//! The main window renders the server's own web UI. It gets no IPC; the shell only
//! hands in the session cookie and decides where links, popups and downloads go.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Mutex, MutexGuard};

use tauri::webview::cookie::{Cookie, SameSite};
use tauri::webview::{DownloadEvent, NewWindowFeatures, NewWindowResponse};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;
use url::Url;

use crate::state::AppState;

pub const LABEL: &str = "main";
static POPUP_COUNTER: AtomicUsize = AtomicUsize::new(0);
/// The token last handed to the main window's cookie store.
static WINDOW_TOKEN: Mutex<Option<String>> = Mutex::new(None);

fn window_token() -> MutexGuard<'static, Option<String>> {
    WINDOW_TOKEN.lock().unwrap_or_else(|p| p.into_inner())
}
#[cfg(target_os = "macos")]
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

/// A `blob:` URL has the origin of the page that made it, so another site (in
/// a popup) cannot show its own page in the main window. `data:` pages have no
/// origin and are blocked.
pub fn classify(url: &Url, server_origin: &str) -> LinkAction {
    let same_origin = url.origin().ascii_serialization() == server_origin;
    match url.scheme() {
        // about:srcdoc is the document of an iframe with inline content.
        "about" if matches!(url.path(), "blank" | "srcdoc") => LinkAction::Allow,
        "blob" | "http" | "https" if same_origin => LinkAction::Allow,
        "http" | "https" | "mailto" | "tel" => LinkAction::External,
        _ => LinkAction::Block,
    }
}

/// Popups and the SSO window may also load other HTTPS sites (OAuth consent,
/// identity providers). All other URLs follow the main window's rules.
pub fn classify_popup(url: &Url, server_origin: &str) -> LinkAction {
    match classify(url, server_origin) {
        LinkAction::External if url.scheme() == "https" => LinkAction::Allow,
        action => action,
    }
}

/// Resolves `path` against the server. Fails if the result is on another
/// origin: `//host/x` and `/\host/x` are paths that name another host.
pub fn server_url_join(server_url: &Url, path: &str) -> Result<Url, String> {
    // Only an absolute path; `//host` and `/\host` would name another host.
    if !path.starts_with('/') || path[1..].starts_with(['/', '\\']) {
        return Err("That link is not on your Onyx server.".into());
    }
    let target = server_url.join(path).map_err(|e| e.to_string())?;
    if target.origin() != server_url.origin() {
        return Err("That link is not on your Onyx server.".into());
    }
    Ok(target)
}

