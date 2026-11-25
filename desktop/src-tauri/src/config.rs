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
    /// Per server, the fingerprints (`token_fingerprint`) of the tokens that a
    /// sign-out could not delete from the OS store. These tokens are never
    /// used again. The tokens themselves are never written here.
    #[serde(
        default,
        deserialize_with = "lenient_rejected_tokens",
        skip_serializing_if = "BTreeMap::is_empty"
    )]
    pub rejected_tokens: BTreeMap<String, BTreeSet<String>>,
    /// Windows: the earlier app's program folder that is still to delete
    /// (`earlier_install.rs`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub earlier_install_dir: Option<String>,
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
    /// user deleted the app's data. A token that a sign-out could not delete
    /// is never used, with or without a record.
    pub fn trusts_stored_token(&self, server: &str, needs_record: bool) -> bool {
        !needs_record || self.session_servers.contains(server)
    }

    /// Whether `token` is the one a sign-out from `server` could not delete.
    pub fn rejects_token(&self, server: &str, token: &str) -> bool {
        self.rejected_tokens
            .get(server)
            .is_some_and(|set| set.contains(&token_fingerprint(server, token)))
    }
}

/// Reads `rejectedTokens` without ever failing the whole config: a server
/// maps to one fingerprint (the first format) or a list of them. Any other
/// value is dropped and logged.
fn lenient_rejected_tokens<'de, D>(
    deserializer: D,
) -> Result<BTreeMap<String, BTreeSet<String>>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    Ok(rejected_tokens_from(value))
}

fn rejected_tokens_from(value: serde_json::Value) -> BTreeMap<String, BTreeSet<String>> {
    use serde_json::Value;
    let Value::Object(entries) = value else {
        log::warn!("rejectedTokens in config.json is not an object; ignored");
        return BTreeMap::new();
    };
    let mut out = BTreeMap::new();
    for (server, value) in entries {
        let set: Option<BTreeSet<String>> = match value {
            Value::String(one) => Some(BTreeSet::from([one])),
            // A list keeps its valid fingerprints; only bad items go.
            Value::Array(items) => {
                let mut skipped_invalid = false;
                let set: BTreeSet<String> = items
                    .into_iter()
                    .filter_map(|item| match item {
                        Value::String(s) => Some(s),
                        _ => {
                            skipped_invalid = true;
                            None
                        }
                    })
                    .collect();
                if skipped_invalid {
                    log::warn!("a rejectedTokens item in config.json is not valid; ignored");
                }
                Some(set)
            }
            _ => None,
        };
        match set {
            Some(set) if !set.is_empty() => {
                out.insert(server, set);
            }
            Some(_) => {}
            None => log::warn!("a rejectedTokens entry in config.json is not valid; ignored"),
        }
    }
    out
}

/// The fingerprints to record when a sign-out cannot delete the stored
/// token: every token that can still be loaded for `server`. The token in
/// memory and the stored one differ when a renewed token could not be saved.
pub fn tokens_to_reject(
    server: &str,
    in_memory: Option<&str>,
    stored: Option<&str>,
) -> BTreeSet<String> {
    in_memory
        .into_iter()
        .chain(stored)
        .map(|token| token_fingerprint(server, token))
        .collect()
}

