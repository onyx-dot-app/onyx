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
