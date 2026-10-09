//! Window placement quirks that differ per desktop.

use tauri::{LogicalSize, PhysicalPosition, Runtime, WebviewWindow};

/// Locks the window to exactly this size. GTK won't shrink a window below the
/// webview's natural size, so on Linux the window is "resizable" with min and max
/// pinned together. That also tells tiling compositors (Hyprland, sway) to float it.
pub fn fit<R: Runtime>(window: &WebviewWindow<R>, width: f64, height: f64) -> tauri::Result<()> {
    let size = LogicalSize::new(width, height);
    window.set_min_size(None::<LogicalSize<f64>>)?;
    window.set_max_size(None::<LogicalSize<f64>>)?;
    window.set_size(size)?;
    window.set_min_size(Some(size))?;
    window.set_max_size(Some(size))
}

/// First launch: sit in the bottom-right corner of the screen instead of wherever
/// the OS drops new windows. Later launches restore the last position.
pub fn park_bottom_right<R: Runtime>(window: &WebviewWindow<R>, width: f64, height: f64) -> tauri::Result<()> {
    let Some(monitor) = window.current_monitor()?.or(window.primary_monitor()?) else {
        return Ok(());
    };
    let area = monitor.work_area();
    let scale = monitor.scale_factor();
    let margin = 24.0 * scale;
    let x = area.position.x as f64 + area.size.width as f64 - width * scale - margin;
    let y = area.position.y as f64 + area.size.height as f64 - height * scale - margin;
    window.set_position(PhysicalPosition::new(x, y))
}

/// Puts the voice HUD in the bottom-left corner of the rightmost monitor (on a single screen, that
/// screen). Hyprland moves it through its IPC; elsewhere Tauri does.
pub fn place_hud<R: Runtime>(window: &WebviewWindow<R>, height: f64) -> tauri::Result<()> {
    #[cfg(target_os = "linux")]
    if std::env::var_os("HYPRLAND_INSTANCE_SIGNATURE").is_some() {
        hyprland_place_hud(height);
        return Ok(());
    }
    let monitors = window.available_monitors()?;
    let Some(monitor) = monitors.iter().max_by_key(|m| m.position().x) else {
        return Ok(());
    };
    let area = monitor.work_area();
    let scale = monitor.scale_factor();
    let x = area.position.x as f64 + 24.0 * scale;
    let y = area.position.y as f64 + area.size.height as f64 - (height + 24.0) * scale;
    window.set_position(PhysicalPosition::new(x, y))
}

#[cfg(target_os = "linux")]
fn hyprland_place_hud(height: f64) {
    use std::process::Command;
    let json = |what: &str| -> serde_json::Value {
        Command::new("hyprctl")
            .args([what, "-j"])
            .output()
            .ok()
            .and_then(|o| serde_json::from_slice(&o.stdout).ok())
            .unwrap_or_default()
    };
    let monitors = json("monitors");
    let Some(m) = monitors.as_array().and_then(|ms| ms.iter().max_by_key(|m| m["x"].as_i64().unwrap_or(0))) else {
        return;
    };
    let scale = m["scale"].as_f64().unwrap_or(1.0);
    let reserved = |i: usize| m["reserved"][i].as_f64().unwrap_or(0.0);
    let x = m["x"].as_f64().unwrap_or(0.0) + reserved(0) + 24.0;
    let y = m["y"].as_f64().unwrap_or(0.0) + m["height"].as_f64().unwrap_or(1080.0) / scale - reserved(3) - height - 24.0;
    let pid = std::process::id() as u64;
    let clients = json("clients");
    let Some(addr) = clients.as_array().and_then(|cs| {
        cs.iter()
            .find(|c| c["pid"].as_u64() == Some(pid) && c["title"].as_str() == Some("Claude Bot HUD"))
            .and_then(|c| c["address"].as_str().map(String::from))
    }) else {
        return;
    };
    hyprland_move(&addr, x, y);
}

/// Puts one of my windows at a desktop position (layout pixels). On Hyprland the window is also
/// handed to the monitor there: Hyprland draws a window only on its own monitor, however far it's
/// moved.
pub fn place<R: Runtime>(window: &WebviewWindow<R>, title: &str, x: f64, y: f64) -> tauri::Result<()> {
    #[cfg(target_os = "linux")]
    if std::env::var_os("HYPRLAND_INSTANCE_SIGNATURE").is_some() {
        hyprland_place(title, x, y);
        return Ok(());
    }
    window.set_position(tauri::LogicalPosition::new(x, y))
}

