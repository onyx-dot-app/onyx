use crate::config::ConfigState;
use crate::debug_log::{log_backend_debug, log_backend_error};
use crate::window::{focus_main_window, focused_webview_window, open_chat_window};
use std::sync::{Mutex, PoisonError};
use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

/// Managed only while the summon shortcut is actually registered, so menus
/// can surface the chord without risking advertising a binding that failed
/// to register.
pub struct SummonShortcut {
    pub chord: String,
}

/// Labels of the windows the last chord dismissal hid. Auxiliary windows
/// have no other path back once hidden (the tray and summon paths only
/// manage `main`), so the next summon restores this exact set.
struct DismissedWindows(Mutex<Vec<String>>);

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

    app.manage(DismissedWindows(Mutex::new(Vec::new())));

    let result = app
        .global_shortcut()
        .on_shortcut(shortcut, |app, _shortcut, event| {
            if event.state() != ShortcutState::Pressed {
                return;
            }
            // Toggle contract: the chord that summons Onyx also dismisses it,
            // returning focus to whatever app was active before. Dismissal
            // hides every visible Onyx window -- hiding only the focused one
            // would just hand focus to the next Onyx window instead of the
            // previous application.
            if focused_webview_window(app).is_some() {
                dismiss_all_windows(app);
                return;
            }
            restore_dismissed_windows(app);
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

fn dismiss_all_windows(app: &AppHandle) {
    let mut hidden = Vec::new();
    for (label, window) in app.webview_windows() {
        let visible = window.is_visible().unwrap_or_else(|e| {
            log_backend_error(app, &format!("Failed to query window visibility: {e}"));
            false
        });
        if !visible {
            continue;
        }
        if let Err(e) = window.hide() {
            log_backend_error(app, &format!("Failed to hide window \"{label}\": {e}"));
        } else {
            hidden.push(label);
        }
    }
    log_backend_debug(
        app,
        &format!(
            "Summon shortcut fired (action=dismiss, windows={})",
            hidden.len()
        ),
    );
    // Merge rather than replace: the queue may still hold labels whose
    // restore failed earlier, and overwriting would strand those windows.
    if let Some(state) = app.try_state::<DismissedWindows>() {
        let mut queued = state.0.lock().unwrap_or_else(PoisonError::into_inner);
        for label in hidden {
            if !queued.contains(&label) {
                queued.push(label);
            }
        }
    }
}

/// Re-show the windows the last dismissal hid. `main` is skipped here; the
/// summon action that follows shows and focuses it. A window whose `show`
/// fails stays queued so a later summon retries it -- dropping the label
/// would strand the window hidden with no path back.
fn restore_dismissed_windows(app: &AppHandle) {
    let Some(state) = app.try_state::<DismissedWindows>() else {
        return;
    };
    let labels = std::mem::take(&mut *state.0.lock().unwrap_or_else(PoisonError::into_inner));
    let mut failed = Vec::new();
    for label in labels {
        if label == "main" {
            continue;
        }
        if let Some(window) = app.get_webview_window(&label) {
            if let Err(e) = window.show() {
                log_backend_error(app, &format!("Failed to restore window \"{label}\": {e}"));
                failed.push(label);
            }
        }
    }
    if !failed.is_empty() {
        state
            .0
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .extend(failed);
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
