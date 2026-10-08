use serde::{Deserialize, Serialize};
use std::{fs, path::Path};

#[derive(Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Config {
    pub size: String,
    pub color: String,
    pub always_on_top: bool,
    pub sleep_after_mins: u32,
    pub roam: bool,
    pub notify: bool,
    pub label: bool,
    pub weather: bool,
    pub notify_react: bool,
    /// Apps whose desktop notifications the pet ignores (case-insensitive names).
    pub quiet_apps: Vec<String>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            size: "medium".into(),
            color: "pink".into(),
            always_on_top: true,
            sleep_after_mins: 5,
            roam: true,
            notify: true,
            label: true,
            weather: true,
            notify_react: true,
            quiet_apps: vec![],
        }
    }
}

pub fn load(path: &Path) -> Config {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

pub fn save(path: &Path, config: &Config) {
    if let Some(dir) = path.parent() {
        let _ = fs::create_dir_all(dir);
    }
    if let Ok(json) = serde_json::to_vec_pretty(config) {
        let _ = fs::write(path, json);
    }
}
