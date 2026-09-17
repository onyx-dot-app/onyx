use crate::config::ConfigState;
use crate::debug_log::{log_backend_error, maybe_open_devtools};
use std::process::Command;
#[cfg(target_os = "macos")]
use std::time::Duration;
use tauri::webview::{NewWindowFeatures, NewWindowResponse};
#[cfg(target_os = "macos")]
use tauri::Webview;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, Wry};
#[cfg(target_os = "macos")]
use tokio::time::sleep;
use url::Url;
#[cfg(target_os = "macos")]
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};

#[cfg(target_os = "macos")]
const TITLEBAR_SCRIPT: &str = include_str!("../../src/titlebar.js");

/// The window a shortcut or menu action should apply to: whichever one is
/// focused (the app can have several windows). Focus-query failures are
/// logged and treated as unfocused.
pub fn focused_webview_window(app: &AppHandle) -> Option<WebviewWindow> {
    app.webview_windows().into_values().find(|window| {
        window.is_focused().unwrap_or_else(|e| {
            log_backend_error(app, &format!("Failed to query window focus: {e}"));
            false
        })
    })
}

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
        let url = format!("{server_url}/chat");
        if let Err(e) = window.eval(format!("window.location.href = '{url}'")) {
            log_backend_error(app, &format!("Failed to navigate to new chat: {e}"));
        }
    }
}

/// Focus the main window and navigate it to `/chat`, building it first if it
/// doesn't exist. Building and navigating must happen in the same task --
/// doing them as the two independent fire-and-forget steps `focus_main_window`
/// / `trigger_new_chat` normally are lets the navigation run against a window
/// that hasn't finished being created yet, silently dropping it.
pub fn open_chat_window(app: &AppHandle) {
    if app.get_webview_window("main").is_some() {
        focus_main_window(app);
        trigger_new_chat(app);
        return;
    }

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        match build_and_setup_window(&handle) {
            Ok(window) => {
                let server_url = handle.state::<ConfigState>().config().server_url;
                let url = format!("{server_url}/chat");
                if let Err(e) = window.eval(format!("window.location.href = '{url}'")) {
                    log_backend_error(&handle, &format!("Failed to navigate to new chat: {e}"));
                }
            }
            Err(e) => {
                log_backend_error(&handle, &format!("Failed to open new window: {e}"));
            }
        }
    });
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

    let handle = app.clone();
    let builder = WebviewWindowBuilder::new(app, &window_label, WebviewUrl::External(url))
        .title(config.window_title)
        .inner_size(1232.0, 800.0)
        .min_inner_size(800.0, 600.0)
        .on_new_window(move |url, _features: NewWindowFeatures| {
            open_new_window_externally(&handle, &url)
        });

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
        .map(|mut url| {
            url.set_query(None);
            url.set_fragment(Some("settings"));
            url.set_path("/");
            url
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

/// `is_ok` only says the opener ran; a non-zero exit still means the URL never
/// reached a browser, so callers need `success()` to report that truthfully.
fn spawned_opener_succeeded(mut command: Command) -> bool {
    command.status().is_ok_and(|status| status.success())
}

pub fn open_in_default_browser(url: &str) -> bool {
    #[cfg(target_os = "macos")]
    {
        let mut command = Command::new("open");
        command.arg(url);
        return spawned_opener_succeeded(command);
    }
    #[cfg(target_os = "linux")]
    {
        let mut command = Command::new("xdg-open");
        command.arg(url);
        return spawned_opener_succeeded(command);
    }
    #[cfg(target_os = "windows")]
    {
        let mut command = Command::new("rundll32");
        command.arg("url.dll,FileProtocolHandler").arg(url);
        return spawned_opener_succeeded(command);
    }
    #[allow(unreachable_code)]
    false
}

/// Schemes we hand to the OS opener. The URL comes from web content, so
/// anything outside this list (`file:`, custom app schemes) must not reach it.
pub fn is_externally_openable(url: &Url) -> bool {
    matches!(url.scheme(), "http" | "https" | "mailto" | "tel")
}

/// Enough of a URL to identify it in a log, without the path, query or
/// userinfo -- those are web-controlled and routinely carry signed tokens.
pub fn redact_url(url: &Url) -> String {
    url.host_str().map_or_else(
        || url.scheme().to_string(),
        |host| format!("{}://{host}", url.scheme()),
    )
}

/// Send every popup request -- `window.open` and `target="_blank"` alike -- to
/// the user's browser and refuse the popup itself.
///
/// Without a handler the platform webview drops these requests on the floor,
/// which is what made `window.open` links dead in the app: `WKWebView` returns
/// no webview and `WebView2` marks the request handled with nothing to show,
/// so the click does nothing at all.
fn open_new_window_externally(app: &AppHandle, url: &Url) -> NewWindowResponse<Wry> {
    if is_externally_openable(url) && !open_in_default_browser(url.as_str()) {
        log_backend_error(
            app,
            &format!(
                "Failed to open external URL in default browser: {}",
                redact_url(url)
            ),
        );
    }

    NewWindowResponse::Deny
}

/// Build the main window. It is declared in `tauri.conf.json` with
/// `"create": false` so it can be built here instead: `on_new_window` is only
/// reachable through the builder, and the main window needs it as much as the
/// windows `build_and_setup_window` creates.
pub fn build_main_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    let window_config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == "main")
        .cloned()
        .ok_or_else(|| "No \"main\" window in the Tauri config".to_string())?;

    let handle = app.clone();
    WebviewWindowBuilder::from_config(app, &window_config)
        .map_err(|e| e.to_string())?
        .on_new_window(move |url, _features: NewWindowFeatures| {
            open_new_window_externally(&handle, &url)
        })
        .build()
        .map_err(|e| e.to_string())
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

    #[allow(clippy::unwrap_used)]
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
    fn is_externally_openable_allows_only_web_and_contact_schemes() {
        assert!(is_externally_openable(&url("https://example.com")));
        assert!(is_externally_openable(&url("http://example.com")));
        assert!(is_externally_openable(&url("mailto:a@b.com")));
        assert!(is_externally_openable(&url("tel:12345")));
        // Web content picks these URLs, so the OS opener must not see schemes
        // that would launch an arbitrary local handler.
        assert!(!is_externally_openable(&url("file:///etc/passwd")));
        assert!(!is_externally_openable(&url("ftp://example.com")));
        assert!(!is_externally_openable(&url("javascript:alert(1)")));
    }

    #[test]
    fn redact_url_drops_path_query_and_userinfo() {
        assert_eq!(
            redact_url(&url("https://example.com/doc?token=secret#frag")),
            "https://example.com"
        );
        assert_eq!(
            redact_url(&url("https://user:pw@example.com/a")),
            "https://example.com"
        );
        // Hostless schemes keep only the scheme.
        assert_eq!(redact_url(&url("mailto:someone@example.com")), "mailto");
        assert_eq!(redact_url(&url("tel:12345")), "tel");
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