/// The web app opens popups for OAuth consent (connectors, MCP): it opens a
/// same-origin `about:blank` popup and then sends it to the provider. So a
/// popup, unlike the main window, may load other HTTPS sites; its title shows
/// the site's host so it is never mistaken for Onyx. Plain HTTP and other
/// schemes follow the main window's rules.
fn popup_navigation_allowed(app: &AppHandle, label: &str, url: &Url, server_origin: &str) -> bool {
    match classify_popup(url, server_origin) {
        LinkAction::Allow => true,
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

#[cfg(not(target_os = "linux"))]
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

/// wry asks on the GTK main thread, where rfd's blocking dialog would deadlock,
/// so Linux keeps wry's unique path in the Downloads folder.
#[cfg(target_os = "linux")]
fn choose_download_path(_destination: &mut std::path::PathBuf) -> bool {
    true
}

fn hand_over_session(
    window: &tauri::WebviewWindow,
    server_url: &Url,
    name: &str,
    token: &str,
) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let result = crate::macos_cookies::set_session_cookie(window, server_url, name, token);
    // WebView2 and WebKitGTK: wry's cookie API. The cookie and the first page
    // load are queued on the main thread in that order.
    #[cfg(not(target_os = "macos"))]
    let result = window
        .set_cookie(session_cookie(server_url, name, token)?)
        .map_err(|e| e.to_string());
    result.map_err(|e| format!("Could not hand the session to the window: {e}"))?;
    *window_token() = Some(token.to_string());
    Ok(())
}

/// Opens (or reuses) the main window logged in as `token`, at `path` on the server.
pub async fn open(app: &AppHandle, server: &str, token: &str, path: &str) -> Result<(), String> {
    let server_url = Url::parse(server).map_err(|e| e.to_string())?;
    let target = server_url_join(&server_url, path)?;
    open_url(app, server, token, target).await
}

/// Like `open`, for a URL that is already parsed. It must be on the server's origin.
pub async fn open_url(
    app: &AppHandle,
    server: &str,
    token: &str,
    target: Url,
) -> Result<(), String> {
    let epoch = app.state::<AppState>().epoch();
    let server_url = Url::parse(server).map_err(|e| e.to_string())?;
    if target.origin() != server_url.origin() {
        return Err("That link is not on your Onyx server.".into());
    }
    if crate::offline::defer_open(app, &target[url::Position::BeforePath..]) {
        return Ok(());
    }

    if let Some(window) = app.get_webview_window(LABEL) {
        // A sign-in since the window got its cookie (for example after the
        // session expired) must reach it; a stale caller token must not.
        let state = app.state::<AppState>();
        let changed = window_token().as_deref() != Some(token)
            && state.token(server).as_deref() == Some(token);
        if changed {
            let cookie_name = state
                .cookie_name(server)
                .await
                .map_err(|e| format!("Could not read the server's sign-in settings: {e}"))?;
            if state.epoch() != epoch {
                return Err("The session ended while Onyx was opening.".to_string());
            }
            hand_over_session(&window, &server_url, &cookie_name, token)?;
        }
        window.navigate(target).map_err(|e| e.to_string())?;
        crate::windows::bring_forward(app, &window);
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
        .on_page_load(|window, payload| match payload.event() {
            tauri::webview::PageLoadEvent::Started => {
                crate::offline::load_committed(window.app_handle());
            }
            tauri::webview::PageLoadEvent::Finished => {
                crate::offline::load_finished(window.app_handle());
                sync_chrome(window.app_handle());
            }
        })
        // Let the web page receive dropped files (chat attachments).
        .disable_drag_drop_handler()
        .on_navigation(move |url| match classify(url, &nav_origin) {
            LinkAction::Allow => {
                if matches!(url.scheme(), "http" | "https") {
                    crate::offline::watch_load(&nav_app, url);
                }
                true
            }
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
    // Other platforms keep the native title bar and the page's own layout.
    #[cfg(target_os = "macos")]
    let builder = builder
        .initialization_script(DESKTOP_CHROME_JS)
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true);
    #[cfg(not(target_os = "macos"))]
    let builder = builder.menu(crate::menu::build_window_menu(app).map_err(|e| e.to_string())?);

    let window = builder.build().map_err(|e| e.to_string())?;
    // Entering or leaving full screen resizes the window.
    let resize_app = app.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::Resized(_) = event {
            sync_chrome(&resize_app);
        }
    });

    // WebView2 and WebKitGTK show alert(), confirm() and prompt() themselves.
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
    crate::windows::bring_forward(app, &window);
    Ok(())
}

/// Removes the session cookie and closes the main window and its popups.
pub fn close(app: &AppHandle, server: &str) {
    let Some(window) = app.get_webview_window(LABEL) else {
        return;
    };
    *window_token() = None;
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

/// Renews the stored session so a running app never signs out. Returns the
/// token to use from now on, or `None` when the session ended meanwhile (a
/// sign-out, a new sign-in or a server change): the caller must stop.
pub async fn renew_session(app: &AppHandle, server: &str, token: &str) -> Option<String> {
    let state = app.state::<AppState>();
    match state.api.refresh(server, token).await {
        // Saved only if this session is still the stored one.
        Ok(fresh) if state.replace_token(server, token, &fresh) => {
            if let (Some(window), Ok(server_url)) =
                (app.get_webview_window(LABEL), Url::parse(server))
            {
                let name = state.cached_cookie_name(server);
                let _ = hand_over_session(&window, &server_url, &name, &fresh);
            }
            Some(fresh)
        }
        Ok(_) => None,
        Err(e) => {
            log::warn!("session renewal failed: {e}");
            // A transient failure keeps the current token, if it is still current.
            (state.token(server).as_deref() == Some(token)).then(|| token.to_string())
        }
    }
}

/// Renews the session while the app runs, as often as the web app does
/// (every 10 minutes), so short server session lifetimes
/// (`SESSION_EXPIRE_TIME_SECONDS`) do not expire while only the launcher is
/// in use.
pub fn spawn_session_renewal(app: &AppHandle) {
    const RENEWAL_INTERVAL: std::time::Duration = std::time::Duration::from_secs(10 * 60);
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(RENEWAL_INTERVAL).await;
            if let Ok((server, token)) = app.state::<AppState>().session() {
                renew_session(&app, &server, &token).await;
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{classify, classify_popup, server_url_join, LinkAction};
    use url::Url;

    const ORIGIN: &str = "http://localhost:3000";

    fn joined(path: &str) -> Option<String> {
        let server = Url::parse("https://onyx.example").unwrap();
        server_url_join(&server, path)
            .ok()
            .map(|url| url.to_string())
    }

    #[test]
    fn joins_paths_on_the_server() {
        assert_eq!(
            joined("/app?chatId=1#end").as_deref(),
            Some("https://onyx.example/app?chatId=1#end")
        );
        assert_eq!(joined("/").as_deref(), Some("https://onyx.example/"));
    }

    #[test]
    fn rejects_paths_that_leave_the_server() {
        assert_eq!(joined("//evil.example/login"), None);
        assert_eq!(joined("/\\evil.example"), None);
        assert_eq!(joined("https://evil.example/"), None);
        assert_eq!(joined("app"), None);
        assert_eq!(joined(""), None);
    }

    fn action(url: &str) -> LinkAction {
        classify(&Url::parse(url).unwrap(), ORIGIN)
    }

    fn popup_action(url: &str) -> LinkAction {
        classify_popup(&Url::parse(url).unwrap(), ORIGIN)
    }

    #[test]
    fn same_origin_stays_in_app() {
        assert_eq!(
            action("http://localhost:3000/app?chatId=1"),
            LinkAction::Allow
        );
        assert_eq!(action("about:blank"), LinkAction::Allow);
        assert_eq!(action("about:srcdoc"), LinkAction::Allow);
        assert_eq!(action("blob:http://localhost:3000/abc"), LinkAction::Allow);
    }

    #[test]
    fn other_sites_cannot_replace_the_page() {
        // What a third-party page in a popup could send `window.opener` to.
        for url in [
            "blob:https://evil.example/abc",
            "blob:null/abc",
            "data:text/html,<title>Onyx</title>",
            "about:evil",
        ] {
            assert_eq!(action(url), LinkAction::Block, "{url}");
            assert_eq!(popup_action(url), LinkAction::Block, "{url}");
        }
        assert_eq!(action("https://evil.example/login"), LinkAction::External);
    }

    #[test]
    fn popups_may_load_other_https_sites() {
        assert_eq!(
            popup_action("https://accounts.google.com/o/oauth2"),
            LinkAction::Allow
        );
        assert_eq!(popup_action("http://evil.example/"), LinkAction::External);
        assert_eq!(popup_action("javascript:alert(1)"), LinkAction::Block);
    }

    #[test]
    fn joined_paths_stay_on_the_server() {
        let server = Url::parse("https://onyx.corp").unwrap();
        assert_eq!(
            server_url_join(&server, "/app?chatId=1#top")
                .unwrap()
                .as_str(),
            "https://onyx.corp/app?chatId=1#top"
        );
        assert_eq!(
            server_url_join(&server, "/onyx.corp//x").unwrap().as_str(),
            "https://onyx.corp/onyx.corp//x"
        );
        for path in [
            "//evil.example/x",
            "/\\evil.example/x",
            "\\\\evil.example/x",
            "https://evil.example/x",
            "http://onyx.corp/x",
            "javascript:alert(1)",
        ] {
            assert!(server_url_join(&server, path).is_err(), "{path}");
        }
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
