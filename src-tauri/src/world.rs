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

/// Another window the pet can stand on, cling to or hide behind.
#[derive(Serialize)]
pub struct Surface {
    id: String,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
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

/// `w` and `h` are the window's size: Hyprland needs it to tell which monitor the pet is on.
#[cfg_attr(not(target_os = "linux"), allow(unused_variables))]
pub fn move_to<R: Runtime>(backend: Backend, window: &WebviewWindow<R>, x: i32, y: i32, w: i32, h: i32) {
    match backend {
        Backend::Native => {
            let _ = window.set_position(PhysicalPosition::new(x, y));
        }
        #[cfg(target_os = "linux")]
        Backend::Hyprland => hypr::move_to(x, y, w, h),
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

/// Windows the pet can land on, in the same coordinates as `world`. Only Hyprland
/// reports them so far; elsewhere the pet has the floor and the screen edges.
pub fn surfaces(backend: Backend) -> Vec<Surface> {
    match backend {
        #[cfg(target_os = "linux")]
        Backend::Hyprland => hypr::surfaces(),
        _ => vec![],
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
        time::{Duration, Instant},
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
    // The monitor Hyprland has the pet's window on. It draws a window only there, and moving
    // the window doesn't change it, so the pet would vanish walking onto the next screen.
    static MONITOR: Mutex<Option<i64>> = Mutex::new(None);

    // The pet's window: the voice panel shares our pid, so match the title too.
    fn ours() -> Option<Value> {
        let pid = std::process::id() as u64;
        let client = json("clients")?
            .as_array()?
            .iter()
            .find(|c| c["pid"].as_u64() == Some(pid) && c["title"].as_str() == Some("Claude Bot"))?
            .clone();
        *ADDRESS.lock().unwrap() = client["address"].as_str().map(String::from);
        *MONITOR.lock().unwrap() = client["monitor"].as_i64();
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
                let (w, h) = size(m)?;
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

    // A monitor's size in layout pixels: scaled, and swapped when it's turned sideways.
    fn size(m: &Value) -> Option<(f64, f64)> {
        let scale = m["scale"].as_f64().unwrap_or(1.0);
        let (w, h) = (m["width"].as_f64()? / scale, m["height"].as_f64()? / scale);
        Some(if m["transform"].as_u64().unwrap_or(0) % 2 == 1 { (h, w) } else { (w, h) })
    }

    #[derive(Clone)]
    struct Screen {
        id: i64,
        name: String,
        workspace: i64,
        area: Rect,
    }

    static SCREENS: Mutex<Option<(Instant, Vec<Screen>)>> = Mutex::new(None);

    // The monitor under a point. The pet asks on every frame it moves, so the list is
    // read again only every couple of seconds.
    fn screen_at(x: f64, y: f64) -> Option<Screen> {
        let mut cache = SCREENS.lock().unwrap();
        if cache.as_ref().is_none_or(|(at, _)| at.elapsed() > Duration::from_secs(2)) {
            let list = json("monitors")?
                .as_array()?
                .iter()
                .filter_map(|m| {
                    let (w, h) = size(m)?;
                    Some(Screen {
                        id: m["id"].as_i64()?,
                        name: m["name"].as_str()?.to_string(),
                        workspace: m["activeWorkspace"]["id"].as_i64()?,
                        area: Rect { x: m["x"].as_f64()?, y: m["y"].as_f64()?, w, h },
                    })
                })
                .collect();
            *cache = Some((Instant::now(), list));
        }
        let (_, list) = cache.as_ref()?;
        list.iter()
            .find(|s| x >= s.area.x && x < s.area.x + s.area.w && y >= s.area.y && y < s.area.y + s.area.h)
            .cloned()
    }

    pub fn move_to(x: i32, y: i32, w: i32, h: i32) {
        let address = ADDRESS.lock().unwrap().clone();
        let Some(addr) = address.or_else(|| ours().and_then(|c| c["address"].as_str().map(String::from))) else {
            return;
        };
        let mut cmd = if lua() {
            format!("dispatch hl.dsp.window.move({{ x = {x}, y = {y}, window = \"address:{addr}\" }})")
        } else {
            format!("dispatch movewindowpixel exact {x} {y},address:{addr}")
        };
        // Once the middle of the window is over another monitor, hand the window to it. Handing
        // over pulls the window fully inside that monitor, so the move goes in the same batch
        // right after it, and the window never shows anywhere in between.
        let (cx, cy) = (x as f64 + w as f64 / 2.0, y as f64 + h as f64 / 2.0);
        if let Some(screen) = screen_at(cx, cy) {
            let mut on = MONITOR.lock().unwrap();
            if *on != Some(screen.id) {
                *on = Some(screen.id);
                let hand = if lua() {
                    format!(
                        "dispatch hl.dsp.window.move({{ monitor = \"{}\", follow = false, window = \"address:{addr}\" }})",
                        screen.name
                    )
                } else {
                    format!("dispatch movetoworkspacesilent {},address:{addr}", screen.workspace)
                };
                cmd = format!("[[BATCH]]{hand};{cmd}");
            }
        }
        request(&cmd);
    }

    pub fn cursor() -> Option<Point> {
        let c = json("cursorpos")?;
        Some(Point { x: c["x"].as_f64()?, y: c["y"].as_f64()? })
    }

    /// Visible windows on the workspaces each monitor shows (plus pinned ones),
    /// leaving out our own windows and anything fullscreen.
    pub fn surfaces() -> Vec<super::Surface> {
        let pid = std::process::id() as u64;
        let showing: Vec<i64> = json("monitors")
            .and_then(|m| m.as_array().cloned())
            .unwrap_or_default()
            .iter()
            .filter_map(|m| m["activeWorkspace"]["id"].as_i64())
            .collect();
        let Some(clients) = json("clients") else { return vec![] };
        clients
            .as_array()
            .into_iter()
            .flatten()
            .filter(|c| c["pid"].as_u64() != Some(pid))
            .filter(|c| c["mapped"].as_bool() != Some(false) && c["hidden"].as_bool() != Some(true))
            .filter(|c| c["fullscreen"].as_u64().unwrap_or(0) == 0 && c["fullscreen"].as_bool() != Some(true))
            .filter(|c| {
                c["pinned"].as_bool() == Some(true)
                    || c["workspace"]["id"].as_i64().is_some_and(|id| showing.contains(&id))
            })
            .filter_map(|c| {
                Some(super::Surface {
                    id: c["address"].as_str()?.to_string(),
                    x: c["at"][0].as_f64()?,
                    y: c["at"][1].as_f64()?,
                    w: c["size"][0].as_f64()?,
                    h: c["size"][1].as_f64()?,
                })
            })
            .collect()
    }
}
