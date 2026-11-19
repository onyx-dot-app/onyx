//! The launcher panel. On macOS it is a non-activating `NSPanel`, like
//! Spotlight: the global shortcut shows it over whatever app is in front (also
//! full-screen apps and on every Space), it takes keystrokes without bringing
//! Onyx's other windows forward, and it hides when it loses focus. On Windows
//! and Linux it is a borderless, always-on-top window with no taskbar entry
//! that takes focus when shown and hides when it loses focus.

use tauri::{AppHandle, Manager, WebviewUrl};

use crate::windows::{local_navigation_allowed, local_new_window, LAUNCHER};

#[cfg(target_os = "macos")]
// The panel_event! macro needs the explicit `-> ()` return type.
#[allow(clippy::unused_unit)]
mod platform {
    use std::sync::atomic::{AtomicBool, Ordering};

    use objc2_app_kit::NSApplication;
    use tauri::{AppHandle, LogicalSize, Manager, Size, WebviewUrl};
    use tauri_nspanel::{
        tauri_panel, CollectionBehavior, ManagerExt, PanelBuilder, PanelLevel, StyleMask,
    };

    use super::{local_navigation_allowed, local_new_window, LAUNCHER};

    tauri_panel! {
        panel!(LauncherPanel {
            config: {
                can_become_key_window: true,
                is_floating_panel: true
            }
        })

        panel_event!(LauncherPanelEvents {
            window_did_resign_key(notification: &NSNotification) -> ()
        })
    }

    pub fn ensure(app: &AppHandle, url: WebviewUrl) -> Result<(), String> {
        if app.get_webview_panel(LAUNCHER).is_ok() {
            return Ok(());
        }
        let nav_app = app.clone();
        let new_window = local_new_window(app);
        let panel = PanelBuilder::<_, LauncherPanel>::new(app, LAUNCHER)
            .url(url)
            .title("Onyx Launcher")
            .size(Size::Logical(LogicalSize::new(720.0, 460.0)))
            .level(PanelLevel::Floating)
            .style_mask(StyleMask::empty().borderless().nonactivating_panel())
            .collection_behavior(
                CollectionBehavior::new()
                    .can_join_all_spaces()
                    .full_screen_auxiliary()
                    .ignores_cycle(),
            )
            .hides_on_deactivate(false)
            // Building a window activates the app by default; the launcher must
            // leave the app you are in active, as Spotlight does.
            .no_activate(true)
            .has_shadow(true)
            .transparent(true)
            .with_window(move |window| {
                window
                    .decorations(false)
                    .transparent(true)
                    .skip_taskbar(true)
                    .resizable(false)
                    .visible(false)
                    .focused(false)
                    .on_navigation(move |url| local_navigation_allowed(&nav_app, url))
                    .on_new_window(new_window)
            })
            .build()
            .map_err(|e| e.to_string())?;

        // Native rounded corners (and a matching shadow); the page's frame
        // uses the same 16px radius.
        panel.set_corner_radius(16.0);
        clip_to_corners(app);
        prevent_activation(app);

        // Clicking another app or window takes key status away: hide, as
        // Spotlight does.
        let handler = LauncherPanelEvents::new();
        let hide_app = app.clone();
        handler.window_did_resign_key(move |_| hide(&hide_app));
        panel.set_event_handler(Some(handler.as_ref()));
        // The panel's delegate is a weak reference; keep the handler alive.
        std::mem::forget(handler);
        Ok(())
    }

    /// `set_corner_radius` rounds the content layer but does not clip to it.
    fn clip_to_corners(app: &AppHandle) {
        use objc2::msg_send;
        use objc2::runtime::{AnyObject, Bool};
        let Some(window) = app.get_webview_window(LAUNCHER) else {
            return;
        };
        let Ok(ns_window) = window.ns_window() else {
            return;
        };
        // SAFETY: runs on the main thread with a live NSWindow; contentView and
        // its layer are standard AppKit/Core Animation objects.
        unsafe {
            let content: *mut AnyObject = msg_send![ns_window.cast::<AnyObject>(), contentView];
            if content.is_null() {
                return;
            }
            let layer: *mut AnyObject = msg_send![content, layer];
            if !layer.is_null() {
                let _: () = msg_send![layer, setMasksToBounds: Bool::YES];
            }
        }
    }

