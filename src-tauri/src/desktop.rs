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
        + " ; keyword windowrulev2 size 460 720, class:^(claudebot)$, title:^(Claude Bot Voice)$";
    ok(&["--batch", &batch]);
}
