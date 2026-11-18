use tauri::AppHandle;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

use crate::windows;

pub fn register(app: &AppHandle, accelerator: &str) -> Result<(), String> {
    app.global_shortcut()
        .on_shortcut(accelerator, |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                windows::toggle_launcher(app);
            }
        })
        .map_err(|e| format!("Could not use {accelerator} as the shortcut: {e}"))
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
