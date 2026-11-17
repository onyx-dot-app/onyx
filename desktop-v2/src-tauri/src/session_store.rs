//! Where the session token lives, one entry per server origin.
//!
//! Release builds use the macOS keychain. macOS ties an item to the app's code
//! signature; a signed release keeps it across updates, so the user approves
//! once. An unsigned dev build gets a new signature on every rebuild, and macOS
//! would ask for the user's password each time, so debug builds keep the token
//! in a file only the user can read (mode 600) in the app's support folder.

#[cfg(not(debug_assertions))]
mod backend {
    use keyring::Entry;

    const SERVICE: &str = "app.onyx.desktop.v2";

    fn entry(server: &str) -> Result<Entry, String> {
        Entry::new(SERVICE, server).map_err(|e| format!("Keychain unavailable: {e}"))
    }

    pub fn load(server: &str) -> Option<String> {
        entry(server).ok()?.get_password().ok()
    }

    pub fn store(server: &str, token: &str) -> Result<(), String> {
        entry(server)?
            .set_password(token)
            .map_err(|e| format!("Could not save the session to the keychain: {e}"))
    }

    pub fn clear(server: &str) -> Result<(), String> {
        match entry(server)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(format!("Could not remove the keychain entry: {e}")),
        }
    }
}

#[cfg(debug_assertions)]
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

    fn write(tokens: &BTreeMap<String, String>) -> Result<(), String> {
        let path = path().ok_or("HOME is not set")?;
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let raw = serde_json::to_string(tokens).map_err(|e| e.to_string())?;
        fs::write(&path, raw).map_err(|e| format!("Could not save the session: {e}"))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o600))
                .map_err(|e| e.to_string())?;
        }
        Ok(())
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
