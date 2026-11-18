//! The main window renders the server's own web UI. It gets no IPC; the shell only
//! hands in the session cookie and decides where links, popups and downloads go.

use std::sync::atomic::{AtomicUsize, Ordering};

use tauri::webview::cookie::{Cookie, SameSite};
use tauri::webview::{DownloadEvent, NewWindowFeatures, NewWindowResponse};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;
use url::Url;

use crate::state::AppState;

pub const LABEL: &str = "main";
static POPUP_COUNTER: AtomicUsize = AtomicUsize::new(0);
const DESKTOP_CHROME_JS: &str = include_str!("desktop_chrome.js");
const LINK_SHIM_JS: &str = include_str!("link_shim.js");

/// Tells the page script the current zoom and full-screen state, so the
/// traffic-light row keeps its size in screen points (see desktop_chrome.js).
pub fn sync_chrome(app: &AppHandle) {
    let Some(window) = app.get_webview_window(LABEL) else {
        return;
    };
    let zoom = app.state::<AppState>().config.get().zoom();
    let fullscreen = window.is_fullscreen().unwrap_or_else(|e| {
        log::warn!("could not read the full-screen state: {e}");
        false
    });
    if let Err(e) = window.eval(format!(
        "window.__onyxDesktop && window.__onyxDesktop.sync({zoom}, {fullscreen});"
    )) {
        log::warn!("could not update the window chrome: {e}");
    }
}

/// The overlay title bar has no native drag area, so the page's drag strip uses
/// Tauri's built-in drag handler. Only window dragging and title-bar zoom are
/// granted, only to the main window, only on the configured server's origin;
/// every app command stays out of reach.
fn allow_window_dragging(app: &AppHandle, origin: &str) {
    let capability = tauri::ipc::CapabilityBuilder::new(format!("main-window-drag-{origin}"))
        .window(LABEL)
        .local(false)
        .remote(format!("{origin}/*"))
        .permission("core:window:allow-start-dragging")
        .permission("core:window:allow-internal-toggle-maximize");
    if let Err(e) = app.add_capability(capability) {
        log::debug!("drag capability already present: {e}");
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum LinkAction {
    Allow,
    External,
    Block,
}

pub fn classify(url: &Url, server_origin: &str) -> LinkAction {
    match url.scheme() {
        "about" | "blob" | "data" => LinkAction::Allow,
        "http" | "https" if url.origin().ascii_serialization() == server_origin => {
            LinkAction::Allow
        }
        "http" | "https" | "mailto" | "tel" => LinkAction::External,
        _ => LinkAction::Block,
    }
}

/// The web app opens popups for OAuth consent (connectors, MCP): it opens a
/// same-origin `about:blank` popup and then sends it to the provider. So a
/// popup, unlike the main window, may load other HTTPS sites; its title shows
/// the site's host so it is never mistaken for Onyx. Plain HTTP and other
/// schemes follow the main window's rules.
fn popup_navigation_allowed(app: &AppHandle, label: &str, url: &Url, server_origin: &str) -> bool {
    match classify(url, server_origin) {
        LinkAction::Allow => true,
        LinkAction::External if url.scheme() == "https" => true,
        LinkAction::External => {
            open_external(app, url.as_str());
            close_if_blank(app, label);
            false
        }
        LinkAction::Block => false,
    }
}

/// Closes a popup that never showed a page (it went straight to a link that
/// opened in the browser), so no empty window stays behind.
fn close_if_blank(app: &AppHandle, label: &str) {
    let blank = app
        .get_webview_window(label)
        .and_then(|w| w.url().ok())
        .is_none_or(|url| url.as_str() == "about:blank");
    if !blank {
        return;
    }
    let app = app.clone();
    let label = label.to_string();
    // Not from inside the navigation callback of the window being closed.
    tauri::async_runtime::spawn(async move {
        let handle = app.clone();
        let _ = app.run_on_main_thread(move || {
            if let Some(window) = handle.get_webview_window(&label) {
                let _ = window.destroy();
            }
        });
    });
}

/// Handles `window.open` and `target="_blank"` from the main window or a
/// popup: a server page opens in a popup that follows the same rules (its own
/// popups, downloads), other web pages open in the browser.
fn open_new_window(
    app: &AppHandle,
    url: Url,
    features: NewWindowFeatures,
    origin: &str,
) -> NewWindowResponse<tauri::Wry> {
    match classify(&url, origin) {
        LinkAction::Allow => {
            let label = format!("popup-{}", POPUP_COUNTER.fetch_add(1, Ordering::Relaxed));
            let blank = WebviewUrl::External("about:blank".parse().expect("valid url"));
            let nav_app = app.clone();
            let nav_origin = origin.to_string();
            let nav_label = label.clone();
            let child_app = app.clone();
            let child_origin = origin.to_string();
            match WebviewWindowBuilder::new(app, label, blank)
                .title("Onyx")
                .window_features(features)
                .initialization_script(LINK_SHIM_JS)
                .on_navigation(move |url| {
                    popup_navigation_allowed(&nav_app, &nav_label, url, &nav_origin)
                })
                .on_new_window(move |url, features| {
                    open_new_window(&child_app, url, features, &child_origin)
                })
                .on_download(|_webview, event| handle_download(event))
                .on_page_load(|window, payload| {
                    if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
                        let _ = window.set_title(&popup_title(payload.url()));
                    }
                })
                .build()
            {
                Ok(window) => NewWindowResponse::Create { window },
                Err(e) => {
                    log::warn!("could not open popup: {e}");
                    NewWindowResponse::Deny
                }
            }
        }
        LinkAction::External => {
            open_external(app, url.as_str());
            NewWindowResponse::Deny
        }
        LinkAction::Block => NewWindowResponse::Deny,
    }
}

/// Downloads from any app window ask where to save, like a browser.
fn handle_download(event: DownloadEvent) -> bool {
    match event {
        DownloadEvent::Requested { destination, .. } => choose_download_path(destination),
        DownloadEvent::Finished { url, success, .. } => {
            log::info!("download of {url} finished (success: {success})");
            true
        }
        _ => true,
    }
}

fn popup_title(url: &Url) -> String {
    match url.host_str() {
        Some(host) => format!("Onyx — {host}"),
        None => "Onyx".to_string(),
    }
}

pub fn open_external(app: &AppHandle, url: &str) {
    if let Err(e) = app.opener().open_url(url, None::<&str>) {
        log::warn!("could not open {url}: {e}");
    }
}

fn session_cookie(server: &Url, name: &str, token: &str) -> Result<Cookie<'static>, String> {
    let host = server
        .host_str()
        .ok_or_else(|| "server URL has no host".to_string())?
        .to_string();
    let mut cookie = Cookie::build((name.to_string(), token.to_string()))
        .domain(host)
        .path("/")
        .http_only(true)
        .same_site(SameSite::Lax);
    // wry writes `Secure=FALSE` for `secure(false)`, which WebKit reads as secure.
    if server.scheme() == "https" {
        cookie = cookie.secure(true);
    }
    Ok(cookie.build())
}

