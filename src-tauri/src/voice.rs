//! The voice engine: a Python process (voice/ in the repo) that listens, talks and runs the Claude
//! session. Claude Bot starts it, hands it a fresh token, restarts it when it dies, and stops it on
//! the way out. Windows talk to it over a local WebSocket with that token.

use serde::Serialize;
use std::{
    collections::hash_map::RandomState,
    hash::BuildHasher,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager, Runtime};

#[derive(Clone, Serialize)]
pub struct Info {
    pub port: u16,
    pub token: String,
    /// "starting", "running", "unavailable"
    pub state: String,
    pub error: String,
}

pub struct Voice {
    pub info: Mutex<Info>,
    child: Mutex<Option<Child>>,
    /// Commands from the CLI (`claudebot --call`) waiting for the pet to pass them on.
    pub pending: Mutex<Vec<String>>,
}

impl Voice {
    pub fn new(port: u16) -> Self {
        let s = RandomState::new();
        let token = format!("{:016x}{:016x}", s.hash_one(1u8), s.hash_one(2u8));
        Self {
            info: Mutex::new(Info { port, token, state: "starting".into(), error: String::new() }),
            child: Mutex::new(None),
            pending: Mutex::new(Vec::new()),
        }
    }

    pub fn stop(&self) {
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

pub fn port() -> u16 {
    std::env::var("CLAUDEBOT_VOICE_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(47822)
}

/// The engine's project folder: $CLAUDEBOT_VOICE_DIR, else voice/ next to the source tree this
/// binary was built from.
fn engine_dir() -> Option<PathBuf> {
    if let Some(dir) = std::env::var_os("CLAUDEBOT_VOICE_DIR") {
        return Some(PathBuf::from(dir));
    }
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../voice");
    dir.join("pyproject.toml").exists().then(|| dir.canonicalize().unwrap_or(dir))
}

fn find_uv() -> Option<PathBuf> {
    let home = std::env::var_os("HOME").map(PathBuf::from);
    let mut candidates: Vec<PathBuf> = std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).map(|d| d.join("uv")).collect())
        .unwrap_or_default();
    if let Some(home) = home {
        candidates.push(home.join(".local/bin/uv"));
        candidates.push(home.join(".cargo/bin/uv"));
    }
    candidates.into_iter().find(|p| p.is_file())
}

fn set_state<R: Runtime>(app: &AppHandle<R>, state: &str, error: &str) {
    let voice = app.state::<Voice>();
    let info = {
        let mut info = voice.info.lock().unwrap();
        info.state = state.into();
        info.error = error.into();
        info.clone()
    };
    let _ = app.emit("voice-status", info);
}

/// Starts the engine and keeps it running for as long as Claude Bot runs.
pub fn spawn<R: Runtime>(app: AppHandle<R>) {
    let (Some(dir), Some(uv)) = (engine_dir(), find_uv()) else {
        set_state(&app, "unavailable", "Voice needs uv and the voice/ folder (set CLAUDEBOT_VOICE_DIR).");
        return;
    };
    thread::spawn(move || {
        let mut backoff = Duration::from_secs(1);
        loop {
            let (port, token) = {
                let voice = app.state::<Voice>();
                let info = voice.info.lock().unwrap();
                (info.port, info.token.clone())
            };
            set_state(&app, "starting", "");
            let started = Instant::now();
            let child = Command::new(&uv)
                .args(["run", "--quiet", "--project"])
                .arg(&dir)
                .args(["python", "-m", "claudebot_voice"])
                .current_dir(&dir)
                .env("CLAUDEBOT_VOICE_PORT", port.to_string())
                .env("CLAUDEBOT_VOICE_TOKEN", &token)
                .env("CLAUDEBOT_PARENT_PID", std::process::id().to_string())
                .stdin(Stdio::null())
                .spawn();
            let child = match child {
                Ok(child) => child,
                Err(e) => {
                    set_state(&app, "unavailable", &format!("Couldn't start the voice engine: {e}"));
                    return;
                }
            };
            let pid = child.id();
            *app.state::<Voice>().child.lock().unwrap() = Some(child);
            let mut up = false;
            // Poll for exit without holding the lock between checks, so stop() can still kill it.
            loop {
                thread::sleep(Duration::from_millis(250));
                let voice = app.state::<Voice>();
                let mut guard = voice.child.lock().unwrap();
                match guard.as_mut() {
                    Some(c) if c.id() == pid => match c.try_wait() {
                        Ok(None) => {}
                        Ok(Some(status)) => {
                            eprintln!("claudebot: voice engine exited ({status})");
                            *guard = None;
                            break;
                        }
                        Err(_) => break,
                    },
                    _ => return, // stopped on purpose
                }
                drop(guard);
                if !up && healthy(port) {
                    up = true;
                    set_state(&app, "running", "");
                }
            }
            set_state(&app, "starting", "The voice engine stopped, restarting it.");
            if started.elapsed() > Duration::from_secs(60) {
                backoff = Duration::from_secs(1);
            }
            thread::sleep(backoff);
            backoff = (backoff * 2).min(Duration::from_secs(30));
        }
    });
}

fn healthy(port: u16) -> bool {
    use std::io::{Read, Write};
    let Ok(mut s) = std::net::TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(300)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_millis(800)));
    let req = format!("GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if s.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 64];
    matches!(s.read(&mut buf), Ok(n) if buf[..n].starts_with(b"HTTP/1.1 200"))
}

/// Voice flags on the command line, as engine commands. `claudebot --call` from a hotkey reaches
/// the running pet through the single-instance plugin.
pub fn commands(args: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    let mut it = args.iter().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--call" | "--interrupt" | "--mute" | "--ptt-start" | "--ptt-stop" | "--panel" => {
                out.push(arg.trim_start_matches("--").to_string())
            }
            "--say" => {
                let text: Vec<&str> = it.by_ref().map(String::as_str).collect();
                out.push(format!("say:{}", text.join(" ")));
            }
            _ => {}
        }
    }
    out
}
