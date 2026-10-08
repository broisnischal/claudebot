#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod config;
mod desktop;
mod hooks;
mod server;
mod voice;
mod world;

use config::Config;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};
use tauri::{
    image::Image,
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Listener, LogicalPosition, Manager, Runtime, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
    Window,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_window_state::StateFlags;

const TRAY_ID: &str = "pet";

const ANIMATIONS: &[(&str, &str)] = &[
    ("building", "Run a command"),
    ("testing", "Run tests"),
    ("typing", "Edit a file"),
    ("reading", "Read a file"),
    ("searching", "Search code"),
    ("surfing", "Browse the web"),
    ("planning", "Plan"),
    ("delegating", "Delegate"),
    ("agent", "Send in a subagent"),
    ("alert", "Need permission"),
    ("done", "Done, remind me"),
    ("compacting", "Compact"),
    ("error", "API error"),
    ("celebrate", "Celebrate"),
    ("sleeping", "Sleep"),
    ("zoomies", "Zoomies"),
    ("chase", "Chase the cursor"),
    ("walk", "Go for a walk"),
    ("dance", "Dance"),
    ("trip", "Trip over"),
    ("sneeze", "Sneeze"),
    ("dizzy", "Dizzy"),
];
const THINK_STYLES: &[(&str, &str)] = &[
    ("bubble", "Thought bubble"),
    ("ponder", "Pondering"),
    ("pontificate", "Pontificating"),
    ("cook", "Cooking"),
    ("wizard", "Enchanting"),
    ("vibe", "Vibing"),
    ("gears", "Computing"),
    ("hatch", "Hatching"),
    ("spin", "Flibbertigibbeting"),
    ("wander", "Meandering"),
    ("garden", "Sprouting"),
    ("space", "Hyperspacing"),
    ("weather", "Thundering"),
    ("doodle", "Doodling"),
    ("forge", "Tinkering"),
];
const SIZES: &[(&str, &str)] = &[("small", "Small"), ("medium", "Medium"), ("large", "Large")];
const COLORS: &[(&str, &str)] = &[
    ("pink", "Pink"),
    ("clay", "Claude orange"),
    ("mint", "Mint"),
    ("sky", "Sky"),
    ("lavender", "Lavender"),
    ("ghost", "Ghost"),
];

struct AppState {
    config: Mutex<Config>,
    path: PathBuf,
    first_run: AtomicBool,
    backend: world::Backend,
    #[cfg_attr(target_os = "linux", allow(dead_code))]
    hit: Arc<Mutex<Option<world::Rect>>>,
}

fn port() -> u16 {
    std::env::var("CLAUDEBOT_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(47821)
}

#[tauri::command]
fn get_config(state: tauri::State<AppState>) -> Config {
    state.config.lock().unwrap().clone()
}

#[tauri::command]
fn fit_window<R: Runtime>(
    window: WebviewWindow<R>,
    state: tauri::State<AppState>,
    width: f64,
    height: f64,
) -> Result<(), String> {
    desktop::fit(&window, width, height).map_err(|e| e.to_string())?;
    if state.first_run.swap(false, Ordering::Relaxed) {
        desktop::park_bottom_right(&window, width, height).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn world<R: Runtime>(window: WebviewWindow<R>, state: tauri::State<AppState>) -> world::World {
    world::world(state.backend, &window)
}

#[tauri::command]
fn move_window<R: Runtime>(window: WebviewWindow<R>, state: tauri::State<AppState>, x: i32, y: i32) {
    world::move_to(state.backend, &window, x, y);
}

#[tauri::command]
fn cursor<R: Runtime>(window: WebviewWindow<R>, state: tauri::State<AppState>) -> Option<world::Point> {
    world::cursor(state.backend, &window)
}

#[tauri::command]
fn set_hit_region<R: Runtime>(window: WebviewWindow<R>, state: tauri::State<AppState>, x: f64, y: f64, width: f64, height: f64) {
    let rect = world::Rect { x, y, w: width, h: height };
    #[cfg(target_os = "linux")]
    {
        let _ = &state;
        world::set_hit_region(&window, rect);
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = &window;
        *state.hit.lock().unwrap() = Some(rect);
    }
}

#[tauri::command]
fn notify<R: Runtime>(app: AppHandle<R>, title: String, body: String) {
    let _ = app.notification().builder().title(title).body(body).show();
}

#[tauri::command]
fn set_status<R: Runtime>(app: AppHandle<R>, text: String) {
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let _ = tray.set_tooltip(Some(text));
    }
}

/// Frontend errors end up on stderr, next to everything else the app prints.
#[tauri::command]
fn log(message: String) {
    eprintln!("claudebot[ui]: {message}");
}

#[tauri::command]
fn voice_info(voice: tauri::State<voice::Voice>) -> voice::Info {
    voice.info.lock().unwrap().clone()
}

/// Voice commands from the command line or the menu, for the pet to pass on to the engine.
#[tauri::command]
fn take_voice_commands(voice: tauri::State<voice::Voice>) -> Vec<String> {
    std::mem::take(&mut *voice.pending.lock().unwrap())
}

#[tauri::command]
fn toggle_panel<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    panel(&app, None).map_err(|e| e.to_string())
}

/// The voice panel: fleet, conversation, approvals, memory and settings. `open` None toggles it.
fn panel<R: Runtime>(app: &AppHandle<R>, open: Option<bool>) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window("panel") {
        if open == Some(true) || (open.is_none() && !window.is_visible()?) {
            window.show()?;
            window.set_focus()?;
        } else {
            window.close()?;
        }
        return Ok(());
    }
    if open == Some(false) {
        return Ok(());
    }
    WebviewWindowBuilder::new(app, "panel", WebviewUrl::App("panel.html".into()))
        .title("Claude Bot Voice")
        .inner_size(460.0, 720.0)
        .min_inner_size(360.0, 480.0)
        .decorations(false)
        .build()?;
    Ok(())
}

fn voice_command<R: Runtime>(app: &AppHandle<R>, cmd: String) {
    if cmd == "panel" {
        let _ = panel(app, Some(true));
        return;
    }
    app.state::<voice::Voice>().pending.lock().unwrap().push(cmd);
    let _ = app.emit_to("main", "voice-commands", ());
}

/// Opens the menu at the click. Without a position, GTK parents the menu to the root
/// window, which Wayland refuses to show.
#[tauri::command]
fn show_menu<R: Runtime>(app: AppHandle<R>, window: Window<R>, x: f64, y: f64) -> Result<(), String> {
    let menu = build_menu(&app).map_err(|e| e.to_string())?;
    window.popup_menu_at(&menu, LogicalPosition::new(x, y)).map_err(|e| e.to_string())
}

fn build_menu<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<Menu<R>> {
    let config = app.state::<AppState>().config.lock().unwrap().clone();

    let play = Submenu::with_id(app, "play", "Play animation", true)?;
    for (id, label) in ANIMATIONS {
        play.append(&MenuItem::with_id(app, format!("play:{id}"), *label, true, None::<&str>)?)?;
    }
    let think = Submenu::with_id(app, "think", "Thinking styles", true)?;
    for (id, label) in THINK_STYLES {
        think.append(&MenuItem::with_id(app, format!("play:think:{id}"), *label, true, None::<&str>)?)?;
    }
    let size = Submenu::with_id(app, "size", "Size", true)?;
    for (id, label) in SIZES {
        size.append(&CheckMenuItem::with_id(app, format!("size:{id}"), *label, true, config.size == *id, None::<&str>)?)?;
    }
    let color = Submenu::with_id(app, "color", "Color", true)?;
    for (id, label) in COLORS {
        color.append(&CheckMenuItem::with_id(app, format!("color:{id}"), *label, true, config.color == *id, None::<&str>)?)?;
    }

    let autostart = app.autolaunch().is_enabled().unwrap_or(false);
    let voice = app.state::<voice::Voice>().info.lock().unwrap().clone();
    let talk = match voice.state.as_str() {
        "unavailable" => "Voice unavailable",
        "starting" => "Voice is starting...",
        _ => "Talk to me",
    };
    Menu::with_items(
        app,
        &[
            &MenuItem::with_id(app, "voice:call", talk, voice.state == "running", None::<&str>)?,
            &MenuItem::with_id(app, "voice:panel", "Voice panel", voice.state != "unavailable", None::<&str>)?,
            &PredefinedMenuItem::separator(app)?,
            &CheckMenuItem::with_id(app, "hooks", "React to Claude Code", true, hooks::installed(), None::<&str>)?,
            &PredefinedMenuItem::separator(app)?,
            &play,
            &think,
            &PredefinedMenuItem::separator(app)?,
            &CheckMenuItem::with_id(app, "roam", "Roam around the screen", true, config.roam, None::<&str>)?,
            &CheckMenuItem::with_id(app, "label", "Show status text", true, config.label, None::<&str>)?,
            &CheckMenuItem::with_id(app, "notify", "Notify when Claude is done", true, config.notify, None::<&str>)?,
            &size,
            &color,
            &CheckMenuItem::with_id(app, "top", "Always on top", true, config.always_on_top, None::<&str>)?,
            &CheckMenuItem::with_id(app, "autostart", "Start at login", true, autostart, None::<&str>)?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, "quit", "Quit Claude Bot", true, None::<&str>)?,
        ],
    )
}

