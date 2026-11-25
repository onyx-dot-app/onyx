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
                    // Dropped files reach the page as HTML drops (attachments).
                    .disable_drag_drop_handler()
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
    use tauri::{
        AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindowBuilder,
        WindowEvent,
    };

    use super::{local_navigation_allowed, local_new_window, LAUNCHER};

    pub fn ensure(app: &AppHandle, url: WebviewUrl) -> Result<(), String> {
        if app.get_webview_window(LAUNCHER).is_some() {
            return Ok(());
        }
        let nav_app = app.clone();
        let window = WebviewWindowBuilder::new(app, LAUNCHER, url)
            .title("Onyx Launcher")
            .inner_size(super::SIZE.0, super::SIZE.1)
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
            .disable_drag_drop_handler()
            .build()
            .map_err(|e| e.to_string())?;
        let handle = window.clone();
        window.on_window_event(move |event| {
            if let WindowEvent::Focused(false) = event {
                // Windows can move the foreground once more right after a
                // notification click shows the launcher.
                #[cfg(windows)]
                if super::take_blur_grace(std::time::Instant::now()) {
                    return;
                }
                let _ = handle.hide();
            }
        });
        Ok(())
    }

    /// Brings the launcher to the foreground after a notification click.
    /// Windows gives the foreground only to the process that got the last
    /// input, here the notification host. If the first try fails, a
    /// synthetic Alt press makes this process the one with the last input;
    /// no other thread's input queue is joined.
    #[cfg(windows)]
    pub fn take_foreground(app: &AppHandle) {
        use ::windows::Win32::UI::Input::KeyboardAndMouse::{
            SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYBD_EVENT_FLAGS,
            KEYEVENTF_KEYUP, VK_MENU,
        };
        use ::windows::Win32::UI::WindowsAndMessaging::{
            BringWindowToTop, GetForegroundWindow, SetForegroundWindow,
        };

        let Some(window) = app.get_webview_window(LAUNCHER) else {
            return;
        };
        let Ok(hwnd) = window.hwnd() else {
            return;
        };
        let alt = |flags: KEYBD_EVENT_FLAGS| INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT {
                    wVk: VK_MENU,
                    dwFlags: flags,
                    ..Default::default()
                },
            },
        };
        let size = std::mem::size_of::<INPUT>() as i32;
        // SAFETY: plain Win32 calls on the main thread with a live window
        // handle; SendInput reads only the local array.
        let raised = unsafe {
            if GetForegroundWindow() == hwnd {
                return;
            }
            let _ = BringWindowToTop(hwnd);
            SetForegroundWindow(hwnd).as_bool() || {
                SendInput(&[alt(KEYBD_EVENT_FLAGS(0))], size);
                let raised = SetForegroundWindow(hwnd).as_bool();
                SendInput(&[alt(KEYEVENTF_KEYUP)], size);
                raised
            }
        };
        if !raised {
            log::warn!("Windows did not bring the launcher to the foreground");
        }
        // Keyboard focus into the web view.
        let _ = window.set_focus();
    }

    pub fn show(app: &AppHandle) -> Result<(), String> {
        let window = app.get_webview_window(LAUNCHER).ok_or("launcher missing")?;
        match position_on_cursor_monitor(app) {
            Some((position, _size)) => {
                let _ = window.set_position(position);
                // A hidden window keeps its size through a display scale change.
                #[cfg(windows)]
                let _ = window.set_size(_size);
            }
            None => {
                let _ = window.center();
            }
        }
        #[cfg(target_os = "linux")]
        {
            present(&window)
        }
        #[cfg(not(target_os = "linux"))]
        {
            window.show().map_err(|e| e.to_string())?;
            window.set_focus().map_err(|e| e.to_string())
        }
    }

    /// The launcher's place and physical size on the monitor under the
    /// pointer, the one the user works on. `center()` keeps it on the monitor
    /// it was on.
    fn position_on_cursor_monitor(
        app: &AppHandle,
    ) -> Option<(PhysicalPosition<i32>, PhysicalSize<u32>)> {
        let cursor = app.cursor_position().ok()?;
        let monitor = app.monitor_from_point(cursor.x, cursor.y).ok()??;
        // The known size: tao reports a wrong outer size for a window that
        // was never shown on Linux. The logical size is kept on a monitor with
        // another scale.
        Some(super::placement(
            monitor.work_area(),
            monitor.scale_factor(),
        ))
    }

    /// Shows the launcher and asks the window manager for focus. KWin and
    /// Openbox refuse focus to a request without a fresh X timestamp, and no
    /// key event reaches GTK for a grabbed global shortcut.
    #[cfg(target_os = "linux")]
    fn present(window: &tauri::WebviewWindow) -> Result<(), String> {
        use gdkx11::glib::Cast;
        use gtk::prelude::{GtkWindowExt, WidgetExt};

        let gtk_window = window.gtk_window().map_err(|e| e.to_string())?;
        gtk_window.show_all();
        let time = gtk_window
            .window()
            .and_then(|w| w.downcast::<gdkx11::X11Window>().ok())
            .map(|w| gdkx11::functions::x11_get_server_time(&w))
            .unwrap_or(gdkx11::gdk::ffi::GDK_CURRENT_TIME as u32);
        gtk_window.present_with_time(time);
        Ok(())
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

/// The launcher's size on Windows and Linux, in logical pixels.
#[cfg(any(not(target_os = "macos"), test))]
const SIZE: (f64, f64) = (720.0, 460.0);

/// The launcher's place and physical size, centered in `work_area` at `scale`.
#[cfg(any(not(target_os = "macos"), test))]
fn placement(
    work_area: &tauri::PhysicalRect<i32, u32>,
    scale: f64,
) -> (tauri::PhysicalPosition<i32>, tauri::PhysicalSize<u32>) {
    let size = tauri::LogicalSize::new(SIZE.0, SIZE.1).to_physical::<u32>(scale);
    (centered(work_area, size), size)
}

/// The top-left corner that centers a window of `size` in `work_area`.
#[cfg(any(not(target_os = "macos"), test))]
fn centered(
    work_area: &tauri::PhysicalRect<i32, u32>,
    size: tauri::PhysicalSize<u32>,
) -> tauri::PhysicalPosition<i32> {
    let offset = |area: u32, window: u32| (i64::from(area) - i64::from(window)) / 2;
    tauri::PhysicalPosition::new(
        (i64::from(work_area.position.x) + offset(work_area.size.width, size.width)) as i32,
        (i64::from(work_area.position.y) + offset(work_area.size.height, size.height)) as i32,
    )
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
    // The cleared answer must not notify later (a rejected session resets
    // the launcher without a sign-out).
    crate::aonyx::answer_discarded(app);
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
            crate::windows::window_failed(
                &handle,
                crate::windows::FailedWindow::LauncherPreload,
                &format!("could not create the launcher: {e}"),
            );
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

/// Shows the launcher with what it last showed, for a click on a
/// notification, if `wanted` still holds on the main thread. A launcher that
/// is showing stays; on Windows it also takes the foreground.
pub fn show_for_notification(
    app: &AppHandle,
    wanted: impl FnOnce(&AppHandle) -> bool + Send + 'static,
    when_signed_out: impl FnOnce(&AppHandle) + Send + 'static,
) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        // `wanted` runs for a visible launcher too: it can route the page
        // (a notification click switches to the answer).
        if !wanted(&handle) {
            return;
        }
        #[cfg(windows)]
        start_blur_grace(std::time::Instant::now());
        if !platform::is_visible(&handle) {
            show_now(&handle, when_signed_out);
        }
        #[cfg(windows)]
        if platform::is_visible(&handle) {
            platform::take_foreground(&handle);
        }
    });
}

