//! Launch at login, for the current user only.
//!
//! - macOS: a LaunchAgent from tauri-plugin-autostart.
//! - Windows: a quoted command in `HKCU\...\Run`. The plugin writes `HKLM`
//!   when the app runs elevated, and does not quote the path.
//! - Linux: an XDG autostart entry with a quoted `Exec=`.

#[cfg(not(any(windows, target_os = "linux")))]
use tauri::AppHandle;

#[cfg(target_os = "macos")]
pub fn is_enabled(app: &AppHandle) -> Result<bool, String> {
    use tauri_plugin_autostart::ManagerExt;
    app.autolaunch().is_enabled().map_err(|e| e.to_string())
}

#[cfg(target_os = "macos")]
pub fn set(app: &AppHandle, enabled: bool) -> Result<(), String> {
    use tauri_plugin_autostart::ManagerExt;
    let autolaunch = app.autolaunch();
    let result = if enabled {
        autolaunch.enable()
    } else {
        autolaunch.disable()
    };
    result.map_err(|e| e.to_string())
}

#[cfg(windows)]
mod platform {
    use tauri::AppHandle;
    use winreg::enums::{RegType, HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE};
    use winreg::{RegKey, RegValue};

    const RUN: &str = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run";
    /// Where Task Manager records that the user turned a startup app off.
    const APPROVED: &str =
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run";
    const APPROVED_ENABLED: [u8; 12] = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];

    fn name(app: &AppHandle) -> String {
        app.package_info().name.clone()
    }

    fn not_found(e: &std::io::Error) -> bool {
        e.kind() == std::io::ErrorKind::NotFound
    }

    pub fn is_enabled(app: &AppHandle) -> Result<bool, String> {
        let hkcu = RegKey::predef(HKEY_CURRENT_USER);
        let name = name(app);
        match hkcu
            .open_subkey_with_flags(RUN, KEY_READ)
            .and_then(|key| key.get_value::<String, _>(&name))
        {
            Ok(_) => {}
            Err(e) if not_found(&e) => return Ok(false),
            Err(e) => return Err(e.to_string()),
        }
        // Task Manager keeps the Run value and stores the time it was turned
        // off in the last 8 bytes; all zeros means on.
        match hkcu
            .open_subkey_with_flags(APPROVED, KEY_READ)
            .and_then(|key| key.get_raw_value(&name))
        {
            Ok(value) => {
                Ok(value.bytes.len() < 8 || value.bytes.iter().rev().take(8).all(|b| *b == 0))
            }
            Err(e) if not_found(&e) => Ok(true),
            Err(e) => Err(e.to_string()),
        }
    }

    pub fn set(app: &AppHandle, enabled: bool) -> Result<(), String> {
        let hkcu = RegKey::predef(HKEY_CURRENT_USER);
        let name = name(app);
        if !enabled {
            return match hkcu
                .open_subkey_with_flags(RUN, KEY_SET_VALUE)
                .and_then(|key| key.delete_value(&name))
            {
                Err(e) if !not_found(&e) => Err(e.to_string()),
                _ => Ok(()),
            };
        }
        let exe = std::env::current_exe().map_err(|e| e.to_string())?;
        let (run, _) = hkcu.create_subkey(RUN).map_err(|e| e.to_string())?;
        run.set_value(&name, &super::windows_command(&exe.to_string_lossy()))
            .map_err(|e| e.to_string())?;
        match hkcu.open_subkey_with_flags(APPROVED, KEY_SET_VALUE) {
            Ok(key) => key
                .set_raw_value(
                    &name,
                    &RegValue {
                        bytes: APPROVED_ENABLED.to_vec().into(),
                        vtype: RegType::REG_BINARY,
                    },
                )
                .map_err(|e| e.to_string()),
            Err(e) if not_found(&e) => Ok(()),
            Err(e) => Err(e.to_string()),
        }
    }
}

#[cfg(target_os = "linux")]
mod platform {
    use std::path::PathBuf;

    use tauri::{AppHandle, Manager};

    fn entry(app: &AppHandle) -> Result<PathBuf, String> {
        let dir = app.path().config_dir().map_err(|e| e.to_string())?;
        Ok(dir
            .join("autostart")
            .join(format!("{}.desktop", app.config().identifier)))
    }