fn choose_download_path(destination: &mut std::path::PathBuf) -> bool {
    let suggested = destination
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "download".into());
    let mut dialog = rfd::FileDialog::new().set_file_name(&suggested);
    if let Some(dir) = destination.parent() {
        dialog = dialog.set_directory(dir);
    }
    match dialog.save_file() {
        Some(path) => {
            *destination = path;
            true
        }
        None => false,
    }
}

fn hand_over_session(
    window: &tauri::WebviewWindow,
    server_url: &Url,
    name: &str,
    token: &str,
) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let result = crate::macos_cookies::set_session_cookie(window, server_url, name, token);
    #[cfg(not(target_os = "macos"))]
    let result = window
        .set_cookie(session_cookie(server_url, name, token)?)
        .map_err(|e| e.to_string());
    result.map_err(|e| format!("Could not hand the session to the window: {e}"))
}

/// Opens (or reuses) the main window logged in as `token`, at `path` on the server.
pub async fn open(app: &AppHandle, server: &str, token: &str, path: &str) -> Result<(), String> {
    let epoch = app.state::<AppState>().epoch();
    let server_url = Url::parse(server).map_err(|e| e.to_string())?;
    let target = server_url.join(path).map_err(|e| e.to_string())?;

    if let Some(window) = app.get_webview_window(LABEL) {
        window.navigate(target).map_err(|e| e.to_string())?;
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }

    let origin = server_url.origin().ascii_serialization();
    let nav_app = app.clone();
    let nav_origin = origin.clone();
    let popup_app = app.clone();
    let popup_origin = origin.clone();

    allow_window_dragging(app, &origin);

    let blank = WebviewUrl::External("about:blank".parse().map_err(|_| "bad url")?);
    let builder = WebviewWindowBuilder::new(app, LABEL, blank)
        .title("Onyx")
        .inner_size(1280.0, 840.0)
        .min_inner_size(800.0, 600.0)
        .center()
        .initialization_script(LINK_SHIM_JS)
        .initialization_script(DESKTOP_CHROME_JS)
        .on_page_load(|window, payload| {
            if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
                sync_chrome(window.app_handle());
            }
        })
        // Let the web page receive dropped files (chat attachments).
        .disable_drag_drop_handler()
        .on_navigation(move |url| match classify(url, &nav_origin) {
            LinkAction::Allow => true,
            LinkAction::External => {
                open_external(&nav_app, url.as_str());
                false
            }
            LinkAction::Block => false,
        })
        .on_new_window(move |url, features| {
            open_new_window(&popup_app, url, features, &popup_origin)
        })
        .on_download(|_webview, event| handle_download(event));

    // Overlay title bar: the traffic lights float over the web UI's sidebar.
    #[cfg(target_os = "macos")]
    let builder = builder
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true);

    let window = builder.build().map_err(|e| e.to_string())?;
    // Entering or leaving full screen resizes the window.
    let resize_app = app.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::Resized(_) = event {
            sync_chrome(&resize_app);
        }
    });

    #[cfg(target_os = "macos")]
    crate::macos_dialogs::install(&window);

    // A window that did not get the session must not stay open: the next
    // open() would reuse it without a session and show the web login page.
    let result = async {
        let cookie_name = app
            .state::<AppState>()
            .cookie_name(server)
            .await
            .map_err(|e| format!("Could not read the server's sign-in settings: {e}"))?;
        if app.state::<AppState>().epoch() != epoch {
            return Err("The session ended while Onyx was opening.".to_string());
        }
        hand_over_session(&window, &server_url, &cookie_name, token)?;
        if let Err(e) = window.set_zoom(app.state::<AppState>().config.get().zoom()) {
            log::warn!("could not apply the saved zoom: {e}");
        }
        window.navigate(target).map_err(|e| e.to_string())
    }
    .await;
    if let Err(e) = result {
        let _ = window.destroy();
        return Err(e);
    }
    let _ = window.set_focus();
    Ok(())
}

