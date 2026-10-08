//! Adds and removes the Claude Code hooks that report activity to the pet.
//!
//! Every hook pipes Claude Code's JSON payload to the pet's local server with curl.
//! The URL path doubles as the marker that tells our entries apart from anyone else's.

use serde_json::{json, Map, Value};
use std::{
    env, fs,
    path::{Path, PathBuf},
};

const MARKER: &str = "/claudebot/hook";

/// Events the pet listens to, with the matcher each one needs.
const EVENTS: &[(&str, Option<&str>)] = &[
    ("SessionStart", None),
    ("UserPromptSubmit", None),
    ("PreToolUse", Some("*")),
    ("PostToolUse", Some("*")),
    ("PostToolUseFailure", Some("*")),
    ("PermissionRequest", Some("*")),
    ("Notification", None),
    ("Stop", None),
    ("StopFailure", None),
    ("SubagentStart", None),
    ("SubagentStop", None),
    ("PreCompact", None),
    ("PostCompact", None),
    ("SessionEnd", None),
];

pub fn settings_path() -> Option<PathBuf> {
    let dir = match env::var_os("CLAUDE_CONFIG_DIR") {
        Some(dir) => PathBuf::from(dir),
        None => env::home_dir()?.join(".claude"),
    };
    Some(dir.join("settings.json"))
}

/// `|| true` keeps Claude Code quiet when the pet isn't running.
fn command(port: u16) -> String {
    format!("curl -s -m 2 --data-binary @- http://127.0.0.1:{port}{MARKER} || true")
}

fn read(path: &Path) -> Result<Value, String> {
    match fs::read_to_string(path) {
        Ok(text) if text.trim().is_empty() => Ok(json!({})),
        Ok(text) => serde_json::from_str(&text)
            .map_err(|e| format!("{} isn't valid JSON ({e}), so I left it alone.", path.display())),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(json!({})),
        Err(e) => Err(format!("Couldn't read {}: {e}", path.display())),
    }
}

fn write(path: &Path, value: &Value) -> Result<(), String> {
    let fail = |e: std::io::Error| format!("Couldn't write {}: {e}", path.display());
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(fail)?;
    }
    // Keep one copy of the settings as they were before the pet ever touched them.
    let backup = path.with_extension("json.claudebot-backup");
    if path.exists() && !backup.exists() {
        fs::copy(path, &backup).map_err(fail)?;
    }
    let mut text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    text.push('\n');
    let tmp = path.with_extension("json.claudebot-tmp");
    fs::write(&tmp, text).map_err(fail)?;
    fs::rename(&tmp, path).map_err(fail)
}

fn is_ours(hook: &Value) -> bool {
    hook.get("command")
        .and_then(Value::as_str)
        .is_some_and(|c| c.contains(MARKER))
}

/// Drops our hook entries, then any groups and events left empty. Returns whether anything changed.
fn strip(root: &mut Value) -> bool {
    let Some(events) = root.get_mut("hooks").and_then(Value::as_object_mut) else {
        return false;
    };
    let mut changed = false;
    for groups in events.values_mut() {
        let Some(groups) = groups.as_array_mut() else { continue };
        for group in groups.iter_mut() {
            if let Some(hooks) = group.get_mut("hooks").and_then(Value::as_array_mut) {
                let before = hooks.len();
                hooks.retain(|h| !is_ours(h));
                changed |= hooks.len() != before;
            }
        }
        groups.retain(|g| g.get("hooks").and_then(Value::as_array).map_or(true, |h| !h.is_empty()));
    }
    events.retain(|_, groups| groups.as_array().map_or(true, |g| !g.is_empty()));
    if events.is_empty() {
        root.as_object_mut().map(|o| o.remove("hooks"));
    }
    changed
}

/// Our hook commands per event name.
fn ours_by_event(root: &Value) -> Vec<(String, String)> {
    let Some(events) = root.get("hooks").and_then(Value::as_object) else { return vec![] };
    events
        .iter()
        .flat_map(|(event, groups)| {
            groups
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|g| g.get("hooks").and_then(Value::as_array))
                .flatten()
                .filter(|h| is_ours(h))
                .filter_map(move |h| Some((event.clone(), h.get("command")?.as_str()?.to_string())))
        })
        .collect()
}

pub fn installed() -> bool {
    let Some(path) = settings_path() else { return false };
    read(&path).is_ok_and(|root| !ours_by_event(&root).is_empty())
}

/// True when every event has exactly our current command, so an older install
/// (fewer events, another port) gets refreshed on launch.
pub fn up_to_date(port: u16) -> bool {
    let Some(path) = settings_path() else { return false };
    let Ok(root) = read(&path) else { return false };
    let ours = ours_by_event(&root);
    ours.len() == EVENTS.len()
        && EVENTS.iter().all(|(event, _)| ours.iter().any(|(e, c)| e == event && *c == command(port)))
}

pub fn install(port: u16) -> Result<PathBuf, String> {
    let path = settings_path().ok_or("Couldn't find the home directory.")?;
    let mut root = read(&path)?;
    if !root.is_object() {
        return Err(format!("{} isn't a JSON object, so I left it alone.", path.display()));
    }
    strip(&mut root);

    let events = root
        .as_object_mut()
        .unwrap()
        .entry("hooks")
        .or_insert_with(|| json!({}))
        .as_object_mut()
        .ok_or("\"hooks\" in settings.json isn't an object, so I left it alone.")?;

    for (event, matcher) in EVENTS {
        let mut group = Map::new();
        if let Some(m) = matcher {
            group.insert("matcher".into(), json!(m));
        }
        group.insert(
            "hooks".into(),
            json!([{ "type": "command", "command": command(port), "timeout": 5 }]),
        );
        events
            .entry(*event)
            .or_insert_with(|| json!([]))
            .as_array_mut()
            .ok_or(format!("\"hooks.{event}\" in settings.json isn't a list."))?
            .push(Value::Object(group));
    }

    write(&path, &root)?;
    Ok(path)
}

pub fn uninstall() -> Result<bool, String> {
    let path = settings_path().ok_or("Couldn't find the home directory.")?;
    let mut root = read(&path)?;
    if !strip(&mut root) {
        return Ok(false);
    }
    write(&path, &root)?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn install_then_strip_restores_other_hooks() {
        let original = json!({
            "model": "opus",
            "hooks": {
                "Stop": [{ "hooks": [{ "type": "command", "command": "notify-send done" }] }]
            }
        });
        let mut root = original.clone();
        strip(&mut root);
        assert_eq!(root, original);

        let events = root["hooks"].as_object_mut().unwrap();
        for (event, _) in EVENTS {
            events
                .entry(*event)
                .or_insert_with(|| json!([]))
                .as_array_mut()
                .unwrap()
                .push(json!({ "hooks": [{ "type": "command", "command": command(47821) }] }));
        }
        assert!(strip(&mut root));
        assert_eq!(root, original);
    }

    #[test]
    fn strip_removes_empty_hooks_key() {
        let mut root = json!({ "hooks": { "Stop": [{ "hooks": [{ "command": command(1) }] }] } });
        assert!(strip(&mut root));
        assert_eq!(root, json!({}));
    }
}
