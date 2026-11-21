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

    const SERVICE: &str = "app.onyx.desktop.v2";
    #[cfg(target_os = "macos")]
    const STORE: &str = "the macOS keychain";
    #[cfg(target_os = "windows")]
    const STORE: &str = "Windows Credential Manager";
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    const STORE: &str = "the Secret Service";

    /// What the user can do when the store fails. On Linux the usual cause is
    /// that no Secret Service runs (minimal desktops, VDI, SSH sessions).
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    const HINT: &str = " Onyx keeps your session in the Secret Service. Start GNOME Keyring or \
                        KWallet (or another Secret Service provider) and unlock it, then sign in \
                        again.";
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    const HINT: &str = "";

    fn entry(server: &str) -> Result<Entry, String> {
        Entry::new(SERVICE, server).map_err(|e| format!("Could not open {STORE} ({e}).{HINT}"))
    }

    pub fn load(server: &str) -> Option<String> {
        entry(server).ok()?.get_password().ok()
    }

    pub fn store(server: &str, token: &str) -> Result<(), String> {
        entry(server)?
            .set_password(token)
            .map_err(|e| format!("Could not save the session to {STORE} ({e}).{HINT}"))
    }

    pub fn clear(server: &str) -> Result<(), String> {
        match entry(server)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(format!(
                "Could not remove the session from {STORE} ({e}).{HINT}"
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
                .join("Library/Application Support/app.onyx.desktop.v2")
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

    pub fn load(server: &str) -> Option<String> {
        read().get(server).cloned()
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