#[cfg(target_os = "linux")]
fn hyprland_place(title: &str, x: f64, y: f64) {
    use std::process::Command;
    let pid = std::process::id() as u64;
    // a window built a moment ago is mapped a moment later
    for _ in 0..40 {
        let clients: serde_json::Value = Command::new("hyprctl")
            .args(["clients", "-j"])
            .output()
            .ok()
            .and_then(|o| serde_json::from_slice(&o.stdout).ok())
            .unwrap_or_default();
        let addr = clients.as_array().and_then(|cs| {
            cs.iter()
                .find(|c| c["pid"].as_u64() == Some(pid) && c["title"].as_str() == Some(title))
                .and_then(|c| c["address"].as_str().map(String::from))
        });
        if let Some(addr) = addr {
            hyprland_move(&addr, x, y);
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
}

/// Hand the window to the monitor under (x, y), then move it there, in one batch so it never shows
/// in between.
#[cfg(target_os = "linux")]
fn hyprland_move(addr: &str, x: f64, y: f64) {
    use std::process::Command;
    let monitors: serde_json::Value = Command::new("hyprctl")
        .args(["monitors", "-j"])
        .output()
        .ok()
        .and_then(|o| serde_json::from_slice(&o.stdout).ok())
        .unwrap_or_default();
    let name = monitors.as_array().and_then(|ms| {
        ms.iter().find(|m| {
            let scale = m["scale"].as_f64().unwrap_or(1.0);
            let (mx, my) = (m["x"].as_f64().unwrap_or(0.0), m["y"].as_f64().unwrap_or(0.0));
            let (mw, mh) = (m["width"].as_f64().unwrap_or(0.0) / scale, m["height"].as_f64().unwrap_or(0.0) / scale);
            x + 1.0 >= mx && x + 1.0 < mx + mw && y + 1.0 >= my && y + 1.0 < my + mh
        })
        .and_then(|m| m["name"].as_str().map(String::from))
    });
    let (x, y) = (x.round() as i64, y.round() as i64);
    let mut batch = Vec::new();
    if let Some(name) = name {
        batch.push(format!("dispatch hl.dsp.window.move({{ monitor = \"{name}\", follow = false, window = \"address:{addr}\" }})"));
    }
    batch.push(format!("dispatch hl.dsp.window.move({{ x = {x}, y = {y}, window = \"address:{addr}\" }})"));
    let ok = Command::new("hyprctl").args(["--batch", &batch.join(" ; ")]).output()
        .is_ok_and(|o| o.status.success() && !String::from_utf8_lossy(&o.stdout).contains("rror"));
    if !ok {
        let _ = Command::new("hyprctl").args(["dispatch", "movewindowpixel", &format!("exact {x} {y},address:{addr}")]).output();
    }
}

/// Hyprland ignores "always on top" from clients and blurs behind transparent
/// windows. Register a rule for this session (nothing is written to the user's
/// config) before the window first appears. No animation, so walking is smooth,
/// and no focus-follows-mouse, so the pet never steals focus by strolling under the cursor.
#[cfg(target_os = "linux")]
pub fn hyprland_rules() {
    use std::process::Command;

    if std::env::var_os("HYPRLAND_INSTANCE_SIGNATURE").is_none() {
        return;
    }
    let ok = |args: &[&str]| {
        Command::new("hyprctl")
            .args(args)
            .output()
            .is_ok_and(|o| o.status.success() && String::from_utf8_lossy(&o.stdout).trim() == "ok")
    };

    // Lua config (Hyprland 0.55 and later). The pet and the voice panel share the app class.
    let lua = r#"hl.window_rule({
        match = { class = "^claudebot$", title = "^Claude Bot$" },
        float = true, pin = true, border_size = 0, no_shadow = true, no_blur = true,
        no_dim = true, no_initial_focus = true, no_follow_mouse = true, no_anim = true,
        opacity = "1 1", tag = "-default-opacity",
        move = { "(monitor_w-window_w-24)", "(monitor_h-window_h-24)" },
    })
    hl.window_rule({
        match = { class = "^claudebot$", title = "^Claude Bot HUD$" },
        float = true, pin = true, border_size = 0, no_shadow = true, no_blur = true,
        no_dim = true, no_initial_focus = true, no_follow_mouse = true, no_anim = true,
        opacity = "1 1", tag = "-default-opacity",
    })
    hl.window_rule({
        match = { class = "^claudebot$", title = "^Claude Bot Play$" },
        float = true, pin = true, border_size = 0, no_shadow = true, no_blur = true,
        no_dim = true, no_initial_focus = true, no_follow_mouse = true, no_anim = true,
        opacity = "1 1", tag = "-default-opacity",
    })
    hl.window_rule({
        match = { class = "^claudebot$", title = "^Claude Bot Voice$" },
        float = true, size = { 460, 720 },
        move = { "(monitor_w-window_w-24)", "(monitor_h-window_h-190)" },
    })"#;
    if ok(&["eval", lua]) {
        return;
    }

    // hyprlang config (older releases).
    let batch = ["float", "pin", "noborder", "noshadow", "noblur", "nodim", "noinitialfocus", "noanim", "opacity 1 override"]
        .map(|rule| format!("keyword windowrulev2 {rule}, class:^(claudebot)$, title:^(Claude Bot)$"))
        .join(" ; ")
        + " ; keyword windowrulev2 float, class:^(claudebot)$, title:^(Claude Bot Voice)$"
        + " ; keyword windowrulev2 size 460 720, class:^(claudebot)$, title:^(Claude Bot Voice)$"
        + &["float", "pin", "noborder", "noshadow", "noblur", "nodim", "noinitialfocus", "noanim"]
            .map(|rule| format!(" ; keyword windowrulev2 {rule}, class:^(claudebot)$, title:^(Claude Bot HUD)$"))
            .join("")
        + &["float", "pin", "noborder", "noshadow", "noblur", "nodim", "noinitialfocus", "noanim"]
            .map(|rule| format!(" ; keyword windowrulev2 {rule}, class:^(claudebot)$, title:^(Claude Bot Play)$"))
            .join("");
    ok(&["--batch", &batch]);
}
