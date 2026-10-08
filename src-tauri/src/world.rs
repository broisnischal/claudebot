//! Where the pet is on the desktop, and moving it there.
//!
//! Windows, macOS and X11 let an app place its own window. Wayland doesn't, except
//! through compositor IPC, which is only wired up for Hyprland. Everywhere else the
//! pet stays put and wanders inside its own window.

use serde::{Deserialize, Serialize};
use tauri::{PhysicalPosition, Runtime, WebviewWindow};

#[derive(Clone, Copy, PartialEq)]
pub enum Backend {
    Native,
    Hyprland,
    Fixed,
}

#[derive(Serialize, Deserialize, Clone, Copy, Default)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    #[serde(alias = "width")]
    pub w: f64,
    #[serde(alias = "height")]
    pub h: f64,
}

#[derive(Serialize)]
pub struct World {
    backend: &'static str,
    monitors: Vec<Rect>,
    window: Option<Rect>,
}

#[derive(Serialize)]
pub struct Point {
    x: f64,
    y: f64,
}

pub fn detect() -> Backend {
    #[cfg(target_os = "linux")]
    {
        let wayland = std::env::var_os("WAYLAND_DISPLAY").is_some()
            && !std::env::var("GDK_BACKEND").is_ok_and(|b| b.starts_with("x11"));
        if wayland {
            return if hypr::available() { Backend::Hyprland } else { Backend::Fixed };
        }
    }
    Backend::Native
}

pub fn world<R: Runtime>(backend: Backend, window: &WebviewWindow<R>) -> World {
    match backend {
        Backend::Native => World {
            backend: "native",
            monitors: window
                .available_monitors()
                .unwrap_or_default()
                .iter()
                .map(|m| {
                    let a = m.work_area();
                    Rect { x: a.position.x as f64, y: a.position.y as f64, w: a.size.width as f64, h: a.size.height as f64 }
                })
                .collect(),
            window: window.outer_position().ok().zip(window.outer_size().ok()).map(|(p, s)| Rect {
                x: p.x as f64,
                y: p.y as f64,
                w: s.width as f64,
                h: s.height as f64,
            }),
        },
        #[cfg(target_os = "linux")]
        Backend::Hyprland => World { backend: "hyprland", monitors: hypr::monitors(), window: hypr::window() },
        _ => World { backend: "fixed", monitors: vec![], window: None },
    }
}

pub fn move_to<R: Runtime>(backend: Backend, window: &WebviewWindow<R>, x: i32, y: i32) {
    match backend {
        Backend::Native => {
            let _ = window.set_position(PhysicalPosition::new(x, y));
        }
        #[cfg(target_os = "linux")]
        Backend::Hyprland => hypr::move_to(x, y),
        _ => {}
    }
}

pub fn cursor<R: Runtime>(backend: Backend, window: &WebviewWindow<R>) -> Option<Point> {
    match backend {
        Backend::Native => window.cursor_position().ok().map(|p| Point { x: p.x, y: p.y }),
        #[cfg(target_os = "linux")]
        Backend::Hyprland => hypr::cursor(),
        _ => None,
    }
}

/// Lets clicks fall through everywhere except `hit` (logical pixels inside the window).
/// Linux gets a real input shape; Windows and macOS toggle click-through as the
/// cursor crosses the pet (see `spawn_hit_poller`).
#[cfg(target_os = "linux")]
pub fn set_hit_region<R: Runtime>(window: &WebviewWindow<R>, hit: Rect) {
    let w = window.clone();
    let _ = window.run_on_main_thread(move || {
        use gtk::prelude::*;
        let Some(gdk) = w.gtk_window().ok().and_then(|g| g.window()) else { return };
        let rect = gtk::cairo::RectangleInt::new(hit.x as i32, hit.y as i32, hit.w.max(1.0) as i32, hit.h.max(1.0) as i32);
        gdk.input_shape_combine_region(&gtk::cairo::Region::create_rectangle(&rect), 0, 0);
    });
}

#[cfg(not(target_os = "linux"))]
pub fn spawn_hit_poller<R: Runtime>(window: WebviewWindow<R>, hit: std::sync::Arc<std::sync::Mutex<Option<Rect>>>) {
    std::thread::spawn(move || {
        let mut ignoring = false;
        loop {
            std::thread::sleep(std::time::Duration::from_millis(33));
            let Some(r) = *hit.lock().unwrap() else { continue };
            let (Ok(c), Ok(p), Ok(scale)) = (window.cursor_position(), window.outer_position(), window.scale_factor()) else {
                continue;
            };
            let (lx, ly) = ((c.x - p.x as f64) / scale, (c.y - p.y as f64) / scale);
            let inside = lx >= r.x && lx < r.x + r.w && ly >= r.y && ly < r.y + r.h;
            if inside == ignoring {
                ignoring = !inside;
                if window.set_ignore_cursor_events(ignoring).is_err() {
                    return;
                }
            }
        }
    });
}

