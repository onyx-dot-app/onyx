//! Where the session token lives, one entry per server origin.
//!
//! Release builds use the macOS keychain. macOS ties an item to the app's code
//! signature; a signed release keeps it across updates, so the user approves
//! once. An unsigned dev build gets a new signature on every rebuild, and macOS
//! would ask for the user's password each time, so debug builds keep the token
//! in a file only the user can read (mode 600) in the app's support folder.
//! Windows and Linux always use the OS store (Credential Manager, Secret
//! Service), which does not depend on the code signature.

#[cfg(not(all(debug_assertions, target_os = "macos")))]
mod backend {
    use keyring::Entry;

    const SERVICE: &str = "app.onyx.desktop";
    #[cfg(target_os = "macos")]
    const STORE: &str = "the macOS keychain";
    #[cfg(target_os = "windows")]
    const STORE: &str = "Windows Credential Manager";
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    const STORE: &str = "the Secret Service";

    /// The message for a failed store call. On Linux it also says what the
    /// user can do (see `secret_service`).
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    fn failed(action: &str, e: &keyring::Error) -> String {
        format!(
            "{action}. {} (Details: {e}.)",
            super::secret_service::advice(e)
        )
    }
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    fn failed(action: &str, e: &keyring::Error) -> String {
        format!("{action} ({e}).")
    }

    fn entry(server: &str) -> Result<Entry, String> {
        Entry::new(SERVICE, server).map_err(|e| failed(&format!("Could not open {STORE}"), &e))
    }

    /// `Ok(None)` when no session is stored, `Err` when the store could not
    /// be read (for example, a locked keyring).
    pub fn load(server: &str) -> Result<Option<String>, String> {
        match entry(server)?.get_password() {
            Ok(token) => Ok(Some(token)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(e) => Err(failed(
                &format!("Could not read the session from {STORE}"),
                &e,
            )),
        }
    }

    pub fn store(server: &str, token: &str) -> Result<(), String> {
        entry(server)?
            .set_password(token)
            .map_err(|e| failed(&format!("Could not save the session to {STORE}"), &e))
    }

    pub fn clear(server: &str) -> Result<(), String> {
        match entry(server)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(failed(
                &format!("Could not remove the session from {STORE}"),
                &e,
            )),
        }
    }
}

#[cfg(all(debug_assertions, target_os = "macos"))]
mod backend {
    use std::collections::BTreeMap;
    use std::fs;
    use std::path::PathBuf;

    fn path() -> Option<PathBuf> {
        let home = std::env::var_os("HOME")?;
        Some(
            PathBuf::from(home)
                .join("Library/Application Support/app.onyx.desktop")
                .join("dev-session-tokens.json"),
        )
    }

    fn read() -> BTreeMap<String, String> {
        path()
            .and_then(|p| fs::read_to_string(p).ok())
            .and_then(|raw| serde_json::from_str(&raw).ok())
            .unwrap_or_default()
    }

    /// The file is created with mode 600, and an existing file is made private
    /// before any token is written, so no other user can read it at any point.
    fn write(tokens: &BTreeMap<String, String>) -> Result<(), String> {
        use std::io::Write;
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

        let path = path().ok_or("HOME is not set")?;
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir).map_err(|e| e.to_string())?;
            fs::set_permissions(dir, fs::Permissions::from_mode(0o700))
                .map_err(|e| e.to_string())?;
        }
        let raw = serde_json::to_string(tokens).map_err(|e| e.to_string())?;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(&path)
            .map_err(|e| format!("Could not save the session: {e}"))?;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())?;
        file.set_len(0).map_err(|e| e.to_string())?;
        file.write_all(raw.as_bytes())
            .map_err(|e| format!("Could not save the session: {e}"))
    }

    pub fn load(server: &str) -> Result<Option<String>, String> {
        Ok(read().get(server).cloned())
    }

    pub fn store(server: &str, token: &str) -> Result<(), String> {
        let mut tokens = read();
        tokens.insert(server.to_string(), token.to_string());
        write(&tokens)
    }

    pub fn clear(server: &str) -> Result<(), String> {
        let mut tokens = read();
        if tokens.remove(server).is_some() {
            write(&tokens)?;
        }
        Ok(())
    }
}

