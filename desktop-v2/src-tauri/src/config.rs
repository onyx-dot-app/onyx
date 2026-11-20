use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

#[cfg(target_os = "macos")]
pub const DEFAULT_HOTKEY: &str = "CommandOrControl+Shift+Space";
// Windows and some Linux desktops already use Ctrl+Shift+Space (IME switch).
#[cfg(not(target_os = "macos"))]
pub const DEFAULT_HOTKEY: &str = "Control+Alt+Space";

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Config {
    pub server_url: Option<String>,
    pub hotkey: Option<String>,
    pub zoom: Option<f64>,
    /// The desktop pet is on screen (an easter egg, see aonyx.rs).
    pub aonyx: Option<bool>,
    /// Where the pet sits, in logical screen coordinates.
    pub aonyx_position: Option<[f64; 2]>,
    /// Notify when a launcher answer finishes while the launcher is hidden.
    pub notify_answers: Option<bool>,
    /// The launcher's last agent, by server origin. No entry: the default agent.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub launcher_agents: BTreeMap<String, i64>,
}

impl Config {
    pub fn zoom(&self) -> f64 {
        self.zoom.unwrap_or(1.0)
    }

    pub fn hotkey(&self) -> String {
        self.hotkey
            .clone()
            .unwrap_or_else(|| DEFAULT_HOTKEY.to_string())
    }

    pub fn notify_answers(&self) -> bool {
        self.notify_answers.unwrap_or(true)
    }
}

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
        // Written beside the file, then renamed over it, so a failed write
        // never leaves a truncated settings file.
        let tmp = self.path.with_extension("json.tmp");
        fs::write(&tmp, raw).map_err(|e| format!("Could not save config: {e}"))?;
        fs::rename(&tmp, &self.path).map_err(|e| format!("Could not save config: {e}"))?;
        *guard = next;
        Ok(())
    }
}