fn refresh_tray<R: Runtime>(app: &AppHandle<R>) {
    if let (Some(tray), Ok(menu)) = (app.tray_by_id(TRAY_ID), build_menu(app)) {
        let _ = tray.set_menu(Some(menu));
    }
}

fn update_config<R: Runtime>(app: &AppHandle<R>, change: impl FnOnce(&mut Config)) -> Config {
    let state = app.state::<AppState>();
    let mut config = state.config.lock().unwrap();
    change(&mut config);
    config::save(&state.path, &config);
    let _ = app.emit("config", config.clone());
    config.clone()
}

fn tell<R: Runtime>(app: &AppHandle<R>, kind: MessageDialogKind, text: String) {
    app.dialog().message(text).title("Claude Bot").kind(kind).show(|_| {});
}

fn toggle_hooks<R: Runtime>(app: &AppHandle<R>) {
    if hooks::installed() {
        match hooks::uninstall() {
            Ok(_) => {
                let _ = app.emit("play", "sleeping");
            }
            Err(e) => tell(app, MessageDialogKind::Error, e),
        }
        return;
    }
    match hooks::install(port()) {
        Ok(path) => {
            let _ = app.emit("play", "celebrate");
            tell(
                app,
                MessageDialogKind::Info,
                format!(
                    "Hooks added to {}.\n\nRestart any open Claude Code sessions and I'll follow along.",
                    path.display()
                ),
            );
        }
        Err(e) => tell(app, MessageDialogKind::Error, e),
    }
}

