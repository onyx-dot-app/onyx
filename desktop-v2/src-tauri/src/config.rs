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
    /// The last valid managed `ServerURL`, used while the policy is invalid.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub managed_server_url: Option<String>,
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
        let config = match fs::read_to_string(&path) {
            Ok(raw) => {
                // Windows PowerShell 5.1 writes UTF-8 with a byte order mark.
                let raw = raw.strip_prefix('\u{feff}').unwrap_or(&raw);
                serde_json::from_str(raw).unwrap_or_else(|e| {
                    log::error!("{} is not valid; using defaults: {e}", path.display());
                    Config::default()
                })
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Config::default(),
            Err(e) => {
                log::error!("could not read {}; using defaults: {e}", path.display());
                Config::default()
            }
        };
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_a_config_file_with_a_byte_order_mark() {
        let dir = std::env::temp_dir().join(format!("onyx-config-bom-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("config.json");
        fs::write(
            &path,
            "\u{feff}{\"serverUrl\": \"https://x.example.com\", \"hotkey\": \"Alt+Space\"}",
        )
        .unwrap();
        let config = ConfigStore::load(path).get();
        let _ = fs::remove_dir_all(&dir);
        assert_eq!(config.server_url.as_deref(), Some("https://x.example.com"));
        assert_eq!(config.hotkey(), "Alt+Space");
    }
}
