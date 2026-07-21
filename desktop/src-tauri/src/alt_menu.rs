// Native GTK-level Alt-alone-press menu toggle for Linux.
//
// Bare `Alt` can't be expressed as a Tauri menu accelerator or a
// tauri-plugin-global-shortcut binding (both require a non-modifier key), so
// this hooks the toplevel GTK window's own key events directly. That's the
// same event path that already makes accelerators like `CmdOrCtrl+N` fire
// reliably regardless of which widget has focus -- GTK dispatches keyboard
// events to the toplevel window first, which is what makes this more
// reliable than the previous approach of listening for keydown/keyup inside
// the webview's DOM (which only saw the key when the page content itself had
// focus).

/// Tracks whether Alt is currently being held down "alone", so a menu-bar
/// toggle only fires when Alt is pressed and released without any other key
/// being pressed in between.
#[derive(Debug, Default)]
// Only wired up from the Linux GTK setup below, but kept unconditionally
// compiled (and unit-tested) since the state machine itself has no
// platform dependencies -- suppress dead-code on the non-Linux builds where
// nothing outside `#[cfg(test)]` constructs it.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
pub struct AltAloneTracker {
    held_alone: bool,
}

#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
impl AltAloneTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Feed a key-press event. `is_alt` is whether the pressed key is Alt;
    /// `other_modifier_held` is whether Ctrl/Shift/Super/etc. was already
    /// down when this key went down. Pressing any other key cancels "alone"
    /// tracking, and pressing Alt while another modifier is already held
    /// (e.g. Ctrl-then-Alt) must not start it -- otherwise releasing Alt
    /// first would toggle the menu even though Ctrl is still held.
    pub const fn on_key_press(&mut self, is_alt: bool, other_modifier_held: bool) {
        self.held_alone = is_alt && !other_modifier_held;
    }

    /// Feed a key-release event. `is_alt` is whether the released key is
    /// Alt. Returns `true` when this release completes a clean,
    /// uninterrupted Alt-alone press and the menu bar should toggle.
    pub const fn on_key_release(&mut self, is_alt: bool) -> bool {
        if !is_alt || !self.held_alone {
            return false;
        }
        self.held_alone = false;
        true
    }
}

#[cfg(target_os = "linux")]
mod linux {
    use super::AltAloneTracker;
    use crate::menu::handle_menu_bar_toggle;
    use gtk::gdk::{self, keys::constants as key};
    use gtk::glib;
    use gtk::prelude::*;
    use std::cell::RefCell;
    use std::rc::Rc;
    use tauri::{AppHandle, WebviewWindow};

    fn is_alt(keyval: gdk::keys::Key) -> bool {
        keyval == key::Alt_L || keyval == key::Alt_R
    }

    /// Hook Alt-alone-press/release directly on the window's native GTK
    /// toplevel so the menu-bar toggle fires no matter which widget (webview
    /// content, title bar, etc.) currently has focus.
    pub fn setup_alt_menu_toggle(app: &AppHandle, window: &WebviewWindow) {
        let gtk_window = match window.gtk_window() {
            Ok(w) => w,
            Err(e) => {
                crate::debug_log::log_backend_error(
                    app,
                    &format!("Failed to get native GTK window for Alt-menu toggle: {e}"),
                );
                return;
            }
        };

        // Bare Alt is GTK's default "mnemonic modifier" (used to underline
        // and activate menu mnemonics). Disabling it stops that native
        // behavior from visually competing with our own Alt-alone toggle.
        gtk_window.set_mnemonic_modifier(gdk::ModifierType::empty());

        let tracker = Rc::new(RefCell::new(AltAloneTracker::new()));

        let press_tracker = tracker.clone();
        gtk_window.connect_key_press_event(move |_win, event| {
            let other_modifier_held = event.state().intersects(
                gdk::ModifierType::CONTROL_MASK
                    | gdk::ModifierType::SHIFT_MASK
                    | gdk::ModifierType::SUPER_MASK
                    | gdk::ModifierType::META_MASK
                    | gdk::ModifierType::HYPER_MASK,
            );
            press_tracker
                .borrow_mut()
                .on_key_press(is_alt(event.keyval()), other_modifier_held);
            glib::Propagation::Proceed
        });

        let app_handle_release = app.clone();
        gtk_window.connect_key_release_event(move |_win, event| {
            let toggled = tracker.borrow_mut().on_key_release(is_alt(event.keyval()));
            if toggled {
                handle_menu_bar_toggle(&app_handle_release);
            }
            glib::Propagation::Proceed
        });
    }
}

#[cfg(target_os = "linux")]
pub use linux::setup_alt_menu_toggle;

// Windows has no toplevel-key-event hook equivalent to the Linux GTK
// approach above, so it keeps the previous DOM-level listener (see git
// history predating the Linux native rework) instead of losing the toggle
// entirely.
#[cfg(target_os = "windows")]
mod windows {
    use tauri::Webview;

    const ALT_MENU_SCRIPT: &str = include_str!("scripts/alt_menu_windows.js");

    pub fn inject_alt_menu_script(webview: &Webview) {
        if let Err(e) = webview.eval(ALT_MENU_SCRIPT) {
            crate::debug_log::log_backend_error(
                webview.app_handle(),
                &format!("Failed to inject Alt-menu toggle script: {e}"),
            );
        }
    }
}

#[cfg(target_os = "windows")]
pub use windows::inject_alt_menu_script;

#[cfg(test)]
mod tests {
    use super::AltAloneTracker;

    #[test]
    fn alone_press_and_release_toggles() {
        let mut tracker = AltAloneTracker::new();
        tracker.on_key_press(true, false);
        assert!(tracker.on_key_release(true));
    }

    #[test]
    fn press_other_key_then_release_alt_does_not_toggle() {
        let mut tracker = AltAloneTracker::new();
        tracker.on_key_press(true, false);
        tracker.on_key_press(false, false); // e.g. Tab pressed while Alt is held
        assert!(!tracker.on_key_release(true));
    }

    #[test]
    fn other_modifier_held_before_alt_press_does_not_toggle() {
        let mut tracker = AltAloneTracker::new();
        tracker.on_key_press(false, false); // Ctrl pressed first
        tracker.on_key_press(true, true); // Alt pressed while Ctrl is held
        assert!(!tracker.on_key_release(true));
    }

    #[test]
    fn key_repeat_does_not_retrigger() {
        let mut tracker = AltAloneTracker::new();
        tracker.on_key_press(true, false);
        tracker.on_key_press(true, false); // simulated repeat of the Alt press
        assert!(tracker.on_key_release(true));
        // A second release call (no matching press) must not fire again.
        assert!(!tracker.on_key_release(true));
    }

    #[test]
    fn releasing_a_non_alt_key_does_not_toggle() {
        let mut tracker = AltAloneTracker::new();
        tracker.on_key_press(true, false);
        assert!(!tracker.on_key_release(false));
        // Alt is still considered held-alone afterwards.
        assert!(tracker.on_key_release(true));
    }

    #[test]
    fn releasing_alt_without_a_prior_press_does_not_toggle() {
        let mut tracker = AltAloneTracker::new();
        assert!(!tracker.on_key_release(true));
    }
}