fn on_menu<R: Runtime>(app: &AppHandle<R>, id: &str) {
    match id {
        "quit" => app.exit(0),
        "hooks" => toggle_hooks(app),
        "top" => {
            let config = update_config(app, |c| c.always_on_top = !c.always_on_top);
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_always_on_top(config.always_on_top);
            }
        }
        "roam" => {
            update_config(app, |c| c.roam = !c.roam);
        }
        "label" => {
            update_config(app, |c| c.label = !c.label);
        }
        "notify" => {
            update_config(app, |c| c.notify = !c.notify);
        }
        "autostart" => {
            let launcher = app.autolaunch();
            let _ = if launcher.is_enabled().unwrap_or(false) {
                launcher.disable()
            } else {
                launcher.enable()
            };
        }
        _ => {
            if let Some(cmd) = id.strip_prefix("voice:") {
                voice_command(app, cmd.into());
            } else if let Some(name) = id.strip_prefix("play:") {
                let _ = app.emit("play", name);
            } else if let Some(size) = id.strip_prefix("size:") {
                update_config(app, |c| c.size = size.into());
            } else if let Some(color) = id.strip_prefix("color:") {
                update_config(app, |c| c.color = color.into());
            }
        }
    }
    refresh_tray(app);
}

/// `claudebot --install-hooks` / `--uninstall-hooks` for setting up without the menu.
fn run_cli() -> Option<i32> {
    let arg = std::env::args().nth(1)?;
    let result = match arg.as_str() {
        "--install-hooks" => hooks::install(port()).map(|p| format!("Hooks added to {}", p.display())),
        "--uninstall-hooks" => hooks::uninstall().map(|removed| {
            if removed { "Hooks removed".into() } else { "No hooks to remove".into() }
        }),
        _ => return None,
    };
    Some(match result {
        Ok(msg) => {
            println!("{msg}");
            0
        }
        Err(e) => {
            eprintln!("{e}");
            1
        }
    })
}

fn main() {
    if let Some(code) = run_cli() {
        std::process::exit(code);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            let commands = voice::commands(&args);
            if commands.is_empty() {
                let _ = app.emit("play", "hello");
            }
            for cmd in commands {
                voice_command(app, cmd);
            }
        }))
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, None))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(StateFlags::POSITION)
                .build(),
        )
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            get_config, fit_window, show_menu, log, world, move_window, cursor, set_hit_region, notify, set_status,
            voice_info, take_voice_commands, toggle_panel
        ])
        .on_menu_event(|app, event| on_menu(app, event.id().as_ref()))
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            #[cfg(target_os = "linux")]
            desktop::hyprland_rules();

            let path = app.path().app_config_dir()?.join("config.json");
            let first_run = AtomicBool::new(!path.exists());
            let config = config::load(&path);
            config::save(&path, &config);
            if let Some(window) = app.get_webview_window("main") {
                window.set_always_on_top(config.always_on_top)?;
                // Only Linux needs the resizable trick in desktop::fit.
                #[cfg(not(target_os = "linux"))]
                window.set_resizable(false)?;
            }
            let hit = Arc::new(Mutex::new(None));
            #[cfg(not(target_os = "linux"))]
            if let Some(window) = app.get_webview_window("main") {
                world::spawn_hit_poller(window, hit.clone());
            }
            app.manage(AppState { config: Mutex::new(config), path, first_run, backend: world::detect(), hit });
            let voice = voice::Voice::new(voice::port());
            *voice.pending.lock().unwrap() = voice::commands(&std::env::args().collect::<Vec<_>>());
            app.manage(voice);

            // Hooks from an older version get the newer event list on launch.
            if hooks::installed() && !hooks::up_to_date(port()) {
                if let Err(e) = hooks::install(port()) {
                    eprintln!("claudebot: couldn't refresh hooks: {e}");
                }
            }

            TrayIconBuilder::with_id(TRAY_ID)
                .icon(Image::from_bytes(include_bytes!("../icons/tray.png"))?)
                .tooltip("Claude Bot")
                .menu(&build_menu(app.handle())?)
                .build(app)?;

            server::spawn(app.handle().clone(), port());
            voice::spawn(app.handle().clone());
            let handle = app.handle().clone();
            app.listen_any("voice-status", move |_| refresh_tray(&handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Claude Bot failed to start")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                app.state::<voice::Voice>().stop();
            }
        });
}
