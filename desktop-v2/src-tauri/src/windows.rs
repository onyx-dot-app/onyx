//! Local (bundled) windows: onboarding, login, preferences, offline and the launcher panel.

use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use url::Url;

use crate::main_window;
use crate::reachability::Unreachable;
use crate::state::AppState;

pub const ONBOARDING: &str = "onboarding";
pub const LOGIN: &str = "login";
pub const PREFERENCES: &str = "preferences";
pub const LAUNCHER: &str = "launcher";
pub const OFFLINE: &str = "offline";

/// Local windows may only show bundled pages; anything else opens in the browser.
pub(crate) fn local_navigation_allowed(app: &AppHandle, url: &Url) -> bool {
    let bundled = matches!(url.scheme(), "tauri" | "about")
        || (url.scheme() == "http" && url.host_str() == Some("tauri.localhost"));
    let dev_server = tauri::is_dev()
        && app
            .config()
            .build
            .dev_url
            .as_ref()
            .is_some_and(|dev| dev.origin() == url.origin());
    if bundled || dev_server {
        return true;
    }
    if matches!(url.scheme(), "http" | "https") {
        crate::main_window::open_external(app, url.as_str());
    }
    false
}

/// Local pages never open windows; links go to the browser.
pub(crate) fn local_new_window(
    app: &AppHandle,
) -> impl Fn(Url, tauri::webview::NewWindowFeatures) -> NewWindowResponse<tauri::Wry> + Send + 'static
{
    let app = app.clone();
    move |url, _features| {
        if matches!(url.scheme(), "http" | "https") {
            main_window::open_external(&app, url.as_str());
        }
        NewWindowResponse::Deny
    }
}

fn local_window(
    app: &AppHandle,
    label: &str,
    page: &str,
    title: &str,
    size: (f64, f64),
) -> Result<WebviewWindow, String> {
    if let Some(window) = app.get_webview_window(label) {
        bring_forward(app, &window);
        return Ok(window);
    }
    let nav_app = app.clone();
    let builder = WebviewWindowBuilder::new(app, label, WebviewUrl::App(page.into()))
        .title(title)
        .inner_size(size.0, size.1)
        .resizable(false)
        .center()
        .focused(true)
        // The first click also acts on the control, not only on the window.
        .accept_first_mouse(true)
        .on_navigation(move |url| local_navigation_allowed(&nav_app, url))
        .on_new_window(local_new_window(app));
    #[cfg(target_os = "macos")]
    let builder = builder
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true);
    // Windows keeps the Maximize button of a window that cannot be resized.
    #[cfg(not(target_os = "macos"))]
    let builder = builder.maximizable(false);
    let window = builder.build().map_err(|e| e.to_string())?;
    activate_app(app);
    Ok(window)
}

/// Shows `window` in front of every app. Showing a window does not activate
/// the app: from the tray or the launcher, the window would open behind the
/// app in front.
pub fn bring_forward(app: &AppHandle, window: &WebviewWindow) {
    // Queued on the main thread ahead of the focus change below.
    crate::launcher::keep_app_shown(app);
    let _ = window.show();
    let _ = window.unminimize();
    activate_app(app);
    let _ = window.set_focus();
}

#[cfg(target_os = "macos")]
fn activate_app(app: &AppHandle) {
    let _ = app.run_on_main_thread(|| {
        if let Some(mtm) = objc2::MainThreadMarker::new() {
            let ns_app = objc2_app_kit::NSApplication::sharedApplication(mtm);
            #[allow(deprecated)] // `activate` needs macOS 14.
            ns_app.activateIgnoringOtherApps(true);
        }
    });
}

#[cfg(not(target_os = "macos"))]
fn activate_app(_app: &AppHandle) {}

/// The size a local window opens at, in logical pixels.
fn initial_size(label: &str) -> Option<(f64, f64)> {
    match label {
        ONBOARDING => Some((520.0, 400.0)),
        LOGIN => Some((460.0, 520.0)),
        PREFERENCES => Some((560.0, 600.0)),
        OFFLINE => Some((460.0, 300.0)),
        _ => None,
    }
}

fn open_local(
    app: &AppHandle,
    label: &str,
    page: &str,
    title: &str,
) -> Result<WebviewWindow, String> {
    let size = initial_size(label).ok_or("not a local window")?;
    local_window(app, label, page, title, size)
}

