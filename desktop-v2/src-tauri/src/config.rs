use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Config {
    pub server_url: Option<String>,
}

impl Config {}

pub struct ConfigStore {
    path: PathBuf,
    inner: Mutex<Config>,
}

impl ConfigStore {
    pub fn load(path: PathBuf) -> Self {
        let config = fs::read_to_string(&path)
            .ok()
            .and_then(|raw| serde_json::from_str(&raw).ok())
            .unwrap_or_default();
        Self {
            path,
            inner: Mutex::new(config),
        }
    }

    pub fn get(&self) -> Config {
        self.inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
    }

    /// Applies `change` and saves it. If saving fails, the settings in memory
    /// stay as they were, so they never differ from the file.
    pub fn update(&self, change: impl FnOnce(&mut Config)) -> Result<(), String> {
        let mut guard = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut next = guard.clone();
        change(&mut next);
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("Could not create config dir: {e}"))?;
        }
        let raw = serde_json::to_string_pretty(&next).map_err(|e| e.to_string())?;
        fs::write(&self.path, raw).map_err(|e| format!("Could not save config: {e}"))?;
        *guard = next;
        Ok(())
    }
}
