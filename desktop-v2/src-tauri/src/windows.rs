//! Local (bundled) windows: onboarding, login and preferences.

use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use url::Url;

use crate::main_window;
use crate::state::AppState;

pub const ONBOARDING: &str = "onboarding";
pub const LOGIN: &str = "login";
pub const PREFERENCES: &str = "preferences";

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
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(window);
    }
    let nav_app = app.clone();
    let builder = WebviewWindowBuilder::new(app, label, WebviewUrl::App(page.into()))
        .title(title)
        .inner_size(size.0, size.1)
        .resizable(false)
        .center()
        .focused(true)
        .on_navigation(move |url| local_navigation_allowed(&nav_app, url))
        .on_new_window(local_new_window(app));
    #[cfg(target_os = "macos")]
    let builder = builder
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true);
    builder.build().map_err(|e| e.to_string())
}

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

pub fn close(app: &AppHandle, label: &str) {
    if let Some(window) = app.get_webview_window(label) {
        let _ = window.destroy();
    }
}

/// Opens whichever window the current state needs: onboarding, login or the main window.
pub fn route(app: &AppHandle) {
    let state = app.state::<AppState>();
    let Ok(server) = state.server() else {
        let _ = open_onboarding(app);
        return;
    };
    let Some(token) = state.token(&server) else {
        let _ = open_login(app);
        return;
    };
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let state = app.state::<AppState>();
        match state.api.session_valid(&server, &token).await {
            Ok(true) => {
                if let Err(e) = main_window::open(&app, &server, &token, "/app").await {
                    log::warn!("could not open main window: {e}");
                }
            }
            Ok(false) => {
                let _ = state.clear_token(&server);
                let _ = open_login(&app);
            }
            Err(e) => {
                log::warn!("server check failed: {e}");
                let _ = open_login(&app);
            }
        }
    });
}

/// Dock click, tray "Open Onyx" and second launches.
pub fn show_primary(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(main_window::LABEL) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
        return;
    }
    for label in [ONBOARDING, LOGIN] {
        if let Some(window) = app.get_webview_window(label) {
            let _ = window.show();
            let _ = window.set_focus();
            return;
        }
    }
    route(app);
}