#[cfg(target_os = "linux")]
mod hypr {
    use super::{Point, Rect};
    use serde_json::Value;
    use std::{
        io::{Read, Write},
        os::unix::net::UnixStream,
        path::PathBuf,
        sync::{Mutex, OnceLock},
        time::Duration,
    };

    fn socket() -> Option<PathBuf> {
        let sig = std::env::var("HYPRLAND_INSTANCE_SIGNATURE").ok()?;
        let runtime = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".into());
        [format!("{runtime}/hypr/{sig}/.socket.sock"), format!("/tmp/hypr/{sig}/.socket.sock")]
            .into_iter()
            .map(PathBuf::from)
            .find(|p| p.exists())
    }

    pub fn request(cmd: &str) -> Option<String> {
        let mut stream = UnixStream::connect(socket()?).ok()?;
        stream.set_read_timeout(Some(Duration::from_millis(500))).ok()?;
        stream.write_all(cmd.as_bytes()).ok()?;
        let mut out = String::new();
        stream.read_to_string(&mut out).ok()?;
        Some(out)
    }

    fn json(cmd: &str) -> Option<Value> {
        serde_json::from_str(&request(&format!("j/{cmd}"))?).ok()
    }

    pub fn available() -> bool {
        socket().is_some()
    }

    /// Hyprland 0.55+ is configured in Lua; older releases take hyprlang dispatchers.
    pub fn lua() -> bool {
        static LUA: OnceLock<bool> = OnceLock::new();
        *LUA.get_or_init(|| request("eval return 1").is_some_and(|r| r.trim() == "ok"))
    }

    static ADDRESS: Mutex<Option<String>> = Mutex::new(None);

    // The pet's window: the voice panel shares our pid, so match the title too.
    fn ours() -> Option<Value> {
        let pid = std::process::id() as u64;
        let client = json("clients")?
            .as_array()?
            .iter()
            .find(|c| c["pid"].as_u64() == Some(pid) && c["title"].as_str() == Some("Claude Bot"))?
            .clone();
        *ADDRESS.lock().unwrap() = client["address"].as_str().map(String::from);
        Some(client)
    }

    pub fn window() -> Option<Rect> {
        let c = ours()?;
        Some(Rect {
            x: c["at"][0].as_f64()?,
            y: c["at"][1].as_f64()?,
            w: c["size"][0].as_f64()?,
            h: c["size"][1].as_f64()?,
        })
    }

    pub fn monitors() -> Vec<Rect> {
        let Some(list) = json("monitors") else { return vec![] };
        list.as_array()
            .into_iter()
            .flatten()
            .filter_map(|m| {
                let scale = m["scale"].as_f64().unwrap_or(1.0);
                let (mut w, mut h) = (m["width"].as_f64()? / scale, m["height"].as_f64()? / scale);
                if m["transform"].as_u64().unwrap_or(0) % 2 == 1 {
                    std::mem::swap(&mut w, &mut h);
                }
                let r = |i: usize| m["reserved"][i].as_f64().unwrap_or(0.0);
                Some(Rect {
                    x: m["x"].as_f64()? + r(0),
                    y: m["y"].as_f64()? + r(1),
                    w: w - r(0) - r(2),
                    h: h - r(1) - r(3),
                })
            })
            .collect()
    }

    pub fn move_to(x: i32, y: i32) {
        let address = ADDRESS.lock().unwrap().clone();
        let Some(addr) = address.or_else(|| ours().and_then(|c| c["address"].as_str().map(String::from))) else {
            return;
        };
        let cmd = if lua() {
            format!("dispatch hl.dsp.window.move({{ x = {x}, y = {y}, window = \"address:{addr}\" }})")
        } else {
            format!("dispatch movewindowpixel exact {x} {y},address:{addr}")
        };
        request(&cmd);
    }

    pub fn cursor() -> Option<Point> {
        let c = json("cursorpos")?;
        Some(Point { x: c["x"].as_f64()?, y: c["y"].as_f64()? })
    }
}