/// How long after a notification click the launcher ignores losing focus.
#[cfg(any(windows, test))]
const BLUR_GRACE: std::time::Duration = std::time::Duration::from_secs(1);

/// When a notification click last showed the launcher.
#[cfg(windows)]
static BLUR_GRACE_START: std::sync::Mutex<Option<std::time::Instant>> = std::sync::Mutex::new(None);

#[cfg(windows)]
fn start_blur_grace(now: std::time::Instant) {
    *BLUR_GRACE_START.lock().unwrap_or_else(|p| p.into_inner()) = Some(now);
}

/// Whether the launcher ignores this loss of focus. Only the first one after
/// a notification click is ignored.
#[cfg(windows)]
fn take_blur_grace(now: std::time::Instant) -> bool {
    let started = BLUR_GRACE_START
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .take();
    in_blur_grace(started, now)
}

#[cfg(any(windows, test))]
fn in_blur_grace(started: Option<std::time::Instant>, now: std::time::Instant) -> bool {
    started.is_some_and(|started| now.saturating_duration_since(started) < BLUR_GRACE)
}

fn show_now(app: &AppHandle, when_signed_out: impl FnOnce(&AppHandle)) {
    let state = app.state::<crate::state::AppState>();
    if state.policy().disable_launcher {
        log::info!("not showing the launcher: managed policy turns it off");
    } else if state.session().is_err() {
        when_signed_out(app);
    } else if let Err(e) = platform::ensure(app, WebviewUrl::App("launcher.html".into()))
        .and_then(|()| platform::show(app))
    {
        crate::windows::window_failed(
            app,
            crate::windows::FailedWindow::Launcher,
            &format!("could not show launcher: {e}"),
        );
    } else {
        crate::aonyx::set_mood(app, crate::aonyx::Mood::Hop);
    }
}

