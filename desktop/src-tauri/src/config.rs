use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

#[cfg(target_os = "macos")]
pub const DEFAULT_HOTKEY: &str = "CommandOrControl+Shift+Space";
// Windows and some Linux desktops already use Ctrl+Shift+Space (IME switch).
#[cfg(not(target_os = "macos"))]
pub const DEFAULT_HOTKEY: &str = "Control+Alt+Space";

/// Windows keeps Credential Manager entries when the app is uninstalled or its
/// data is deleted. There a stored token is used only if this install's
/// config records that it saved one (`Config::session_servers`).
pub const TOKEN_NEEDS_RECORD: bool = cfg!(target_os = "windows");

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
    /// Server origins this install saved a session token for. Written only
    /// where `TOKEN_NEEDS_RECORD` is set.
    #[serde(default, skip_serializing_if = "BTreeSet::is_empty")]
    pub session_servers: BTreeSet<String>,
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

    /// Whether a token found in the OS store for `server` may be used. A
    /// token with no record came from an earlier install, or from before the
    /// user deleted the app's data.
    pub fn trusts_stored_token(&self, server: &str, needs_record: bool) -> bool {
        !needs_record || self.session_servers.contains(server)
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

    const SERVER: &str = "https://onyx.example.com";

    #[test]
    fn stored_token_needs_a_record_where_required() {
        let mut config = Config::default();
        assert!(!config.trusts_stored_token(SERVER, true));
        config.session_servers.insert(SERVER.to_string());
        assert!(config.trusts_stored_token(SERVER, true));
        assert!(!config.trusts_stored_token("https://other.example.com", true));
    }

    #[test]
    fn stored_token_is_trusted_where_no_record_is_required() {
        assert!(Config::default().trusts_stored_token(SERVER, false));
    }

    #[test]
    fn empty_session_record_is_not_written() {
        let raw = serde_json::to_string(&Config::default()).unwrap();
        assert!(!raw.contains("sessionServers"));
    }

    #[test]
    fn session_record_survives_a_reload_and_not_a_data_wipe() {
        let dir =
            std::env::temp_dir().join(format!("onyx-desktop-config-test-{}", std::process::id()));
        let path = dir.join("config.json");
        let store = ConfigStore::load(path.clone());
        store
            .update(|c| {
                c.session_servers.insert(SERVER.to_string());
            })
            .unwrap();
        assert!(ConfigStore::load(path.clone())
            .get()
            .trusts_stored_token(SERVER, true));

        fs::remove_dir_all(&dir).unwrap();
        assert!(!ConfigStore::load(path)
            .get()
            .trusts_stored_token(SERVER, true));
    }

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