    /// tauri-nspanel turns an existing window into a panel, and AppKit applies
    /// the non-activating style to the window server only when the window is
    /// created with it. Without this the panel cannot become key while another
    /// app stays active, so it could not take typing without activating Onyx.
    fn prevent_activation(app: &AppHandle) {
        use objc2::runtime::{AnyObject, Bool, Sel};
        use objc2::{msg_send, sel};
        let Some(window) = app.get_webview_window(LAUNCHER) else {
            return;
        };
        let Ok(ns_window) = window.ns_window() else {
            return;
        };
        let selector: Sel = sel!(_setPreventsActivation:);
        // SAFETY: main thread, live NSWindow; the private setter is only called
        // when the window responds to it.
        unsafe {
            let ns_window = ns_window.cast::<AnyObject>();
            let responds: Bool = msg_send![ns_window, respondsToSelector: selector];
            if responds.as_bool() {
                let _: () = msg_send![ns_window, _setPreventsActivation: Bool::YES];
            }
        }
    }

    /// Set while the launcher shows for an app the user hid (Cmd+H). Showing
    /// any window unhides the app and with it the main window, which a
    /// Spotlight-style launcher must not bring back.
    static OVER_HIDDEN_APP: AtomicBool = AtomicBool::new(false);

    /// Makes the app's other windows invisible and click-through, or restores them.
    fn set_others_invisible(app: &AppHandle, invisible: bool) {
        for (label, window) in app.webview_windows() {
            if label == LAUNCHER {
                continue;
            }
            let Ok(ns_window) = window.ns_window() else {
                continue;
            };
            let alpha: f64 = if invisible { 0.0 } else { 1.0 };
            // SAFETY: main thread, live NSWindow.
            unsafe {
                let ns_window = ns_window.cast::<AnyObject>();
                let _: () = msg_send![ns_window, setAlphaValue: alpha];
                let _: () = msg_send![ns_window, setIgnoresMouseEvents: Bool::new(invisible)];
            }
        }
    }

    pub fn show(app: &AppHandle) -> Result<(), String> {
        let panel = app
            .get_webview_panel(LAUNCHER)
            .map_err(|e| format!("{e:?}"))?;
        if let Some(window) = app.get_webview_window(LAUNCHER) {
            let _ = window.center();
        }
        if let Some(mtm) = MainThreadMarker::new() {
            if NSApplication::sharedApplication(mtm).isHidden() {
                set_others_invisible(app, true);
                OVER_HIDDEN_APP.store(true, Ordering::SeqCst);
            }
        }
        panel.show_and_make_key();
        Ok(())
    }

    pub fn hide(app: &AppHandle) {
        if let Ok(panel) = app.get_webview_panel(LAUNCHER) {
            panel.hide();
        }
        // Back to how the user left it: hidden, with its windows intact for
        // the next unhide. A window that opens from the launcher (Cmd+Enter)
        // activates the app again afterwards.
        if OVER_HIDDEN_APP.swap(false, Ordering::SeqCst) {
            if let Some(mtm) = MainThreadMarker::new() {
                NSApplication::sharedApplication(mtm).hide(None);
            }
            set_others_invisible(app, false);
        }
    }

    /// Another window is coming forward: the app stays shown, so a later
    /// launcher hide must not hide it again.
    pub fn keep_app_shown(app: &AppHandle) {
        if OVER_HIDDEN_APP.swap(false, Ordering::SeqCst) {
            set_others_invisible(app, false);
        }
    }

    pub fn is_visible(app: &AppHandle) -> bool {
        app.get_webview_panel(LAUNCHER)
            .map(|panel| panel.is_visible())
            .unwrap_or(false)
    }
}

