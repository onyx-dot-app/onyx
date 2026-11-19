//! Managed configuration that IT pushes with an MDM (Kandji, Jamf, Intune) or
//! Group Policy. A managed value wins over the user's `config.json` value.
//!
//! - macOS: forced managed preferences for the app's bundle id.
//! - Windows: `HKLM\SOFTWARE\Policies\Onyx\Desktop`, then the same key in HKCU.
//! - Linux: `/etc/onyx-desktop/policy.json`.

use std::cell::Cell;
use std::str::FromStr;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::Shortcut;

use crate::api::normalize_managed_server_url;
use crate::state::AppState;

const SERVER_URL: &str = "ServerURL";
const LOCK_SERVER_URL: &str = "LockServerURL";
const DISABLE_AUTO_UPDATE: &str = "DisableAutoUpdate";
const LAUNCHER_SHORTCUT: &str = "LauncherShortcut";
const DISABLE_LAUNCHER: &str = "DisableLauncher";
const LAUNCH_AT_LOGIN: &str = "LaunchAtLogin";
const DISABLE_NOTIFICATIONS: &str = "DisableNotifications";

/// How often the app reads the policy again while it runs.
const REFRESH_INTERVAL: Duration = Duration::from_secs(5 * 60);

/// A value as the platform store holds it.
#[derive(Debug, Clone, PartialEq)]
pub enum RawValue {
    Str(String),
    Bool(bool),
    Int(i64),
    /// A type the policy does not use (a float, a list); always invalid.
    Other(String),
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Policy {
    pub server_url: Option<String>,
    /// Without `server_url`, the saved server stays and cannot change.
    pub lock_server_url: bool,
    pub disable_auto_update: bool,
    pub launcher_shortcut: Option<String>,
    pub disable_launcher: bool,
    pub launch_at_login: Option<bool>,
    pub disable_notifications: bool,
    /// A policy exists but holds a value that is not valid.
    pub invalid: bool,
}

impl Policy {
    /// A policy source that exists but cannot be read: the server and
    /// updates stay locked, so a broken policy is never more permissive.
    pub fn unreadable() -> Self {
        Self {
            lock_server_url: true,
            disable_auto_update: true,
            invalid: true,
            ..Self::default()
        }
    }

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

fn as_bool(value: &RawValue) -> Option<bool> {
    match value {
        RawValue::Bool(b) => Some(*b),
        RawValue::Int(0) => Some(false),
        RawValue::Int(1) => Some(true),
        RawValue::Str(s) => match s.trim().to_ascii_lowercase().as_str() {
            "true" | "1" | "yes" => Some(true),
            "false" | "0" | "no" => Some(false),
            _ => None,
        },
        RawValue::Int(_) | RawValue::Other(_) => None,
    }
}

/// Builds the policy from a key lookup. An invalid value is logged and marks
/// the policy invalid. A lock or `Disable*` key with an invalid value takes
/// its restrictive value; any other invalid key is ignored.
pub fn parse(lookup: impl Fn(&str) -> Option<RawValue>) -> Policy {
    let invalid = Cell::new(false);
    let reject = |key: &str, value: &RawValue, why: &str| {
        log::error!("managed setting {key} is not valid ({why}): {value:?}");
        invalid.set(true);
    };
    let flag = |key: &str| -> Option<bool> {
        let value = lookup(key)?;
        let parsed = as_bool(&value);
        if parsed.is_none() {
            reject(key, &value, "not a boolean; ignored");
        }
        parsed
    };
    let restrictive = |key: &str| -> bool {
        match lookup(key) {
            None => false,
            Some(value) => as_bool(&value).unwrap_or_else(|| {
                reject(key, &value, "not a boolean; treated as true");
                true
            }),
        }
    };
    let string = |key: &str| -> Option<String> {
        match lookup(key)? {
            RawValue::Str(s) => Some(s),
            other => {
                reject(key, &other, "not a string; ignored");
                None
            }
        }
    };
    let server_url = string(SERVER_URL).and_then(|raw| match normalize_managed_server_url(&raw) {
        Ok(url) => Some(url),
        Err(e) => {
            reject(SERVER_URL, &RawValue::Str(raw), &e);
            None
        }
    });
    let lock_server_url = restrictive(LOCK_SERVER_URL);
    if lock_server_url && server_url.is_none() {
        log::error!(
            "managed setting {LOCK_SERVER_URL} needs a valid {SERVER_URL}; the saved server stays and cannot change"
        );
        invalid.set(true);
    }
    let launcher_shortcut = string(LAUNCHER_SHORTCUT).filter(|raw| {
        let valid = Shortcut::from_str(raw).is_ok();
        if !valid {
            reject(
                LAUNCHER_SHORTCUT,
                &RawValue::Str(raw.clone()),
                "not a shortcut; ignored",
            );
        }
        valid
    });
    let policy = Policy {
        server_url,
        lock_server_url,
        disable_auto_update: restrictive(DISABLE_AUTO_UPDATE),
        launcher_shortcut,
        disable_launcher: restrictive(DISABLE_LAUNCHER),
        launch_at_login: flag(LAUNCH_AT_LOGIN),
        disable_notifications: restrictive(DISABLE_NOTIFICATIONS),
        invalid: false,
    };
    Policy {
        invalid: invalid.get(),
        ..policy
    }
}

/// Parses the Linux policy file: one JSON object with the same keys.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
pub fn parse_json(raw: &str) -> Policy {
    // Many Windows tools and editors write a byte order mark.
    let raw = raw.strip_prefix('\u{feff}').unwrap_or(raw);
    let map = match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(serde_json::Value::Object(map)) => map,
        Ok(_) => {
            log::error!("managed policy file is not a JSON object");
            return Policy::unreadable();
        }
        Err(e) => {
            log::error!("managed policy file is not valid JSON: {e}");
            return Policy::unreadable();
        }
    };
    parse(|key| {
        Some(match map.get(key)? {
            serde_json::Value::String(s) => RawValue::Str(s.clone()),
            serde_json::Value::Bool(b) => RawValue::Bool(*b),
            serde_json::Value::Number(n) => match n.as_i64() {
                Some(i) => RawValue::Int(i),
                None => RawValue::Other(n.to_string()),
            },
            other => RawValue::Other(other.to_string()),
        })
    })
}

#[cfg(target_os = "macos")]
fn read_macos(domain: &str, forced_only: bool) -> Policy {
    use objc2_core_foundation::{
        CFBoolean, CFNumber, CFPreferencesAppSynchronize, CFPreferencesAppValueIsForced,
        CFPreferencesCopyAppValue, CFString,
    };
    let app_id = CFString::from_str(domain);
    // CFPreferences caches values; this reads a changed profile.
    CFPreferencesAppSynchronize(&app_id);
    parse(|key| {
        let cf_key = CFString::from_str(key);
        // Only a configuration profile forces a value; the user's own
        // defaults are not managed.
        if forced_only && !CFPreferencesAppValueIsForced(&cf_key, &app_id) {
            return None;
        }
        let value = CFPreferencesCopyAppValue(&cf_key, &app_id)?;
        Some(if let Some(s) = value.downcast_ref::<CFString>() {
            RawValue::Str(s.to_string())
        } else if let Some(b) = value.downcast_ref::<CFBoolean>() {
            RawValue::Bool(b.as_bool())
        } else if let Some(n) = value.downcast_ref::<CFNumber>() {
            match n.as_i64() {
                Some(i) if !n.is_float_type() => RawValue::Int(i),
                _ => RawValue::Other(format!("number {:?}", n.as_f64())),
            }
        } else {
            RawValue::Other("unsupported type".into())
        })
    })
}

/// One store's read of a key: `Ok(None)` when the key or value is absent.
type StoreRead = Result<Option<RawValue>, String>;

/// The value from the first store that has it. A read error stops the search:
/// a lower store must not stand in for a value that may exist, so the error
/// becomes a value that is not valid, and `parse` fails closed on it.
#[cfg_attr(not(windows), allow(dead_code))]
fn first_value(reads: impl IntoIterator<Item = StoreRead>) -> Option<RawValue> {
    for read in reads {
        match read {
            Ok(None) => continue,
            Ok(Some(value)) => return Some(value),
            Err(e) => return Some(RawValue::Other(format!("could not read: {e}"))),
        }
    }
    None
}

#[cfg(windows)]
fn read_windows() -> Policy {
    use std::io::ErrorKind;
    use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
    use winreg::types::FromRegValue;
    use winreg::RegKey;
    const KEY: &str = r"SOFTWARE\Policies\Onyx\Desktop";
    // Machine policy wins over user policy.
    let keys: Vec<Result<Option<RegKey>, String>> = [HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER]
        .into_iter()
        .map(|hive| match RegKey::predef(hive).open_subkey(KEY) {
            Ok(key) => Ok(Some(key)),
            Err(e) if e.kind() == ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.to_string()),
        })
        .collect();
    parse(|name| {
        first_value(keys.iter().map(|key| -> StoreRead {
            let Some(key) = key.as_ref().map_err(Clone::clone)?.as_ref() else {
                return Ok(None);
            };
            let raw = match key.get_raw_value(name) {
                Ok(raw) => raw,
                Err(e) if e.kind() == ErrorKind::NotFound => return Ok(None),
                Err(e) => return Err(e.to_string()),
            };
            Ok(Some(if let Ok(v) = u32::from_reg_value(&raw) {
                RawValue::Int(i64::from(v))
            } else if let Ok(v) = String::from_reg_value(&raw) {
                RawValue::Str(v)
            } else {
                RawValue::Other(format!("{:?}", raw.vtype))
            }))
        }))
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
                log::error!("could not read the managed policy file: {e}");
                Policy::unreadable()
            }
        }
    }
    #[cfg(not(any(target_os = "macos", windows, target_os = "linux")))]
    {
        let _ = app;
        Policy::default()
    }
}

