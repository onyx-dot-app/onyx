use tauri::AppHandle;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

use crate::windows;

pub fn register(app: &AppHandle, accelerator: &str) -> Result<(), String> {
    app.global_shortcut()
        .on_shortcut(accelerator, |app, shortcut, event| {
            crate::qa::log(&format!("global shortcut {shortcut} {:?}", event.state()));
            if event.state() == ShortcutState::Pressed {
                windows::toggle_launcher(app);
            }
        })
        .map_err(|e| {
            // The library's message is for the log, not the settings window.
            log::warn!("could not register {accelerator}: {e}");
            "That shortcut is not available. Try a different one.".to_string()
        })
}

pub fn is_registered(app: &AppHandle, accelerator: &str) -> bool {
    app.global_shortcut().is_registered(accelerator)
}

/// Why the launcher shortcut may not work, for Preferences.
pub fn notice(app: &AppHandle, accelerator: &str) -> Option<String> {
    if !is_registered(app, accelerator) {
        return Some(
            "The launcher shortcut is not active. Another app may use it. Choose a different one."
                .into(),
        );
    }
    // global-hotkey grabs keys on X11 only. Under Wayland the registration
    // reports success, but no key press reaches Onyx while a Wayland app has focus.
    #[cfg(target_os = "linux")]
    if is_wayland() {
        return Some(
            "This is a Wayland session. The shortcut may not work while another app has focus. \
             Open the launcher from the tray icon instead."
                .into(),
        );
    }
    None
}

#[cfg(target_os = "linux")]
fn is_wayland() -> bool {
    std::env::var("XDG_SESSION_TYPE").is_ok_and(|t| t.eq_ignore_ascii_case("wayland"))
        || std::env::var_os("WAYLAND_DISPLAY").is_some()
}

/// Swaps the launcher shortcut. Restores the old one if the new one fails.
pub fn rebind(app: &AppHandle, old: &str, new: &str) -> Result<(), String> {
    if old == new {
        return Ok(());
    }
    let _ = app.global_shortcut().unregister(old);
    if let Err(e) = register(app, new) {
        let _ = register(app, old);
        return Err(e);
    }
    Ok(())
}

/// Swaps one launcher shortcut (or none) for another (or none).
pub fn replace(app: &AppHandle, old: Option<&str>, new: Option<&str>) -> Result<(), String> {
    match (old, new) {
        (Some(old), Some(new)) => rebind(app, old, new),
        (Some(old), None) => {
            let _ = app.global_shortcut().unregister(old);
            Ok(())
        }
        (None, Some(new)) => register(app, new),
        (None, None) => Ok(()),
    }
}