/// Removes the session cookie and closes the main window and its popups.
pub fn close(app: &AppHandle, server: &str) {
    let Some(window) = app.get_webview_window(LABEL) else {
        return;
    };
    if let Ok(server_url) = Url::parse(server) {
        let name = app.state::<AppState>().cached_cookie_name(server);
        #[cfg(target_os = "macos")]
        let _ = crate::macos_cookies::clear_session_cookie(&window, &server_url, &name);
        if let Ok(cookie) = session_cookie(&server_url, &name, "") {
            let _ = window.delete_cookie(cookie);
        }
    }
    let _ = window.destroy();
    for (label, other) in app.webview_windows() {
        if label.starts_with("popup-") {
            let _ = other.destroy();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{classify, LinkAction};
    use url::Url;

    const ORIGIN: &str = "http://localhost:3000";

    fn action(url: &str) -> LinkAction {
        classify(&Url::parse(url).unwrap(), ORIGIN)
    }

    #[test]
    fn same_origin_stays_in_app() {
        assert_eq!(
            action("http://localhost:3000/app?chatId=1"),
            LinkAction::Allow
        );
        assert_eq!(action("about:blank"), LinkAction::Allow);
        assert_eq!(action("blob:http://localhost:3000/abc"), LinkAction::Allow);
    }

    #[test]
    fn other_origins_go_to_the_browser() {
        assert_eq!(action("https://docs.onyx.app/"), LinkAction::External);
        assert_eq!(action("http://localhost:3001/"), LinkAction::External);
        assert_eq!(action("mailto:support@onyx.app"), LinkAction::External);
    }

    #[test]
    fn unknown_schemes_are_blocked() {
        assert_eq!(action("file:///etc/passwd"), LinkAction::Block);
        assert_eq!(action("javascript:alert(1)"), LinkAction::Block);
    }
}
