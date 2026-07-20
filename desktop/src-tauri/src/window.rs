use crate::config::ConfigState;
use crate::debug_log::{log_backend_error, maybe_open_devtools};
use std::process::Command;
#[cfg(target_os = "macos")]
use std::time::Duration;
use tauri::{AppHandle, Manager, Webview, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
#[cfg(target_os = "macos")]
use tokio::time::sleep;
use url::Url;
#[cfg(target_os = "macos")]
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};

#[cfg(target_os = "macos")]
const TITLEBAR_SCRIPT: &str = include_str!("../../src/titlebar.js");
const CHAT_LINK_INTERCEPT_SCRIPT: &str = include_str!("scripts/chat_link_intercept.js");

pub fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if let Err(e) = window.unminimize() {
            log_backend_error(app, &format!("Failed to unminimize main window: {e}"));
        }
        if let Err(e) = window.show() {
            log_backend_error(app, &format!("Failed to show main window: {e}"));
        }
        if let Err(e) = window.set_focus() {
            log_backend_error(app, &format!("Failed to focus main window: {e}"));
        }
    } else {
        trigger_new_window(app);
    }
}

pub fn trigger_new_chat(app: &AppHandle) {
    let server_url = app.state::<ConfigState>().config().server_url;

    if let Some(window) = app.get_webview_window("main") {
        let url = format!("{}/chat", server_url);
        if let Err(e) = window.eval(&format!("window.location.href = '{}'", url)) {
            log_backend_error(app, &format!("Failed to navigate to new chat: {e}"));
        }
    }
}

/// Build a new Onyx window (title, size, platform-specific transparency /
/// titlebar / background-color quirks, vibrancy, the Alt-menu toggle, and
/// devtools) and apply current settings to it. The single source of truth
/// for window creation -- previously duplicated between the menu/tray
/// "New Window" path and the `new_window` command, which had already drifted
/// once (the Windows transparency fix had to be hand-applied to both).
pub fn build_and_setup_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    let config = app.state::<ConfigState>().config();
    let window_label = format!("onyx-{}", uuid::Uuid::new_v4());
    let url = config
        .server_url
        .parse()
        .map_err(|e| format!("Invalid server URL: {e}"))?;

    let builder = WebviewWindowBuilder::new(app, &window_label, WebviewUrl::External(url))
        .title(config.window_title)
        .inner_size(1232.0, 800.0)
        .min_inner_size(800.0, 600.0);

    // Windows draws its own title bar in the system theme; a transparent
    // window leaves any unpainted region see-through, which produces the
    // translucent-bar artifact reported on Windows.
    #[cfg(not(target_os = "windows"))]
    let builder = builder.transparent(true);

    #[cfg(target_os = "macos")]
    let builder = builder
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true);

    #[cfg(target_os = "linux")]
    let builder = builder.background_color(tauri::window::Color(0x1a, 0x1a, 0x2e, 0xff));

    let window = builder.build().map_err(|e| e.to_string())?;

    #[cfg(target_os = "macos")]
    {
        if let Err(e) = apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None) {
            log_backend_error(app, &format!("Failed to apply vibrancy effect: {e}"));
        }
        inject_titlebar(window.clone());
    }

    apply_settings_to_window(app, &window);

    #[cfg(target_os = "linux")]
    crate::alt_menu::setup_alt_menu_toggle(app, &window);

    maybe_open_devtools(app, &window);

    if let Err(e) = window.set_focus() {
        log_backend_error(app, &format!("Failed to focus new window: {e}"));
    }

    Ok(window)
}

/// Fire-and-forget "New Window" entry point for the menu/tray, where there's
/// no caller waiting on a `Result`.
pub fn trigger_new_window(app: &AppHandle) {
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(e) = build_and_setup_window(&handle) {
            log_backend_error(&handle, &format!("Failed to open new window: {e}"));
        }
    });
}

pub fn open_docs(app: &AppHandle) {
    if !open_in_default_browser("https://docs.onyx.app") {
        log_backend_error(app, "Failed to open docs in default browser");
    }
}

pub fn open_settings(app: &AppHandle) {
    // Navigate main window to the settings page (index.html) with settings flag
    let settings_url = app
        .state::<ConfigState>()
        .app_base_url()
        .and_then(|mut url| {
            url.set_query(None);
            url.set_fragment(Some("settings"));
            url.set_path("/");
            Some(url)
        })
        .or_else(|| Url::parse("tauri://localhost/#settings").ok());

    if let Some(window) = app.get_webview_window("main") {
        if let Some(url) = settings_url {
            if let Err(e) = window.navigate(url) {
                log_backend_error(app, &format!("Failed to navigate to settings: {e}"));
            }
        }
    }
}

pub fn same_origin(left: &Url, right: &Url) -> bool {
    left.scheme() == right.scheme()
        && left.host_str() == right.host_str()
        && left.port_or_known_default() == right.port_or_known_default()
}

pub fn is_chat_session_url(url: &Url) -> bool {
    url.path().starts_with("/app") && url.query_pairs().any(|(key, _)| key == "chatId")
}