pub fn open_onboarding(app: &AppHandle) -> Result<WebviewWindow, String> {
    open_local(app, ONBOARDING, "onboarding.html", "Welcome to Onyx")
}

pub fn open_login(app: &AppHandle) -> Result<WebviewWindow, String> {
    open_local(app, LOGIN, "login.html", "Sign in to Onyx")
}

pub fn open_preferences(app: &AppHandle) -> Result<WebviewWindow, String> {
    open_local(app, PREFERENCES, "preferences.html", "Preferences")
}

pub fn open_offline(app: &AppHandle) -> Result<WebviewWindow, String> {
    open_local(app, OFFLINE, "offline.html", "Onyx")
}

/// Logical pixels kept free above and below a local window: the title bar
/// and panels.
const SCREEN_MARGIN: f64 = 80.0;
/// The title bar height a local window is placed with, in logical pixels.
const TITLE_BAR: f64 = 40.0;

/// A local window's height and, if it must move to stay on screen, its new
/// outer position.
#[derive(Debug, PartialEq)]
pub(crate) struct Fit {
    pub height: f64,
    pub position: Option<(i32, i32)>,
}

/// Fits a window `width` logical pixels wide to `content` logical pixels of
/// height inside `work_area` (physical x, y, width, height). A window that
/// would leave the work area is centered in it.
pub(crate) fn fit_in_work_area(
    work_area: (i32, i32, u32, u32),
    scale: f64,
    position: (i32, i32),
    width: f64,
    content: f64,
) -> Fit {
    let (area_x, area_y, area_w, area_h) = work_area;
    let (area_w, area_h) = (f64::from(area_w), f64::from(area_h));
    let max_height = (area_h / scale - SCREEN_MARGIN).max(TITLE_BAR);
    let height = content.clamp(1.0, max_height);
    let outer_w = (width * scale).round();
    let outer_h = ((height + TITLE_BAR) * scale).round();
    let place = |start: i32, extent: f64, area_start: i32, area_extent: f64| -> i32 {
        let end = f64::from(start) + extent;
        if start >= area_start && end <= f64::from(area_start) + area_extent {
            start
        } else {
            area_start + ((area_extent - extent) / 2.0).max(0.0) as i32
        }
    };
    let x = place(position.0, outer_w, area_x, area_w);
    let y = place(position.1, outer_h, area_y, area_h);
    Fit {
        height,
        position: ((x, y) != position).then_some((x, y)),
    }
}