pub use backend::{clear, load, store};

/// Whether a failed read is kept for the rest of the run. Each read of a
/// locked Secret Service asks the user to unlock it; one prompt is enough.
pub const KEEP_READ_FAILURE: bool = cfg!(not(any(target_os = "macos", target_os = "windows")));

/// What a Secret Service failure means for the user.
#[cfg(any(test, not(any(target_os = "macos", target_os = "windows"))))]
mod secret_service {
    #[derive(Debug, PartialEq)]
    pub enum Problem {
        Locked,
        NoDefaultKeyring,
        NoProvider,
        NoSessionBus,
        Other,
    }

    /// keyring boxes the D-Bus errors with no type to match on, so the
    /// error text tells them apart.
    pub fn classify(e: &keyring::Error) -> Problem {
        match e {
            keyring::Error::NoStorageAccess(inner) => {
                if inner.to_string().contains("no result found") {
                    Problem::NoDefaultKeyring
                } else {
                    Problem::Locked
                }
            }
            keyring::Error::PlatformFailure(inner) => {
                let text = inner.to_string();
                let no_bus = [
                    "DBUS_SESSION_BUS_ADDRESS",
                    "autolaunch",
                    "connect to socket",
                    "No DBus session",
                ];
                if text.contains("org.freedesktop.secrets") {
                    Problem::NoProvider
                } else if no_bus.iter().any(|needle| text.contains(needle)) {
                    Problem::NoSessionBus
                } else {
                    Problem::Other
                }
            }
            _ => Problem::Other,
        }
    }

    pub fn advice(e: &keyring::Error) -> &'static str {
        match classify(e) {
            Problem::Locked => "Your keyring is locked. Unlock it when Onyx asks, then try again.",
            Problem::NoDefaultKeyring => {
                "Your keyring has no default collection. In Passwords and Keys (Seahorse) or \
                 KWallet Manager, create a keyring and set it as the default, then try again."
            }
            Problem::NoProvider => {
                "No Secret Service provider runs in this session. Onyx keeps your session in a \
                 keyring: install and start GNOME Keyring or KWallet, then try again."
            }
            Problem::NoSessionBus => {
                "Onyx cannot connect to the D-Bus session bus, so it cannot reach your keyring. \
                 Start Onyx from a desktop session that sets DBUS_SESSION_BUS_ADDRESS, then try \
                 again."
            }
            Problem::Other => {
                "Onyx keeps your session in the Secret Service. Start GNOME Keyring or KWallet \
                 (or another Secret Service provider) and unlock it, then try again."
            }
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        fn wrapped(text: &str) -> Box<dyn std::error::Error + Send + Sync> {
            text.into()
        }

        #[test]
        fn each_secret_service_failure_gets_its_own_advice() {
            let no_access = |text| keyring::Error::NoStorageAccess(wrapped(text));
            let failure = |text| keyring::Error::PlatformFailure(wrapped(text));
            let cases = [
                (
                    no_access("Secret Service: unlock prompt was dismissed"),
                    Problem::Locked,
                ),
                (no_access("Secret Service: object locked"), Problem::Locked),
                (
                    no_access("Secret Service: no result found"),
                    Problem::NoDefaultKeyring,
                ),
                (
                    failure(
                        "DBus error: The name org.freedesktop.secrets was not provided by any \
                         .service files",
                    ),
                    Problem::NoProvider,
                ),
                (
                    failure("DBus error: Unable to autolaunch a dbus-daemon without a $DISPLAY"),
                    Problem::NoSessionBus,
                ),
                (
                    failure("DBus error: Failed to connect to socket /run/user/1000/bus"),
                    Problem::NoSessionBus,
                ),
                (failure("DBus error: something else"), Problem::Other),
            ];
            for (error, problem) in cases {
                assert_eq!(classify(&error), problem, "{error}");
            }
            let mut advice: Vec<&str> = [
                no_access("Secret Service: object locked"),
                no_access("Secret Service: no result found"),
                failure("org.freedesktop.secrets was not provided"),
                failure("Unable to autolaunch"),
                failure("something else"),
            ]
            .iter()
            .map(advice)
            .collect();
            advice.dedup();
            assert_eq!(advice.len(), 5, "one message for each problem");
        }
    }
}