/// SHA-256 (hex) of the server and the token, so a rejected token can be
/// recognized without keeping it.
pub fn token_fingerprint(server: &str, token: &str) -> String {
    use sha2::{Digest, Sha256};
    let digest = Sha256::new()
        .chain_update(server.as_bytes())
        .chain_update([0u8])
        .chain_update(token.as_bytes())
        .finalize();
    digest.iter().map(|b| format!("{b:02x}")).collect()
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
    fn a_rejected_token_is_known_by_its_fingerprint_only() {
        let fingerprint = token_fingerprint(SERVER, "secret-token");
        assert_eq!(fingerprint.len(), 64);
        assert!(!fingerprint.contains("secret-token"));
        assert_ne!(fingerprint, token_fingerprint(SERVER, "other-token"));
        assert_ne!(
            fingerprint,
            token_fingerprint("https://other.example.com", "secret-token")
        );
        let mut config = Config::default();
        assert!(!config.rejects_token(SERVER, "secret-token"));
        config
            .rejected_tokens
            .insert(SERVER.to_string(), BTreeSet::from([fingerprint]));
        assert!(config.rejects_token(SERVER, "secret-token"));
        assert!(!config.rejects_token(SERVER, "new-token"));
        assert!(!config.rejects_token("https://other.example.com", "secret-token"));
        let raw = serde_json::to_string(&config).unwrap();
        assert!(raw.contains("rejectedTokens"));
        assert!(!raw.contains("secret-token"));
    }

    #[test]
    fn sign_out_rejects_both_the_renewed_and_the_stored_token() {
        let both = tokens_to_reject(SERVER, Some("renewed"), Some("stored"));
        assert_eq!(
            both,
            BTreeSet::from([
                token_fingerprint(SERVER, "renewed"),
                token_fingerprint(SERVER, "stored"),
            ])
        );
        assert_eq!(
            tokens_to_reject(SERVER, Some("same"), Some("same")).len(),
            1
        );
        assert_eq!(
            tokens_to_reject(SERVER, None, Some("stored")),
            BTreeSet::from([token_fingerprint(SERVER, "stored")])
        );
        assert!(tokens_to_reject(SERVER, None, None).is_empty());
        let mut config = Config::default();
        config.rejected_tokens.insert(SERVER.to_string(), both);
        assert!(config.rejects_token(SERVER, "renewed"));
        assert!(config.rejects_token(SERVER, "stored"));
    }

    #[test]
    fn rejected_tokens_read_both_formats() {
        let config: Config = serde_json::from_str(
            r#"{"serverUrl": "https://a.example.com",
                "rejectedTokens": {"https://a.example.com": "aa", "https://b.example.com": ["bb", "cc"]}}"#,
        )
        .unwrap();
        assert_eq!(config.server_url.as_deref(), Some("https://a.example.com"));
        assert_eq!(
            config.rejected_tokens.get("https://a.example.com"),
            Some(&BTreeSet::from(["aa".to_string()]))
        );
        assert_eq!(
            config.rejected_tokens.get("https://b.example.com"),
            Some(&BTreeSet::from(["bb".to_string(), "cc".to_string()]))
        );
        // Written in the list format only.
        let raw = serde_json::to_string(&config).unwrap();
        assert!(raw.contains(r#""https://a.example.com":["aa"]"#));
    }

    #[test]
    fn a_bad_rejected_tokens_value_keeps_the_other_settings() {
        for bad in [
            r#""garbage""#,
            "42",
            r#"{"https://a.example.com": 7}"#,
            r#"{"https://a.example.com": [1, null]}"#,
        ] {
            let config: Config = serde_json::from_str(&format!(
                r#"{{"serverUrl": "https://a.example.com", "hotkey": "Alt+Space", "rejectedTokens": {bad}}}"#
            ))
            .unwrap();
            assert_eq!(config.server_url.as_deref(), Some("https://a.example.com"));
            assert_eq!(config.hotkey(), "Alt+Space");
            assert!(config.rejected_tokens.is_empty(), "{bad}");
        }
        let mixed: Config = serde_json::from_str(
            r#"{"rejectedTokens": {"https://a.example.com": 7, "https://b.example.com": "bb"}}"#,
        )
        .unwrap();
        assert_eq!(mixed.rejected_tokens.len(), 1);
        // The valid fingerprints of a list stay when one item is bad.
        let partly: Config = serde_json::from_str(
            r#"{"rejectedTokens": {"https://a.example.com": ["aa", 1, "bb"]}}"#,
        )
        .unwrap();
        assert_eq!(
            partly.rejected_tokens.get("https://a.example.com"),
            Some(&BTreeSet::from(["aa".to_string(), "bb".to_string()]))
        );
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
