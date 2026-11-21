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

pub fn open_onboarding(app: &AppHandle) -> Result<WebviewWindow, String> {
    local_window(
        app,
        ONBOARDING,
        "onboarding.html",
        "Welcome to Onyx",
        (520.0, 400.0),
    )
}

pub fn open_login(app: &AppHandle) -> Result<WebviewWindow, String> {
    local_window(app, LOGIN, "login.html", "Sign in to Onyx", (460.0, 520.0))
}

pub fn open_preferences(app: &AppHandle) -> Result<WebviewWindow, String> {
    local_window(
        app,
        PREFERENCES,
        "preferences.html",
        "Preferences",
        (560.0, 600.0),
    )
}

pub fn open_offline(app: &AppHandle) -> Result<WebviewWindow, String> {
    local_window(app, OFFLINE, "offline.html", "Onyx", (460.0, 300.0))
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
        let _ = open_login(app);
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
pub fn show_primary(app: &AppHandle) {
    // The main window is hidden while the offline window shows.
    for label in [OFFLINE, main_window::LABEL, ONBOARDING, LOGIN] {
        if let Some(window) = app.get_webview_window(label) {
            bring_forward(app, &window);
            return;
        }
    }
    route(app);
}
