//! Watches desktop notifications on the session D-Bus so the pet can react to them.
//!
//! `dbus-monitor` (part of every D-Bus install) eavesdrops on Notify calls to
//! org.freedesktop.Notifications, whichever daemon answers them (mako, swaync, dunst,
//! GNOME, KDE). Each call's first four strings are the app name, icon, summary and body.

use serde::Serialize;
use tauri::{AppHandle, Runtime};

#[derive(Serialize, Clone)]
struct Note {
    app: String,
    summary: String,
    body: String,
}

#[cfg(target_os = "linux")]
pub fn spawn<R: Runtime>(app: AppHandle<R>) {
    use std::{
        io::{BufRead, BufReader},
        process::{Command, Stdio},
    };
    use tauri::Emitter;

    std::thread::spawn(move || {
        let Ok(mut child) = Command::new("dbus-monitor")
            .args(["--session", "interface='org.freedesktop.Notifications',member='Notify'"])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        else {
            eprintln!("claudebot: dbus-monitor isn't available, so the pet won't see notifications");
            return;
        };
        let Some(out) = child.stdout.take() else { return };
        let mut strings: Option<Vec<String>> = None;
        for line in BufReader::new(out).lines().map_while(Result::ok) {
            let line = line.trim();
            if line.starts_with("method call") && line.contains("member=Notify") {
                strings = Some(Vec::new());
                continue;
            }
            let Some(list) = strings.as_mut() else { continue };
            if let Some(rest) = line.strip_prefix("string \"") {
                list.push(rest.strip_suffix('"').unwrap_or(rest).to_string());
            }
            if list.len() == 4 {
                let note = Note { app: list[0].clone(), summary: list[2].clone(), body: list[3].clone() };
                strings = None;
                let _ = app.emit("desktop-notification", note);
            }
        }
    });
}

#[cfg(not(target_os = "linux"))]
pub fn spawn<R: Runtime>(_app: AppHandle<R>) {}