/// Sets the login item to match a managed `LaunchAtLogin`. Best effort: the
/// user can turn the item off outside the app until this runs again.
pub fn apply_launch_at_login(app: &AppHandle, policy: &Policy) {
    let Some(wanted) = policy.launch_at_login else {
        return;
    };
    if crate::login_item::is_enabled(app).ok() == Some(wanted) {
        return;
    }
    if let Err(e) = crate::login_item::set(app, wanted) {
        log::warn!("could not apply managed {LAUNCH_AT_LOGIN}: {e}");
    }
}

/// Registers the launcher shortcut that config and policy want. A shortcut
/// that was not available is tried again on the next call. Main thread only.
pub fn sync_hotkey(app: &AppHandle) {
    let wanted = app.state::<AppState>().hotkey();
    if let Err(e) = crate::shortcut::apply(app, wanted.as_deref()) {
        log::warn!("{e}");
    }
}

static REFRESHING: Mutex<()> = Mutex::new(());

/// Reads the policy again and applies what changed. Runs on any thread.
/// The server keeps its startup value for this run, so the session never
/// moves to another server under the open windows.
pub fn refresh(app: &AppHandle) {
    let _serial = REFRESHING.lock().unwrap_or_else(|p| p.into_inner());
    let state = app.state::<AppState>();
    let old = state.policy();
    let mut new = read(app);
    new.server_url = old.server_url.clone();
    // A lock can turn on (for example when the policy becomes unreadable)
    // but never off. When it turns on, it locks the server in use now.
    if new.lock_server_url && !old.lock_server_url {
        new.server_url = old.server(state.config.get().server_url);
    }
    new.lock_server_url = old.lock_server_url || new.lock_server_url;
    // A policy that cannot be read keeps the restrictions it had.
    if new.invalid {
        new.disable_auto_update |= old.disable_auto_update;
        new.disable_launcher |= old.disable_launcher;
        new.disable_notifications |= old.disable_notifications;
    }
    if new != old {
        state.set_policy(new.clone());
        if new.disable_auto_update {
            crate::updater::discard_ready();
        }
        if new.disable_launcher && !old.disable_launcher {
            crate::windows::hide_launcher(app);
        }
        if new.launch_at_login != old.launch_at_login {
            apply_launch_at_login(app, &new);
        }
    }
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || sync_hotkey(&handle));
}