/// Sizes a local window to its content: `content_height` logical pixels
/// high, as wide as it opened, and inside its monitor's work area.
pub fn fit_to_content(window: &WebviewWindow, content_height: f64) -> Result<(), String> {
    let (width, _) = initial_size(window.label()).ok_or("not a local window")?;
    let monitor = match window.current_monitor().map_err(|e| e.to_string())? {
        Some(monitor) => Some(monitor),
        None => window.primary_monitor().map_err(|e| e.to_string())?,
    };
    let Some(monitor) = monitor else {
        return window
            .set_size(tauri::LogicalSize::new(width, content_height))
            .map_err(|e| e.to_string());
    };
    let area = monitor.work_area();
    let position = window.outer_position().map_err(|e| e.to_string())?;
    let fit = fit_in_work_area(
        (
            area.position.x,
            area.position.y,
            area.size.width,
            area.size.height,
        ),
        monitor.scale_factor(),
        (position.x, position.y),
        width,
        content_height,
    );
    window
        .set_size(tauri::LogicalSize::new(width, fit.height))
        .map_err(|e| e.to_string())?;
    if let Some((x, y)) = fit.position {
        window
            .set_position(tauri::PhysicalPosition::new(x, y))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn close(app: &AppHandle, label: &str) {
    if let Some(window) = app.get_webview_window(label) {
        let _ = window.destroy();
    }
}

pub fn hide_launcher(app: &AppHandle) {
    crate::launcher::hide(app);
}

/// Hides the launcher and drops what it shows, so the next account never sees
/// the previous one's answers or search results.
pub fn reset_launcher(app: &AppHandle) {
    crate::launcher::reset(app);
}

/// Bound to the global shortcut: shows the launcher over any app, or hides it.
pub fn toggle_launcher(app: &AppHandle) {
    if app.state::<AppState>().policy().disable_launcher {
        return;
    }
    crate::launcher::toggle(app, route);
}

/// Opens whichever window the current state needs: onboarding, login or the main window.
/// Onyx could not open although the session may be valid (the server could
/// not be reached, or its sign-in settings did not load): keep the session,
/// explain, and let the user try again or sign in.
fn open_failed(app: &AppHandle, title: &str, error: &str) {
    let dialog = rfd::MessageDialog::new()
        .set_title(title)
        .set_description(crate::dialog::text(error))
        .set_buttons(rfd::MessageButtons::OkCancelCustom(
            "Try Again".into(),
            "Sign In".into(),
        ));
    crate::dialog::show(app, dialog, |app, choice| {
        if choice == rfd::MessageDialogResult::Custom("Try Again".into()) {
            app.state::<AppState>().forget_read_failure();
            route(app);
        } else {
            let _ = open_login(app);
        }
    });
}

/// A message with an OK button, over the app's windows.
pub fn notify(app: &AppHandle, title: &str, text: &str) {
    let dialog = rfd::MessageDialog::new()
        .set_title(title)
        .set_description(crate::dialog::text(text))
        .set_buttons(rfd::MessageButtons::Ok);
    crate::dialog::show(app, dialog, |_, _| {});
}

/// How long opening Onyx waits for the session renewal.
const RENEWAL_WAIT: std::time::Duration = std::time::Duration::from_secs(5);

pub fn route(app: &AppHandle) {
    route_to(app, "/app");
}

/// Like `route`, but a signed-in session opens `path` on the server.
pub fn route_to(app: &AppHandle, path: &str) {
    let state = app.state::<AppState>();
    let epoch = state.epoch();
    let Ok(server) = state.server() else {
        let _ = open_onboarding(app);
        return;
    };
    let Some(token) = state.token(&server) else {
        // A keyring that could not be read (locked, cancelled unlock) is
        // not signed out: say so, and let the user try again.
        match state.read_failure(&server) {
            Some(error) => open_failed(app, "Could not read your session", &error),
            None => show_sign_in(app),
        }
        return;
    };
    let app = app.clone();
    let path = path.to_string();
    tauri::async_runtime::spawn(async move {
        let state = app.state::<AppState>();
        match state.api.session_valid(&server, &token).await {
            Ok(true) => {
                // Renewed before the window opens: the web UI reads the
                // session's expiry when it loads, and a page that sees the
                // old expiry pass signs the session out on the server.
                let renewal = tokio::time::timeout(
                    RENEWAL_WAIT,
                    main_window::renew_session(&app, &server, &token),
                )
                .await;
                // `None` is also a renewal that lost to another one, which
                // stored a newer token: the session is still on.
                let renewed = renewal.is_ok();
                // A sign-out or server change during the wait wins.
                if state.epoch() != epoch || state.server().ok().as_deref() != Some(&server) {
                    return;
                }
                // The stored token, read now: another renewal may have
                // replaced it, or a rejection cleared it.
                let Some(token) = state.token(&server) else {
                    return;
                };
                if let Err(e) = main_window::open(&app, &server, &token, &path).await {
                    log::warn!("could not open main window: {e}");
                    match state.api.health(&server).await {
                        Err(reason) => show_offline(&app, &server, &path, reason, epoch),
                        Ok(()) => open_failed(&app, "Could not open Onyx", &e),
                    }
                }
                // A slow renewal does not delay the window; it finishes
                // here, and the renewed token reaches the window.
                if !renewed {
                    main_window::renew_session(&app, &server, &token).await;
                }
            }
            Ok(false) => end_rejected_session(&app, &server, &token),
            // Unreachable is not signed out: the session is kept, and
            // Sign in is only for a rejected session or the user's choice.
            Err(reason) => show_offline(&app, &server, &path, reason, epoch),
        }
    });
}

/// Ends a session the server no longer accepts and shows the sign-in window,
/// unless a sign-in that finished meanwhile replaced `token`.
pub fn end_rejected_session(app: &AppHandle, server: &str, token: &str) {
    let state = app.state::<AppState>();
    if matches!(state.clear_rejected_token(server, token), Ok(false)) {
        return;
    }
    // The rejected account's answers and pages (a main window kept hidden
    // during an outage) must not reach the next one.
    reset_launcher(app);
    main_window::close(app, server);
    let _ = open_login(app);
}

/// The offline window, or the "Try Again / Sign In" dialog if it cannot open.
pub(crate) fn show_offline(
    app: &AppHandle,
    server: &str,
    path: &str,
    reason: Unreachable,
    epoch: u64,
) {
    if let Err(e) = crate::offline::show(app, path, reason, epoch) {
        log::warn!("showing the dialog instead of the offline window: {e}");
        open_failed(app, "Could not open Onyx", &reason.message(server));
    }
}

/// Dock click, tray "Open Onyx" and second launches.
/// The windows that `show_primary` brings forward, first match wins. The main
/// window is hidden while the offline window shows. Off macOS, the web sign-in
/// window stands in for the login window, which it hides.
#[cfg(target_os = "macos")]
const PRIMARY: [&str; 4] = [OFFLINE, main_window::LABEL, ONBOARDING, LOGIN];
#[cfg(not(target_os = "macos"))]
const PRIMARY: [&str; 5] = [
    OFFLINE,
    main_window::LABEL,
    ONBOARDING,
    crate::sso::LABEL,
    LOGIN,
];

/// Brings the login window forward, or off macOS the web sign-in window that
/// hides it.
fn show_sign_in(app: &AppHandle) {
    #[cfg(not(target_os = "macos"))]
    if let Some(window) = app.get_webview_window(crate::sso::LABEL) {
        bring_forward(app, &window);
        return;
    }
    let _ = open_login(app);
}

pub fn show_primary(app: &AppHandle) {
    for label in PRIMARY {
        if let Some(window) = app.get_webview_window(label) {
            bring_forward(app, &window);
            return;
        }
    }
    route(app);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn content_that_fits_keeps_the_window_where_it_is() {
        let fit = fit_in_work_area((0, 0, 2560, 1920), 2.0, (1040, 400), 520.0, 400.0);
        assert_eq!(
            fit,
            Fit {
                height: 400.0,
                position: None
            }
        );
    }

    #[test]
    fn tall_content_on_a_small_screen_is_clamped_and_moved_on_screen() {
        // Preferences on a 1024x768 screen, centered at its first size.
        let fit = fit_in_work_area((0, 0, 1024, 768), 1.0, (232, 84), 560.0, 900.0);
        assert_eq!(fit.height, 768.0 - SCREEN_MARGIN);
        // The window and its title bar fit between the top and bottom edges.
        let (x, y) = fit.position.expect("moved");
        assert_eq!(x, 232);
        assert!(y >= 0 && f64::from(y) + fit.height + TITLE_BAR <= 768.0);
    }

    #[test]
    fn no_content_height_makes_a_window_larger_than_its_monitor() {
        for scale in [1.0, 1.25, 2.0] {
            let fit = fit_in_work_area((0, 0, 2560, 1440), scale, (0, 0), 920.0, 58_880.0);
            assert!((fit.height + TITLE_BAR) * scale <= 1440.0, "scale {scale}");
        }
    }

    #[test]
    fn a_window_past_the_bottom_edge_is_centered_vertically() {
        // A second monitor to the right, below a top panel.
        let fit = fit_in_work_area((1920, 32, 1920, 1048), 1.0, (2650, 900), 460.0, 300.0);
        assert_eq!(fit.position, Some((2650, 32 + 354)));
        // Off the left edge too: centered on both axes.
        let fit = fit_in_work_area((1920, 32, 1920, 1048), 1.0, (100, 900), 460.0, 300.0);
        assert_eq!(fit.position, Some((1920 + 730, 32 + 354)));
    }

    #[test]
    fn local_windows_keep_the_width_they_open_with() {
        for label in [ONBOARDING, LOGIN, PREFERENCES, OFFLINE] {
            assert!(initial_size(label).is_some(), "{label}");
        }
        assert_eq!(initial_size(LAUNCHER), None);
    }

    #[cfg(not(target_os = "macos"))]
    #[test]
    fn reopening_shows_the_web_sign_in_window_before_login() {
        let position = |label: &str| PRIMARY.iter().position(|l| *l == label);
        let web = position(crate::sso::LABEL).expect("the web sign-in window is primary");
        let login = position(LOGIN).expect("login is primary");
        assert!(web < login);
    }
}