#[cfg(not(target_os = "macos"))]
mod platform {
    use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};

    use super::{local_navigation_allowed, local_new_window, LAUNCHER};

    pub fn ensure(app: &AppHandle, url: WebviewUrl) -> Result<(), String> {
        if app.get_webview_window(LAUNCHER).is_some() {
            return Ok(());
        }
        let nav_app = app.clone();
        let window = WebviewWindowBuilder::new(app, LAUNCHER, url)
            .title("Onyx Launcher")
            .inner_size(720.0, 460.0)
            .decorations(false)
            .transparent(true)
            // The page draws its own rounded frame; a native shadow would
            // outline the transparent corners on Windows.
            .shadow(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .visible_on_all_workspaces(true)
            .resizable(false)
            .visible(false)
            .on_navigation(move |url| local_navigation_allowed(&nav_app, url))
            .on_new_window(local_new_window(app))
            .build()
            .map_err(|e| e.to_string())?;
        let handle = window.clone();
        window.on_window_event(move |event| {
            if let WindowEvent::Focused(false) = event {
                let _ = handle.hide();
            }
        });
        Ok(())
    }

    pub fn show(app: &AppHandle) -> Result<(), String> {
        let window = app.get_webview_window(LAUNCHER).ok_or("launcher missing")?;
        let _ = window.center();
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())
    }

    pub fn hide(app: &AppHandle) {
        if let Some(window) = app.get_webview_window(LAUNCHER) {
            let _ = window.hide();
        }
    }

    pub fn keep_app_shown(_app: &AppHandle) {}

    pub fn is_visible(app: &AppHandle) -> bool {
        app.get_webview_window(LAUNCHER)
            .is_some_and(|w| w.is_visible().unwrap_or(false))
    }
}

/// Where the launcher page keeps recent questions (`Launcher.tsx`).
const HISTORY_KEY: &str = "onyx.launcher.history";

// AppKit panels must be created and changed on the main thread, and callers
// include background threads (commands), so every entry point hops there.

pub fn hide(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || platform::hide(&handle));
}

/// Called before another Onyx window comes forward (Dock, tray, Cmd+Enter),
/// so the launcher losing focus to it does not hide the app again.
pub fn keep_app_shown(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || platform::keep_app_shown(&handle));
}

/// Hides the panel and reloads its page, which clears the question, answer,
/// results and recent questions. Updates from requests still running reach
/// the old page only.
pub fn reset(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        platform::hide(&handle);
        if let Some(window) = handle.get_webview_window(LAUNCHER) {
            // Recent questions belong to the account that asked them.
            let _ = window.eval(format!(
                "localStorage.removeItem({HISTORY_KEY:?}); location.reload()"
            ));
        }
    });
}

/// Creates the hidden panel at startup. Creating it on the first shortcut
/// press left that press without a visible, key panel.
pub fn preload(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Err(e) = platform::ensure(&handle, WebviewUrl::App("launcher.html".into())) {
            log::warn!("could not create the launcher: {e}");
        }
    });
}

/// Shows the launcher if it is hidden, hides it if it is showing.
pub fn toggle(app: &AppHandle, when_signed_out: impl FnOnce(&AppHandle) + Send + 'static) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        let state = handle.state::<crate::state::AppState>();
        // Checked here too: a policy read can turn the launcher off after
        // the caller checked.
        if platform::is_visible(&handle) || state.policy().disable_launcher {
            platform::hide(&handle);
        } else {
            show_now(&handle, when_signed_out);
        }
    });
}

/// Shows the launcher with what it last showed; does nothing if it is showing.
pub fn show(app: &AppHandle, when_signed_out: impl FnOnce(&AppHandle) + Send + 'static) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if !platform::is_visible(&handle) {
            show_now(&handle, when_signed_out);
        }
    });
}

fn show_now(app: &AppHandle, when_signed_out: impl FnOnce(&AppHandle)) {
    if app.state::<crate::state::AppState>().session().is_err() {
        when_signed_out(app);
    } else if let Err(e) = platform::ensure(app, WebviewUrl::App("launcher.html".into()))
        .and_then(|()| platform::show(app))
    {
        log::warn!("could not show launcher: {e}");
    } else {
        crate::aonyx::set_mood(app, crate::aonyx::Mood::Hop);
    }
}

/// Whether the launcher is on screen. Safe to call off the main thread.
pub fn is_visible(app: &AppHandle) -> bool {
    app.get_webview_window(LAUNCHER)
        .is_some_and(|w| w.is_visible().unwrap_or(false))
}