/// Reads the policy again every few minutes, so a change applies while the
/// app runs.
pub fn spawn_refresh(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(REFRESH_INTERVAL).await;
            let handle = app.clone();
            let _ = tauri::async_runtime::spawn_blocking(move || refresh(&handle)).await;
        }
    });
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
            (DISABLE_NOTIFICATIONS, s("Yes")),
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
                disable_notifications: true,
                invalid: false,
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
    fn a_managed_server_may_use_http() {
        let p = policy(&[
            (SERVER_URL, s("http://onyx.corp.internal")),
            (LOCK_SERVER_URL, RawValue::Bool(true)),
        ]);
        assert_eq!(p.server_url.as_deref(), Some("http://onyx.corp.internal"));
        assert!(p.lock_server_url);
        assert!(!p.invalid);
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
    fn invalid_values_fail_closed() {
        let p = policy(&[
            (SERVER_URL, s("ftp://onyx.example.com")),
            (LOCK_SERVER_URL, RawValue::Int(2)),
            (DISABLE_AUTO_UPDATE, s("maybe")),
            (LAUNCHER_SHORTCUT, s("Nope+Nope")),
            (DISABLE_LAUNCHER, RawValue::Int(7)),
            (LAUNCH_AT_LOGIN, s("yes please")),
            (DISABLE_NOTIFICATIONS, RawValue::Other("1.0".into())),
        ]);
        assert_eq!(
            p,
            Policy {
                server_url: None,
                lock_server_url: true,
                disable_auto_update: true,
                launcher_shortcut: None,
                disable_launcher: true,
                launch_at_login: None,
                disable_notifications: true,
                invalid: true,
            }
        );
        let wrong_type = policy(&[(SERVER_URL, RawValue::Bool(true))]);
        assert_eq!(wrong_type.server_url, None);
        assert!(wrong_type.invalid);
    }

    #[test]
    fn lock_without_a_server_keeps_the_saved_one() {
        let p = policy(&[(LOCK_SERVER_URL, RawValue::Bool(true))]);
        assert!(p.lock_server_url);
        assert!(p.invalid);
        assert_eq!(
            p.server(Some("https://mine.example".into())).as_deref(),
            Some("https://mine.example")
        );
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
        assert!(!p.invalid);
    }

    #[test]
    fn a_byte_order_mark_is_allowed() {
        let p = parse_json("\u{feff}{\"DisableAutoUpdate\": true}");
        assert!(p.disable_auto_update);
        assert!(!p.invalid);
    }

    #[test]
    fn a_broken_policy_file_fails_closed() {
        for raw in [
            "not json",
            "[]",
            r#"{"ServerURL": "https://onyx.example.com", "LockServerURL": true,}"#,
        ] {
            assert_eq!(parse_json(raw), Policy::unreadable(), "{raw}");
        }
        let float = parse_json(r#"{"DisableAutoUpdate": 1.0}"#);
        assert!(float.disable_auto_update);
        assert!(float.invalid);
    }

    #[test]
    fn a_read_error_does_not_fall_through_to_a_lower_store() {
        let user = || Ok(Some(RawValue::Bool(false)));
        let denied = || Err("access denied".to_string());
        assert_eq!(first_value([Ok(None), user()]), Some(RawValue::Bool(false)));
        assert_eq!(first_value([Ok(None), Ok(None)]), None);
        assert!(matches!(
            first_value([denied(), user()]),
            Some(RawValue::Other(_))
        ));
        // A key that cannot be read takes its restrictive value.
        let p = parse(|key| match key {
            LOCK_SERVER_URL | DISABLE_LAUNCHER | LAUNCH_AT_LOGIN => first_value([denied(), user()]),
            _ => None,
        });
        assert!(p.lock_server_url);
        assert!(p.disable_launcher);
        assert_eq!(p.launch_at_login, None);
        assert!(p.invalid);
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
