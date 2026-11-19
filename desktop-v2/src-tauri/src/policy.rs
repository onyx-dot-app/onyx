//! Managed configuration that IT pushes with an MDM (Kandji, Jamf, Intune) or
//! Group Policy. A managed value wins over the user's `config.json` value.
//!
//! - macOS: forced managed preferences for the app's bundle id.
//! - Windows: `HKLM\SOFTWARE\Policies\Onyx\Desktop`, then the same key in HKCU.
//! - Linux: `/etc/onyx-desktop/policy.json`.

use std::str::FromStr;

use tauri::{AppHandle, Manager};
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_global_shortcut::Shortcut;

use crate::api::normalize_server_url;
use crate::state::AppState;

const SERVER_URL: &str = "ServerURL";
const LOCK_SERVER_URL: &str = "LockServerURL";
const DISABLE_AUTO_UPDATE: &str = "DisableAutoUpdate";
const LAUNCHER_SHORTCUT: &str = "LauncherShortcut";
const DISABLE_LAUNCHER: &str = "DisableLauncher";
const LAUNCH_AT_LOGIN: &str = "LaunchAtLogin";

/// A value as the platform store holds it.
#[derive(Debug, Clone, PartialEq)]
pub enum RawValue {
    Str(String),
    Bool(bool),
    Int(i64),
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Policy {
    pub server_url: Option<String>,
    /// Only set together with `server_url`.
    pub lock_server_url: bool,
    pub disable_auto_update: bool,
    pub launcher_shortcut: Option<String>,
    pub disable_launcher: bool,
    pub launch_at_login: Option<bool>,
}

impl Policy {
    /// The server to use: a locked managed server, else the saved one, else
    /// the managed one (so a managed device skips onboarding).
    pub fn server(&self, saved: Option<String>) -> Option<String> {
        if self.lock_server_url {
            if let Some(managed) = &self.server_url {
                return Some(managed.clone());
            }
        }
        saved.or_else(|| self.server_url.clone())
    }

    /// The launcher shortcut to register, or `None` if the launcher is off.
    pub fn hotkey(&self, saved: String) -> Option<String> {
        if self.disable_launcher {
            return None;
        }
        Some(self.launcher_shortcut.clone().unwrap_or(saved))
    }

    pub fn hotkey_managed(&self) -> bool {
        self.disable_launcher || self.launcher_shortcut.is_some()
    }
}

fn as_bool(key: &str, value: RawValue) -> Option<bool> {
    let parsed = match &value {
        RawValue::Bool(b) => Some(*b),
        RawValue::Int(0) => Some(false),
        RawValue::Int(1) => Some(true),
        RawValue::Str(s) => match s.trim().to_ascii_lowercase().as_str() {
            "true" | "1" => Some(true),
            "false" | "0" => Some(false),
            _ => None,
        },
        RawValue::Int(_) => None,
    };
    if parsed.is_none() {
        log::warn!("managed setting {key} is not a boolean; ignored: {value:?}");
    }
    parsed
}

fn as_string(key: &str, value: RawValue) -> Option<String> {
    match value {
        RawValue::Str(s) => Some(s),
        other => {
            log::warn!("managed setting {key} is not a string; ignored: {other:?}");
            None
        }
    }
}

/// Builds the policy from a key lookup. Invalid values are logged and ignored.
pub fn parse(lookup: impl Fn(&str) -> Option<RawValue>) -> Policy {
    let flag = |key: &str| lookup(key).and_then(|v| as_bool(key, v));
    let server_url = lookup(SERVER_URL)
        .and_then(|v| as_string(SERVER_URL, v))
        .and_then(|raw| match normalize_server_url(&raw) {
            Ok(url) => Some(url),
            Err(e) => {
                log::warn!("managed setting {SERVER_URL} is invalid; ignored: {e}");
                None
            }
        });
    let mut lock_server_url = flag(LOCK_SERVER_URL).unwrap_or(false);
    if lock_server_url && server_url.is_none() {
        log::warn!("managed setting {LOCK_SERVER_URL} needs a valid {SERVER_URL}; ignored");
        lock_server_url = false;
    }
    let launcher_shortcut = lookup(LAUNCHER_SHORTCUT)
        .and_then(|v| as_string(LAUNCHER_SHORTCUT, v))
        .filter(|raw| {
            let valid = Shortcut::from_str(raw).is_ok();
            if !valid {
                log::warn!("managed setting {LAUNCHER_SHORTCUT} is invalid; ignored: {raw}");
            }
            valid
        });
    Policy {
        server_url,
        lock_server_url,
        disable_auto_update: flag(DISABLE_AUTO_UPDATE).unwrap_or(false),
        launcher_shortcut,
        disable_launcher: flag(DISABLE_LAUNCHER).unwrap_or(false),
        launch_at_login: flag(LAUNCH_AT_LOGIN),
    }
}

/// Parses the Linux policy file: one JSON object with the same keys.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
pub fn parse_json(raw: &str) -> Policy {
    let map = match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(serde_json::Value::Object(map)) => map,
        Ok(_) => {
            log::warn!("managed policy file is not a JSON object; ignored");
            return Policy::default();
        }
        Err(e) => {
            log::warn!("managed policy file is not valid JSON; ignored: {e}");
            return Policy::default();
        }
    };
    parse(|key| match map.get(key)? {
        serde_json::Value::String(s) => Some(RawValue::Str(s.clone())),
        serde_json::Value::Bool(b) => Some(RawValue::Bool(*b)),
        serde_json::Value::Number(n) => n.as_i64().map(RawValue::Int),
        other => {
            log::warn!("managed setting {key} has an unsupported type; ignored: {other}");
            None
        }
    })
}

