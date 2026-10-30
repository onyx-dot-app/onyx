use crate::config::ConfigState;
use crate::debug_log::{log_backend_error, maybe_open_devtools};
use std::process::Command;
#[cfg(target_os = "macos")]
use std::time::Duration;
use tauri::webview::{DownloadEvent, NewWindowFeatures, NewWindowResponse};
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
        .on_new_window(move |url, features| handle_new_window(&handle, &url, features));
    let builder = with_shared_webview_handlers(builder);

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
        crate::macos_webview::install_ui_delegate_extensions(&window);
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

/// Where a `window.open` / `target="_blank"` request should go.
#[derive(Debug, PartialEq, Eq)]
enum NewWindowTarget {
    /// An in-app window that shares the opener's session, keeps
    /// `window.opener`, and can `postMessage` back -- what OAuth flows need.
    InApp,
    ExternalBrowser,
    Deny,
}

/// Script-built popups (a blank window navigated later, an app page, or any
/// window opened with size features) stay in the app so their session and
/// opener survive; plain cross-origin links go to the user's browser.
fn classify_new_window(
    app_url: Option<&Url>,
    url: &Url,
    has_popup_features: bool,
) -> NewWindowTarget {
    if url.as_str() == "about:blank" {
        return NewWindowTarget::InApp;
    }
    if matches!(url.scheme(), "http" | "https")
        && (has_popup_features || app_url.is_some_and(|app_url| same_origin(app_url, url)))
    {
        return NewWindowTarget::InApp;
    }
    if is_externally_openable(url) {
        NewWindowTarget::ExternalBrowser
    } else {
        NewWindowTarget::Deny
    }
}

fn app_url(app: &AppHandle) -> Option<Url> {
    let config_state = app.state::<ConfigState>();
    config_state
        .app_base_url()
        .or_else(|| config_state.config().server_url.parse().ok())
}

fn handle_new_window(
    app: &AppHandle,
    url: &Url,
    features: NewWindowFeatures,
) -> NewWindowResponse<Wry> {
    let target = classify_new_window(app_url(app).as_ref(), url, features.size().is_some());
    match target {
        NewWindowTarget::InApp => match build_popup_window(app, features) {
            Ok(window) => NewWindowResponse::Create { window },
            Err(e) => {
                log_backend_error(app, &format!("Failed to open popup window: {e}"));
                NewWindowResponse::Deny
            }
        },
        NewWindowTarget::ExternalBrowser => {
            if !open_in_default_browser(url.as_str()) {
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
        NewWindowTarget::Deny => NewWindowResponse::Deny,
    }
}

const POPUP_DEFAULT_SIZE: (f64, f64) = (650.0, 760.0);

/// The platform webview loads the requested URL into the returned window
/// itself, so the window starts blank and must reuse the opener's webview
/// configuration (`window_features`) to share its cookies and `window.opener`.
fn build_popup_window(
    app: &AppHandle,
    features: NewWindowFeatures,
) -> Result<WebviewWindow, String> {
    let label = format!("onyx-popup-{}", uuid::Uuid::new_v4());
    let blank = "about:blank"
        .parse()
        .map_err(|e| format!("Invalid popup URL: {e}"))?;
    let (width, height) = features
        .size()
        .map_or(POPUP_DEFAULT_SIZE, |size| (size.width, size.height));

    let handle = app.clone();
    let builder = WebviewWindowBuilder::new(app, &label, WebviewUrl::External(blank))
        .title(app.state::<ConfigState>().config().window_title)
        .inner_size(width, height)
        .window_features(features)
        .on_document_title_changed(|window, title| {
            let _ = window.set_title(&title);
        })
        .on_new_window(move |url, features| handle_new_window(&handle, &url, features));

    let window = with_shared_webview_handlers(builder)
        .build()
        .map_err(|e| e.to_string())?;
    #[cfg(target_os = "macos")]
    crate::macos_webview::install_ui_delegate_extensions(&window);
    maybe_open_devtools(app, &window);
    Ok(window)
}

/// Behaviour every Onyx webview needs, whichever path built it.
fn with_shared_webview_handlers(
    builder: WebviewWindowBuilder<'_, Wry, AppHandle>,
) -> WebviewWindowBuilder<'_, Wry, AppHandle> {
    builder
        // Tauri's own drag-and-drop handler swallows file drops, so the web
        // app's upload drop zones never receive them.
        .disable_drag_drop_handler()
        // Without a download handler `WKWebView` cancels every download.
        // Returning `true` keeps the platform's default destination
        // (the Downloads folder, with a numbered name on collision).
        .on_download(|webview, event| {
            if let DownloadEvent::Finished {
                url,
                success: false,
                ..
            } = &event
            {
                log_backend_error(
                    webview.app_handle(),
                    &format!("Download failed: {}", redact_url(url)),
                );
            }
            true
        })
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
    let builder = WebviewWindowBuilder::from_config(app, &window_config)
        .map_err(|e| e.to_string())?
        .on_new_window(move |url, features| handle_new_window(&handle, &url, features));
    let window = with_shared_webview_handlers(builder)
        .build()
        .map_err(|e| e.to_string())?;
    #[cfg(target_os = "macos")]
    crate::macos_webview::install_ui_delegate_extensions(&window);
    Ok(window)
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

    #[test]
    fn classify_new_window_keeps_script_popups_in_app() {
        let app = url("https://cloud.onyx.app/app");
        let classify = |target: &str, popup| classify_new_window(Some(&app), &url(target), popup);

        assert_eq!(classify("about:blank", false), NewWindowTarget::InApp);
        assert_eq!(
            classify("https://cloud.onyx.app/admin/connectors", false),
            NewWindowTarget::InApp
        );
        assert_eq!(
            classify("https://accounts.google.com/o/oauth2/auth", true),
            NewWindowTarget::InApp
        );
        assert_eq!(
            classify("https://docs.onyx.app", false),
            NewWindowTarget::ExternalBrowser
        );
        assert_eq!(
            classify("mailto:support@onyx.app", true),
            NewWindowTarget::ExternalBrowser
        );
        assert_eq!(classify("file:///etc/passwd", true), NewWindowTarget::Deny);
        assert_eq!(classify("about:srcdoc", false), NewWindowTarget::Deny);
        assert_eq!(
            classify_new_window(None, &url("https://cloud.onyx.app/app"), false),
            NewWindowTarget::ExternalBrowser
        );
    }
}
