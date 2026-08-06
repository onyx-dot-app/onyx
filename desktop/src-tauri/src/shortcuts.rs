use crate::config::ConfigState;
use crate::debug_log::{log_backend_debug, log_backend_error};
use crate::window::{focus_main_window, open_chat_window};
use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

/// Managed only while the summon shortcut is actually registered, so menus
/// can surface the chord without risking advertising a binding that failed
/// to register.
pub struct SummonShortcut {
    pub chord: String,
}

/// Register the configured summon shortcut. This is deliberately the only
/// global (system-wide) shortcut the app registers: summoning Onyx is the one
/// action that must work while another app is focused. Every other shortcut
/// belongs in the menus, which only fire while Onyx has focus -- registering
/// in-app chords like CmdOrCtrl+N globally steals them from every other
/// application (the #7914 regression).
pub fn setup_global_shortcuts(app: &AppHandle) {
    let Some(chord) = app.state::<ConfigState>().config().summon_shortcut else {
        return;
    };

    let shortcut: Shortcut = match chord.parse() {
        Ok(shortcut) => shortcut,
        Err(e) => {
            log_backend_error(app, &format!("Invalid summon shortcut \"{chord}\": {e}"));
            return;
        }
    };

    let result = app
        .global_shortcut()
        .on_shortcut(shortcut, |app, _shortcut, event| {
            if event.state() != ShortcutState::Pressed {
                return;
            }
            let opens_new_chat = app.state::<ConfigState>().config().summon_opens_new_chat;
            log_backend_debug(
                app,
                &format!("Summon shortcut fired (opens_new_chat={opens_new_chat})"),
            );
            if opens_new_chat {
                open_chat_window(app);
            } else {
                focus_main_window(app);
            }
        });

    match result {
        Ok(()) => {
            log_backend_debug(app, &format!("Registered summon shortcut \"{chord}\""));
            app.manage(SummonShortcut { chord });
        }
        // Registration fails when another app owns the chord (reliably
        // reported on Windows/X11 only) or on Wayland, where the plugin has
        // no backend. The app stays fully usable without the shortcut.
        Err(e) => {
            log_backend_error(
                app,
                &format!("Failed to register summon shortcut \"{chord}\": {e}"),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_chords_parse_as_shortcuts() {
        for chord in ["Super+Shift+Space", "Ctrl+Alt+Space"] {
            assert!(
                chord.parse::<Shortcut>().is_ok(),
                "default chord {chord} no longer parses"
            );
        }
    }
}