#[cfg(target_os = "macos")]
fn read_macos(domain: &str, forced_only: bool) -> Policy {
    use objc2_core_foundation::{
        CFBoolean, CFNumber, CFPreferencesAppValueIsForced, CFPreferencesCopyAppValue, CFString,
    };
    let app_id = CFString::from_str(domain);
    parse(|key| {
        let cf_key = CFString::from_str(key);
        // Only a configuration profile forces a value; the user's own
        // defaults are not managed.
        if forced_only && !CFPreferencesAppValueIsForced(&cf_key, &app_id) {
            return None;
        }
        let value = CFPreferencesCopyAppValue(&cf_key, &app_id)?;
        if let Some(s) = value.downcast_ref::<CFString>() {
            Some(RawValue::Str(s.to_string()))
        } else if let Some(b) = value.downcast_ref::<CFBoolean>() {
            Some(RawValue::Bool(b.as_bool()))
        } else if let Some(n) = value.downcast_ref::<CFNumber>() {
            n.as_i64().map(RawValue::Int)
        } else {
            log::warn!("managed setting {key} has an unsupported type; ignored");
            None
        }
    })
}

#[cfg(windows)]
fn read_windows() -> Policy {
    use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
    use winreg::RegKey;
    const KEY: &str = r"SOFTWARE\Policies\Onyx\Desktop";
    // Machine policy wins over user policy.
    let keys: Vec<RegKey> = [HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER]
        .into_iter()
        .filter_map(|hive| RegKey::predef(hive).open_subkey(KEY).ok())
        .collect();
    parse(|name| {
        keys.iter().find_map(|key| {
            if let Ok(v) = key.get_value::<u32, _>(name) {
                Some(RawValue::Int(i64::from(v)))
            } else {
                key.get_value::<String, _>(name).ok().map(RawValue::Str)
            }
        })
    })
}

/// Reads the managed policy from the platform store.
pub fn read(app: &AppHandle) -> Policy {
    #[cfg(target_os = "macos")]
    {
        read_macos(&app.config().identifier, true)
    }
    #[cfg(windows)]
    {
        let _ = app;
        read_windows()
    }
    #[cfg(target_os = "linux")]
    {
        let _ = app;
        match std::fs::read_to_string("/etc/onyx-desktop/policy.json") {
            Ok(raw) => parse_json(&raw),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Policy::default(),
            Err(e) => {
                log::warn!("could not read the managed policy file: {e}");
                Policy::default()
            }
        }
    }
    #[cfg(not(any(target_os = "macos", windows, target_os = "linux")))]
    {
        let _ = app;
        Policy::default()
    }
}