    pub fn is_enabled(app: &AppHandle) -> Result<bool, String> {
        match std::fs::read_to_string(entry(app)?) {
            Ok(body) => Ok(super::desktop_entry_enabled(&body)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(e) => Err(e.to_string()),
        }
    }

    pub fn set(app: &AppHandle, enabled: bool) -> Result<(), String> {
        let path = entry(app)?;
        if !enabled {
            return match std::fs::remove_file(&path) {
                Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.to_string()),
                _ => Ok(()),
            };
        }
        let exe = match app.env().appimage {
            Some(appimage) => PathBuf::from(appimage),
            None => std::env::current_exe().map_err(|e| e.to_string())?,
        };
        let exec = super::desktop_exec(&exe.to_string_lossy())?;
        let body = format!(
            "[Desktop Entry]\nType=Application\nName={}\nExec={exec}\nTerminal=false\nStartupNotify=false\nX-GNOME-Autostart-enabled=true\n",
            app.package_info().name
        );
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        std::fs::write(&path, body).map_err(|e| e.to_string())
    }
}

#[cfg(any(windows, target_os = "linux"))]
pub use platform::{is_enabled, set};

#[cfg(not(any(target_os = "macos", windows, target_os = "linux")))]
pub fn is_enabled(_app: &AppHandle) -> Result<bool, String> {
    Ok(false)
}

#[cfg(not(any(target_os = "macos", windows, target_os = "linux")))]
pub fn set(_app: &AppHandle, _enabled: bool) -> Result<(), String> {
    Err("Launch at login is not supported on this system.".into())
}

/// The Run value: the path in quotes (a Windows path cannot hold `"`).
#[cfg_attr(not(windows), allow(dead_code))]
fn windows_command(exe: &str) -> String {
    format!("\"{exe}\"")
}

/// An `Exec=` value that runs `exe`, quoted as the Desktop Entry spec says.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn desktop_exec(exe: &str) -> Result<String, String> {
    if exe.contains(['\n', '\r']) {
        return Err("The app path has a line break.".into());
    }
    let mut quoted = String::from("\"");
    for c in exe.chars() {
        match c {
            // The quoting rule escapes these with a backslash; the string
            // rule then doubles every backslash.
            '"' | '`' | '$' => {
                quoted.push_str("\\\\");
                quoted.push(c);
            }
            '\\' => quoted.push_str("\\\\\\\\"),
            '%' => quoted.push_str("%%"),
            _ => quoted.push(c),
        }
    }
    quoted.push('"');
    Ok(quoted)
}

/// Whether an autostart entry runs at login. Desktops turn an entry off with
/// `Hidden=true` or `X-GNOME-Autostart-enabled=false` and keep the file.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn desktop_entry_enabled(body: &str) -> bool {
    let mut in_entry = false;
    // An empty or cut-off file is not an entry the desktop can start.
    let mut has_exec = false;
    for line in body.lines().map(str::trim) {
        if line.starts_with('[') {
            in_entry = line == "[Desktop Entry]";
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        let (key, value) = (key.trim(), value.trim());
        if in_entry && key == "Exec" && !value.is_empty() {
            has_exec = true;
        }
        if in_entry
            && ((key == "Hidden" && value == "true")
                || (key == "X-GNOME-Autostart-enabled" && value == "false"))
        {
            return false;
        }
    }
    has_exec
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_whether_an_autostart_entry_is_on() {
        let on = "[Desktop Entry]\nType=Application\nExec=onyx\nX-GNOME-Autostart-enabled=true\n";
        assert!(desktop_entry_enabled(on));
        assert!(!desktop_entry_enabled(""));
        assert!(!desktop_entry_enabled(
            "[Desktop Entry]\nType=Application\n"
        ));
        assert!(!desktop_entry_enabled(
            "[Desktop Entry]\nExec=onyx\nHidden=true\n"
        ));
        assert!(!desktop_entry_enabled(
            "[Desktop Entry]\nExec=onyx\nX-GNOME-Autostart-enabled = false\n"
        ));
        assert!(desktop_entry_enabled(
            "[Desktop Entry]\nExec=onyx\nHidden=false\n# Hidden=true\n"
        ));
        // Keys in another group do not apply to the entry.
        assert!(desktop_entry_enabled(
            "[Desktop Entry]\nExec=onyx\n[Desktop Action x]\nHidden=true\n"
        ));
    }

    #[test]
    fn quotes_the_path() {
        assert_eq!(
            windows_command(r"C:\Program Files\Onyx v2\Onyx v2.exe"),
            r#""C:\Program Files\Onyx v2\Onyx v2.exe""#
        );
        assert_eq!(
            desktop_exec("/opt/Onyx v2/onyx").unwrap(),
            r#""/opt/Onyx v2/onyx""#
        );
        assert_eq!(
            desktop_exec(r#"/a "b"/$c`d`/e\f/100%"#).unwrap(),
            r#""/a \\"b\\"/\\$c\\`d\\`/e\\\\f/100%%""#
        );
        assert!(desktop_exec("/a\nb").is_err());
    }
}