pub fn should_open_in_external_browser(current_url: &Url, destination_url: &Url) -> bool {
    if !is_chat_session_url(current_url) {
        return false;
    }

    match destination_url.scheme() {
        "mailto" | "tel" => true,
        "http" | "https" => !same_origin(current_url, destination_url),
        _ => false,
    }
}

pub fn open_in_default_browser(url: &str) -> bool {
    #[cfg(target_os = "macos")]
    {
        return Command::new("open").arg(url).status().is_ok();
    }
    #[cfg(target_os = "linux")]
    {
        return Command::new("xdg-open").arg(url).status().is_ok();
    }
    #[cfg(target_os = "windows")]
    {
        return Command::new("rundll32")
            .arg("url.dll,FileProtocolHandler")
            .arg(url)
            .status()
            .is_ok();
    }
    #[allow(unreachable_code)]
    false
}

pub fn inject_chat_link_intercept(webview: &Webview) {
    if let Err(e) = webview.eval(CHAT_LINK_INTERCEPT_SCRIPT) {
        log_backend_error(
            webview.app_handle(),
            &format!("Failed to inject chat-link-intercept script: {e}"),
        );
    }
}

/// One-off titlebar re-injection on every page load, distinct from
/// `inject_titlebar`'s setup-time retry loop, which only covers the initial
/// load and would otherwise miss later in-app navigations.
#[cfg(target_os = "macos")]
pub fn eval_titlebar_script(webview: &Webview) {
    if let Err(e) = webview.eval(TITLEBAR_SCRIPT) {
        log_backend_error(
            webview.app_handle(),
            &format!("Failed to inject titlebar script: {e}"),
        );
    }
}

#[cfg(target_os = "macos")]
pub fn inject_titlebar(window: WebviewWindow) {
    let script = TITLEBAR_SCRIPT.to_string();
    tauri::async_runtime::spawn(async move {
        // Keep trying for a few seconds to survive navigations and slow
        // loads. Most early attempts are expected to fail (the page hasn't
        // loaded yet), so failures here aren't logged.
        let delays = [0u64, 200, 600, 1200, 2000, 4000, 6000, 8000, 10000];
        for delay in delays {
            if delay > 0 {
                sleep(Duration::from_millis(delay)).await;
            }
            let _ = window.eval(&script);
        }
    });
}

pub fn apply_settings_to_window(app: &AppHandle, window: &WebviewWindow) {
    let config = app.state::<ConfigState>().config();

    if let Err(e) = window.set_title(&config.window_title) {
        log_backend_error(app, &format!("Failed to set window title: {e}"));
    }

    // Menu-bar visibility and window decorations are only configurable off macOS.
    if cfg!(target_os = "macos") {
        return;
    }
    if !config.show_menu_bar {
        if let Err(e) = window.hide_menu() {
            log_backend_error(app, &format!("Failed to hide menu bar: {e}"));
        }
    }
    #[cfg(target_os = "linux")]
    if config.hide_window_decorations {
        if let Err(e) = window.set_decorations(false) {
            log_backend_error(app, &format!("Failed to hide window decorations: {e}"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    #[test]
    fn same_origin_matches_scheme_host_and_port() {
        assert!(same_origin(
            &url("https://cloud.onyx.app/app"),
            &url("https://cloud.onyx.app/other")
        ));
        assert!(!same_origin(
            &url("https://cloud.onyx.app"),
            &url("http://cloud.onyx.app")
        ));
        assert!(!same_origin(
            &url("https://cloud.onyx.app"),
            &url("https://example.com")
        ));
        assert!(!same_origin(
            &url("https://cloud.onyx.app:8443"),
            &url("https://cloud.onyx.app")
        ));
    }

    #[test]
    fn is_chat_session_url_requires_app_path_and_chat_id() {
        assert!(is_chat_session_url(&url(
            "https://cloud.onyx.app/app?chatId=123"
        )));
        assert!(!is_chat_session_url(&url("https://cloud.onyx.app/app")));
        assert!(!is_chat_session_url(&url(
            "https://cloud.onyx.app/settings?chatId=123"
        )));
    }

    #[test]
    fn should_open_in_external_browser_only_from_chat_session() {
        let chat = url("https://cloud.onyx.app/app?chatId=123");
        let settings = url("https://cloud.onyx.app/settings");

        assert!(should_open_in_external_browser(
            &chat,
            &url("https://example.com")
        ));
        assert!(should_open_in_external_browser(
            &chat,
            &url("mailto:a@b.com")
        ));
        assert!(should_open_in_external_browser(&chat, &url("tel:12345")));
        assert!(!should_open_in_external_browser(
            &chat,
            &url("https://cloud.onyx.app/app?chatId=456")
        ));
        assert!(!should_open_in_external_browser(
            &settings,
            &url("https://example.com")
        ));
        assert!(!should_open_in_external_browser(
            &chat,
            &url("ftp://example.com")
        ));
    }
}