/// Sets the login item to match a managed `LaunchAtLogin`.
pub fn apply_launch_at_login(app: &AppHandle, policy: &Policy) {
    let Some(wanted) = policy.launch_at_login else {
        return;
    };
    let autolaunch = app.autolaunch();
    if autolaunch.is_enabled().ok() == Some(wanted) {
        return;
    }
    let result = if wanted {
        autolaunch.enable()
    } else {
        autolaunch.disable()
    };
    if let Err(e) = result {
        log::warn!("could not apply managed {LAUNCH_AT_LOGIN}: {e}");
    }
}

/// Reads the policy again (when Preferences opens) and applies what changed.
/// The server and its lock keep their startup values for this run, so the
/// session never moves to another server under the open windows.
pub fn refresh(app: &AppHandle) {
    let state = app.state::<AppState>();
    let old = state.policy();
    let mut new = read(app);
    new.server_url = old.server_url.clone();
    new.lock_server_url = old.lock_server_url;
    if new == old {
        return;
    }
    let saved = state.config.get().hotkey();
    let (old_hotkey, new_hotkey) = (old.hotkey(saved.clone()), new.hotkey(saved));
    state.set_policy(new.clone());
    if old_hotkey != new_hotkey {
        if let Err(e) = crate::shortcut::replace(app, old_hotkey.as_deref(), new_hotkey.as_deref())
        {
            log::warn!("{e}");
        }
    }
    apply_launch_at_login(app, &new);
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    fn policy(values: &[(&str, RawValue)]) -> Policy {
        let map: HashMap<String, RawValue> = values
            .iter()
            .map(|(k, v)| (k.to_string(), v.clone()))
            .collect();
        parse(|key| map.get(key).cloned())
    }

    fn s(value: &str) -> RawValue {
        RawValue::Str(value.to_string())
    }

    #[test]
    fn absent_keys_give_the_default() {
        assert_eq!(policy(&[]), Policy::default());
        let p = Policy::default();
        assert_eq!(
            p.server(Some("https://a.example".into())).as_deref(),
            Some("https://a.example")
        );
        assert_eq!(p.server(None), None);
        assert_eq!(p.hotkey("Alt+Space".into()).as_deref(), Some("Alt+Space"));
        assert!(!p.hotkey_managed());
    }

    #[test]
    fn parses_every_key() {
        let p = policy(&[
            (SERVER_URL, s("https://onyx.example.com/app/")),
            (LOCK_SERVER_URL, RawValue::Bool(true)),
            (DISABLE_AUTO_UPDATE, RawValue::Int(1)),
            (LAUNCHER_SHORTCUT, s("CommandOrControl+Alt+O")),
            (DISABLE_LAUNCHER, s("false")),
            (LAUNCH_AT_LOGIN, RawValue::Int(0)),
        ]);
        assert_eq!(
            p,
            Policy {
                server_url: Some("https://onyx.example.com".into()),
                lock_server_url: true,
                disable_auto_update: true,
                launcher_shortcut: Some("CommandOrControl+Alt+O".into()),
                disable_launcher: false,
                launch_at_login: Some(false),
            }
        );
    }

    #[test]
    fn managed_server_skips_onboarding_but_a_saved_one_wins_unless_locked() {
        let unlocked = policy(&[(SERVER_URL, s("https://onyx.example.com"))]);
        assert_eq!(
            unlocked.server(None).as_deref(),
            Some("https://onyx.example.com")
        );
        assert_eq!(
            unlocked
                .server(Some("https://mine.example".into()))
                .as_deref(),
            Some("https://mine.example")
        );
        let locked = policy(&[
            (SERVER_URL, s("https://onyx.example.com")),
            (LOCK_SERVER_URL, RawValue::Bool(true)),
        ]);
        assert_eq!(
            locked
                .server(Some("https://mine.example".into()))
                .as_deref(),
            Some("https://onyx.example.com")
        );
    }

    #[test]
    fn managed_shortcut_wins_and_disable_turns_the_launcher_off() {
        let p = policy(&[(LAUNCHER_SHORTCUT, s("Alt+Space"))]);
        assert_eq!(p.hotkey("Control+K".into()).as_deref(), Some("Alt+Space"));
        assert!(p.hotkey_managed());
        let off = policy(&[
            (LAUNCHER_SHORTCUT, s("Alt+Space")),
            (DISABLE_LAUNCHER, RawValue::Bool(true)),
        ]);
        assert_eq!(off.hotkey("Control+K".into()), None);
        assert!(off.hotkey_managed());
    }

    #[test]
    fn invalid_values_are_ignored() {
        let p = policy(&[
            (SERVER_URL, s("ftp://onyx.example.com")),
            (LOCK_SERVER_URL, RawValue::Bool(true)),
            (DISABLE_AUTO_UPDATE, s("maybe")),
            (LAUNCHER_SHORTCUT, s("Nope+Nope")),
            (DISABLE_LAUNCHER, RawValue::Int(7)),
            (LAUNCH_AT_LOGIN, s("yes please")),
        ]);
        assert_eq!(p, Policy::default());
        // Plain http is only for a server on this computer.
        assert_eq!(
            policy(&[(SERVER_URL, s("http://onyx.example.com"))]).server_url,
            None
        );
        assert_eq!(
            policy(&[(SERVER_URL, RawValue::Bool(true))]).server_url,
            None
        );
    }

    #[test]
    fn lock_without_a_server_is_ignored() {
        let p = policy(&[(LOCK_SERVER_URL, RawValue::Bool(true))]);
        assert!(!p.lock_server_url);
    }

    #[test]
    fn parses_the_linux_policy_file() {
        let p = parse_json(
            r#"{"ServerURL": "https://onyx.example.com", "LockServerURL": true,
                "LaunchAtLogin": true, "DisableLauncher": 1, "Unknown": [1]}"#,
        );
        assert_eq!(p.server_url.as_deref(), Some("https://onyx.example.com"));
        assert!(p.lock_server_url);
        assert_eq!(p.launch_at_login, Some(true));
        assert!(p.disable_launcher);
        assert_eq!(parse_json("not json"), Policy::default());
        assert_eq!(parse_json("[]"), Policy::default());
    }

    /// Reads real preferences through CFPreferences, from a scratch domain
    /// (never the app's own or a managed one).
    #[cfg(target_os = "macos")]
    #[test]
    fn reads_macos_preferences() {
        use std::process::Command;
        let domain = format!("app.onyx.desktop.v2.policy-test-{}", std::process::id());
        let write = |args: &[&str]| {
            let status = Command::new("defaults")
                .arg("write")
                .arg(&domain)
                .args(args)
                .status()
                .expect("defaults runs");
            assert!(status.success());
        };
        write(&[SERVER_URL, "-string", "https://onyx.example.com"]);
        write(&[LOCK_SERVER_URL, "-bool", "true"]);
        write(&[LAUNCH_AT_LOGIN, "-int", "1"]);
        let read = read_macos(&domain, false);
        // A value the user wrote is not forced, so it is not managed.
        let forced = read_macos(&domain, true);
        let _ = Command::new("defaults").args(["delete", &domain]).status();
        if let Some(home) = std::env::var_os("HOME") {
            let plist = std::path::Path::new(&home)
                .join("Library/Preferences")
                .join(format!("{domain}.plist"));
            let _ = std::fs::remove_file(plist);
        }
        assert_eq!(read.server_url.as_deref(), Some("https://onyx.example.com"));
        assert!(read.lock_server_url);
        assert_eq!(read.launch_at_login, Some(true));
        assert_eq!(forced, Policy::default());
    }
}