/// Shows the launcher (Try Again after it did not open).
#[cfg_attr(not(windows), allow(dead_code))]
pub fn show(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        show_now(&handle, crate::windows::route);
    });
}

/// Whether the launcher is on screen. Safe to call off the main thread.
pub fn is_visible(app: &AppHandle) -> bool {
    app.get_webview_window(LAUNCHER)
        .is_some_and(|w| w.is_visible().unwrap_or(false))
}

#[cfg(test)]
mod tests {
    use tauri::{PhysicalPosition, PhysicalRect, PhysicalSize};

    use super::{centered, in_blur_grace, placement, BLUR_GRACE};

    #[test]
    fn only_a_loss_of_focus_soon_after_a_notification_click_is_ignored() {
        let start = std::time::Instant::now();
        let soon = start + std::time::Duration::from_millis(300);
        assert!(in_blur_grace(Some(start), start));
        assert!(in_blur_grace(Some(start), soon));
        assert!(!in_blur_grace(Some(start), start + BLUR_GRACE));
        assert!(!in_blur_grace(None, soon));
        // A clock read before the click does not count as later.
        assert!(in_blur_grace(Some(soon), start));
    }

    fn area(x: i32, y: i32, width: u32, height: u32) -> PhysicalRect<i32, u32> {
        PhysicalRect {
            position: PhysicalPosition::new(x, y),
            size: PhysicalSize::new(width, height),
        }
    }

    #[test]
    fn the_size_follows_the_monitor_scale() {
        // 1280x1080 at 125%, with a 60px taskbar.
        assert_eq!(
            placement(&area(0, 0, 1280, 1020), 1.25),
            (PhysicalPosition::new(190, 222), PhysicalSize::new(900, 575))
        );
        assert_eq!(
            placement(&area(0, 0, 1280, 1020), 1.0),
            (PhysicalPosition::new(280, 280), PhysicalSize::new(720, 460))
        );
    }

    #[test]
    fn centers_on_the_given_monitor() {
        let size = PhysicalSize::new(720, 460);
        assert_eq!(
            centered(&area(0, 0, 1920, 1040), size),
            PhysicalPosition::new(600, 290)
        );
        // A second monitor to the left of and above the primary one.
        assert_eq!(
            centered(&area(-2560, -400, 2560, 1400), size),
            PhysicalPosition::new(-1640, 70)
        );
        // A work area smaller than the window keeps the window centered on it.
        assert_eq!(
            centered(&area(100, 0, 600, 400), size),
            PhysicalPosition::new(40, -30)
        );
    }
}
