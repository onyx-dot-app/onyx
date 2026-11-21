//! The main window renders the server's own web UI. It gets no IPC; the shell only
//! hands in the session cookie and decides where links, popups and downloads go.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Mutex, MutexGuard};
use std::time::{Duration, Instant};

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
const SIGN_IN_GUARD_JS: &str = include_str!("sign_in_guard.js");

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

/// Whether a main-window navigation starts the web app's own sign-in: its
/// login or signup page, an SSO authorize URL on the server, or an identity
/// provider's authorize page that returns to the server's sign-in callback.
/// That sign-in can never reach the app (the identity provider opens in the
/// browser), so the app handles it as a lost web session.
pub fn is_web_sign_in(url: &Url, server_url: &Url) -> bool {
    if !matches!(url.scheme(), "http" | "https") {
        return false;
    }
    if url.origin() == server_url.origin() {
        return is_sign_in_path(url.path());
    }
    url.query_pairs().any(|(key, value)| match key.as_ref() {
        "redirect_uri" => Url::parse(&value).is_ok_and(|target| {
            target.origin() == server_url.origin() && is_auth_path(target.path())
        }),
        "SAMLRequest" => saml_return_url(&value).is_some_and(|target| {
            target.origin() == server_url.origin() && is_auth_path(target.path())
        }),
        _ => false,
    })
}

/// The `AssertionConsumerServiceURL` of a redirect-binding SAML request
/// (base64 of raw-deflated XML).
fn saml_return_url(request: &str) -> Option<Url> {
    use base64::Engine;
    use std::io::Read;
    let compressed = base64::engine::general_purpose::STANDARD
        .decode(request)
        .ok()?;
    let mut xml = String::new();
    flate2::read::DeflateDecoder::new(compressed.as_slice())
        .take(64 * 1024)
        .read_to_string(&mut xml)
        .ok()?;
    let start =
        xml.find("AssertionConsumerServiceURL=\"")? + "AssertionConsumerServiceURL=\"".len();
    let end = xml[start..].find('"')? + start;
    Url::parse(&xml[start..end].replace("&amp;", "&")).ok()
}

fn is_auth_path(path: &str) -> bool {
    (path.starts_with("/auth/") || path.starts_with("/api/auth/"))
        && !path.starts_with("/api/auth/mobile/")
}

fn is_sign_in_path(path: &str) -> bool {
    let path = path.trim_end_matches('/');
    matches!(path, "/auth/login" | "/auth/signup")
        || (is_auth_path(path) && path.ends_with("/authorize"))
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

/// Downloads from any app window ask where to save, like a browser. On Linux
/// they save to the Downloads folder, and a notification tells where
/// (`watch_downloads`).
fn handle_download(event: DownloadEvent) -> bool {
    match event {
        DownloadEvent::Requested { destination, .. } => choose_download_path(destination),
        DownloadEvent::Finished { url, success, .. } => {
            log::info!(
                "download of {} finished (success: {success})",
                log_safe(url.as_str())
            );
            true
        }
        _ => true,
    }
}

/// Notifies once for each finished download. wry adds its download handler
/// to the web context that all windows share, once for each window it
/// builds, so `handle_download` runs several times for one download on Linux.
#[cfg(target_os = "linux")]
fn watch_downloads(app: &AppHandle, view: &webkit2gtk::WebView) {
    use std::cell::Cell;
    use std::rc::Rc;
    use webkit2gtk::{DownloadExt, WebContextExt, WebViewExt};

    static WATCHING: std::sync::Once = std::sync::Once::new();
    WATCHING.call_once(|| {
        let Some(context) = view.context() else {
            return;
        };
        let app = app.clone();
        context.connect_download_started(move |_, download| {
            let failed = Rc::new(Cell::new(false));
            download.connect_failed({
                let failed = failed.clone();
                move |_, _| failed.set(true)
            });
            let app = app.clone();
            download.connect_finished(move |download| {
                let success = !failed.get();
                let path = download.destination().map(std::path::PathBuf::from);
                notify_download(&app, path.as_deref(), success);
            });
        });
    });
}

/// The notification text for a finished download.
#[cfg(any(target_os = "linux", test))]
fn download_notice(path: Option<&std::path::Path>, success: bool) -> (String, String) {
    let name = path
        .and_then(|p| p.file_name())
        .map(|n| n.to_string_lossy().into_owned());
    let folder = path
        .and_then(|p| p.parent())
        .map(|d| d.display().to_string());
    match (success, name, folder) {
        (true, Some(name), Some(folder)) => (
            format!("Downloaded {name}"),
            format!("Saved to {folder}. Click to show it in its folder."),
        ),
        (true, _, _) => (
            "Download finished".into(),
            "Saved to your Downloads folder.".into(),
        ),
        (false, Some(name), _) => ("Download failed".into(), format!("Could not save {name}.")),
        (false, None, _) => ("Download failed".into(), "Could not save the file.".into()),
    }
}

/// The extra key that carries a downloaded file's path in its notification.
#[cfg(target_os = "linux")]
const DOWNLOAD_KEY: &str = "download";

#[cfg(target_os = "linux")]
fn notify_download(app: &AppHandle, path: Option<&std::path::Path>, success: bool) {
    use tauri_plugin_notification::NotificationExt;

    if app.state::<AppState>().policy().disable_notifications {
        return;
    }
    static CLICKS: std::sync::Once = std::sync::Once::new();
    CLICKS.call_once(|| {
        let handle = app.clone();
        let _ = app.notification().on_action(move |performed| {
            let path = performed
                .notification()
                .and_then(|n| n.extra().get(DOWNLOAD_KEY))
                .and_then(|p| p.as_str());
            if let (Some(path), "tap") = (path, performed.action_id()) {
                if let Err(e) = handle.opener().reveal_item_in_dir(path) {
                    log::warn!("could not show the download in its folder: {e}");
                }
            }
        });
    });
    let (title, body) = download_notice(path, success);
    let mut builder = app.notification().builder().title(title).body(body);
    if let (true, Some(path)) = (success, path) {
        builder = builder.extra(DOWNLOAD_KEY, path.display().to_string());
    }
    if let Err(e) = builder.show() {
        log::warn!("could not show the download notification: {e}");
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
        log::warn!("could not open {}: {}", log_safe(url), open_error_kind(&e));
    }
}

/// The kind of an opener error. Its message can hold the whole URL (the
/// launcher command line), so the message is not logged.
fn open_error_kind(error: &tauri_plugin_opener::Error) -> String {
    match error {
        tauri_plugin_opener::Error::Io(e) => format!("{:?}", e.kind()),
        tauri_plugin_opener::Error::ForbiddenUrl { .. }
        | tauri_plugin_opener::Error::ForbiddenPath { .. } => "not allowed".into(),
        _ => "opener error".into(),
    }
}

/// A URL or server path for the log file: no user info, query or fragment,
/// which can carry passwords, tokens or sign-in codes.
pub fn log_safe(url: &str) -> String {
    match Url::parse(url) {
        Ok(mut parsed) => {
            let _ = parsed.set_username("");
            let _ = parsed.set_password(None);
            parsed.set_query(None);
            parsed.set_fragment(None);
            parsed.to_string()
        }
        Err(_) => url.split(['?', '#']).next().unwrap_or_default().to_string(),
    }
}

fn session_cookie(server: &Url, name: &str, token: &str) -> Result<Cookie<'static>, String> {
    let host = server
        .host_str()
        .ok_or_else(|| "server URL has no host".to_string())?
        .to_string();
    // A domain with no leading dot is a host-only cookie in libsoup and
    // WebView2, so subdomains do not get the session.
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

/// WebKitGTK refuses a clipboard write once the click's user activation has
/// passed, which the web UI's copy after a request needs (WebView2 and
/// WKWebView allow it). Reading the clipboard stays behind WebKit's paste
/// rules. The context menu keeps WebKit's standard items only: its custom ones
/// (Copy Link with Highlight) link into the embedded page.
#[cfg(target_os = "linux")]
fn configure_webkit(window: &tauri::WebviewWindow) {
    use webkit2gtk::{ContextMenuExt, ContextMenuItemExt, SettingsExt, WebViewExt};

    let app = window.app_handle().clone();
    let result = window.with_webview(move |webview| {
        let view = webview.inner();
        watch_downloads(&app, &view);
        if let Some(settings) = WebViewExt::settings(&view) {
            settings.set_javascript_can_access_clipboard(true);
        }
        view.connect_context_menu(|_, menu, _, _| {
            for item in menu.items() {
                if !is_standard_menu_action(item.stock_action()) {
                    menu.remove(&item);
                }
            }
            false
        });
    });
    if let Err(e) = result {
        log::warn!("could not set up the web view: {e}");
    }
}

#[cfg(target_os = "linux")]
fn is_standard_menu_action(action: webkit2gtk::ContextMenuAction) -> bool {
    !matches!(
        action,
        webkit2gtk::ContextMenuAction::Custom | webkit2gtk::ContextMenuAction::__Unknown(_)
    )
}

/// WebView2 takes key presses while the page has focus, so the menu bar's
/// accelerators never see them. Its accelerator event runs the menu item.
#[cfg(windows)]
fn forward_menu_keys(window: &tauri::WebviewWindow) {
    use webview2_com::AcceleratorKeyPressedEventHandler;
    use webview2_com::Microsoft::Web::WebView2::Win32::{
        COREWEBVIEW2_KEY_EVENT_KIND, COREWEBVIEW2_KEY_EVENT_KIND_KEY_DOWN,
        COREWEBVIEW2_KEY_EVENT_KIND_SYSTEM_KEY_DOWN,
    };
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        GetKeyState, VIRTUAL_KEY, VK_CONTROL, VK_MENU, VK_SHIFT,
    };

    let app = window.app_handle().clone();
    let result = window.with_webview(move |webview| {
        let held = |key: VIRTUAL_KEY| unsafe { GetKeyState(i32::from(key.0)) } < 0;
        let handler = AcceleratorKeyPressedEventHandler::create(Box::new(move |_, args| {
            let Some(args) = args else {
                return Ok(());
            };
            let mut kind = COREWEBVIEW2_KEY_EVENT_KIND::default();
            let mut key = 0u32;
            // SAFETY: WebView2 calls this on the UI thread with live event args.
            unsafe {
                args.KeyEventKind(&mut kind)?;
                args.VirtualKey(&mut key)?;
            }
            if kind != COREWEBVIEW2_KEY_EVENT_KIND_KEY_DOWN
                && kind != COREWEBVIEW2_KEY_EVENT_KIND_SYSTEM_KEY_DOWN
            {
                return Ok(());
            }
            let modifiers = crate::menu::Modifiers {
                ctrl: held(VK_CONTROL),
                alt: held(VK_MENU),
                shift: held(VK_SHIFT),
            };
            if let Some(id) = crate::menu::key_action(key, modifiers) {
                // SAFETY: as above.
                unsafe { args.SetHandled(true)? };
                // After the WebView2 callback returns: an item can build or
                // close a web view. `run_on_main_thread` runs at once when called
                // on the main thread, so it is called from another thread.
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    let handle = app.clone();
                    let _ = app.run_on_main_thread(move || crate::menu::handle(&handle, id));
                });
            }
            Ok(())
        }));
        let mut token = 0i64;
        // SAFETY: the controller is live on the UI thread, where with_webview runs.
        if let Err(e) = unsafe {
            webview
                .controller()
                .add_AcceleratorKeyPressed(&handler, &mut token)
        } {
            log::warn!("could not watch for menu keys: {e}");
        }
    });
    if let Err(e) = result {
        log::warn!("could not watch for menu keys: {e}");
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
    if crate::offline::defer_open(app, &crate::offline::path_of(&target)) {
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
    let nav_server_url = server_url.clone();
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
        .initialization_script(SIGN_IN_GUARD_JS)
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
        .on_navigation(move |url| {
            if is_web_sign_in(url, &nav_server_url) {
                recover_web_session(&nav_app, url);
                return false;
            }
            navigation_allowed(&nav_app, url, &nav_origin)
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
    #[cfg(target_os = "linux")]
    crate::offline::watch_webview_failures(&window);
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
    #[cfg(windows)]
    forward_menu_keys(&window);
    #[cfg(target_os = "linux")]
    configure_webkit(&window);
    #[cfg(target_os = "linux")]
    crate::aonyx::step_aside_for_file_choosers(&window);

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

fn navigation_allowed(app: &AppHandle, url: &Url, origin: &str) -> bool {
    match classify(url, origin) {
        LinkAction::Allow => {
            if matches!(url.scheme(), "http" | "https") {
                crate::offline::watch_load(app, url);
            }
            true
        }
        LinkAction::External => {
            open_external(app, url.as_str());
            false
        }
        LinkAction::Block => false,
    }
}

/// A recovery of the web session is running; sign-in navigations meanwhile
/// are only blocked.
static RECOVERING: AtomicBool = AtomicBool::new(false);
/// When the cookie was last handed over again, and in which session (epoch),
/// so a web app that still asks for a sign-in does not loop.
static LAST_HANDOVER_RETRY: Mutex<Option<(u64, Instant)>> = Mutex::new(None);
const HANDOVER_RETRY_GAP: Duration = Duration::from_secs(60);

/// Where to go once the web session is back: the login page's `next` path,
/// or the app's home.
fn return_path(url: &Url, server_url: &Url) -> String {
    if url.origin() == server_url.origin() {
        let next = url
            .query_pairs()
            .find(|(key, _)| key == "next")
            .map(|(_, value)| value.into_owned());
        if let Some(next) = next {
            if let Ok(target) = server_url_join(server_url, &next) {
                if !is_sign_in_path(target.path()) {
                    return next;
                }
            }
        }
    }
    "/app".to_string()
}

/// The web app lost its session and started its own sign-in. If the app's
/// session is still valid, the cookie is handed over again (once a minute at
/// most); otherwise the session ends as a rejected one does, and the native
/// sign-in window opens.
fn recover_web_session(app: &AppHandle, url: &Url) {
    if RECOVERING.swap(true, Ordering::SeqCst) {
        return;
    }
    let app = app.clone();
    let url = url.clone();
    tauri::async_runtime::spawn(async move {
        recover(&app, &url).await;
        RECOVERING.store(false, Ordering::SeqCst);
    });
}

async fn recover(app: &AppHandle, url: &Url) {
    let state = app.state::<AppState>();
    let epoch = state.epoch();
    let Ok((server, token)) = state.session() else {
        close(app, &state.server().unwrap_or_default());
        crate::windows::route(app);
        return;
    };
    let Ok(server_url) = Url::parse(&server) else {
        return;
    };
    let path = return_path(url, &server_url);
    let valid = state.api.session_valid(&server, &token).await;
    // A sign-out or new sign-in meanwhile owns the window now.
    if state.epoch() != epoch {
        return;
    }
    match valid {
        Ok(true) if take_handover_retry(epoch) => {
            if let Err(e) = hand_over_again(app, &server, &server_url, &path, epoch).await {
                log::warn!("could not give the session back to the window: {e}");
                release_handover_retry();
                // Open the main window again, which hands the session over.
                crate::windows::route(app);
            }
        }
        Ok(true) => {
            log::warn!("the web app still asks for a sign-in; signing in again");
            crate::windows::end_rejected_session(app, &server, &token);
        }
        Ok(false) => crate::windows::end_rejected_session(app, &server, &token),
        Err(reason) => crate::windows::show_offline(app, &server, &path, reason, epoch),
    }
}

/// True, and starts a new gap, if no hand-over retry ran in this session
/// (epoch) in the last gap.
fn take_handover_retry(epoch: u64) -> bool {
    let mut last = LAST_HANDOVER_RETRY
        .lock()
        .unwrap_or_else(|p| p.into_inner());
    if last.is_some_and(|(at_epoch, at)| at_epoch == epoch && at.elapsed() < HANDOVER_RETRY_GAP) {
        return false;
    }
    *last = Some((epoch, Instant::now()));
    true
}

fn release_handover_retry() {
    *LAST_HANDOVER_RETRY
        .lock()
        .unwrap_or_else(|p| p.into_inner()) = None;
}

async fn hand_over_again(
    app: &AppHandle,
    server: &str,
    server_url: &Url,
    path: &str,
    epoch: u64,
) -> Result<(), String> {
    let state = app.state::<AppState>();
    let name = state.cookie_name(server).await?;
    let window = app
        .get_webview_window(LABEL)
        .ok_or("the main window is closed")?;
    if state.epoch() != epoch {
        return Ok(());
    }
    // The stored token, read now: a renewal during the waits replaced the
    // one that was checked, and the older one must not overwrite it.
    let Ok((current_server, token)) = state.session() else {
        return Ok(());
    };
    if current_server != server {
        return Ok(());
    }
    hand_over_session(&window, server_url, &name, &token)?;
    let target = server_url_join(server_url, path)?;
    window.navigate(target).map_err(|e| e.to_string())
}

/// Removes the session cookie and closes the main window and its popups.
pub fn close(app: &AppHandle, server: &str) {
    let Some(window) = app.get_webview_window(LABEL) else {
        return;
    };
    *window_token() = None;
    release_handover_retry();
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
    use super::{
        classify, classify_popup, download_notice, is_web_sign_in, log_safe, open_error_kind,
        return_path, server_url_join, LinkAction,
    };
    use url::Url;

    #[test]
    fn opener_errors_log_no_url() {
        let error = tauri_plugin_opener::Error::Io(std::io::Error::other(
            "Launcher \"xdg-open\" [\"https://x.example/?token=secret\"] failed",
        ));
        assert_eq!(open_error_kind(&error), "Other");
        let forbidden = tauri_plugin_opener::Error::ForbiddenUrl {
            url: "https://x.example/?token=secret".into(),
            with: None,
        };
        assert!(!open_error_kind(&forbidden).contains("secret"));
    }

    #[test]
    fn a_finished_download_says_where_it_is() {
        let path = std::path::Path::new("/home/me/Downloads/report (1).csv");
        assert_eq!(
            download_notice(Some(path), true),
            (
                "Downloaded report (1).csv".to_string(),
                "Saved to /home/me/Downloads. Click to show it in its folder.".to_string()
            )
        );
        assert_eq!(download_notice(Some(path), false).0, "Download failed");
        assert_eq!(download_notice(None, true).0, "Download finished");
    }

    const ORIGIN: &str = "http://localhost:3000";

    fn joined(path: &str) -> Option<String> {
        let server = Url::parse("https://onyx.example").unwrap();
        server_url_join(&server, path)
            .ok()
            .map(|url| url.to_string())
    }

    #[test]
    fn log_lines_drop_secrets_from_urls() {
        assert_eq!(
            log_safe("https://user:pw@files.example/doc.pdf?X-Amz-Signature=abc#p=2"),
            "https://files.example/doc.pdf"
        );
        assert_eq!(
            log_safe("/auth/oauth/callback?code=abc&state=xyz"),
            "/auth/oauth/callback"
        );
        assert_eq!(log_safe("/app"), "/app");
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

    fn web_sign_in(url: &str) -> bool {
        let server = Url::parse("https://onyx.corp").unwrap();
        is_web_sign_in(&Url::parse(url).unwrap(), &server)
    }

    #[test]
    fn web_sign_in_pages_on_the_server() {
        for url in [
            "https://onyx.corp/auth/login",
            "https://onyx.corp/auth/login/",
            "https://onyx.corp/auth/login?next=%2Fapp%3FchatId%3D1",
            "https://onyx.corp/auth/signup",
            "https://onyx.corp/api/auth/oauth/authorize?redirect=true",
            "https://onyx.corp/api/auth/oidc/okta/authorize",
            "https://onyx.corp/api/auth/saml/authorize",
            "https://onyx.corp/auth/oauth/authorize",
        ] {
            assert!(web_sign_in(url), "{url}");
        }
    }

    #[test]
    fn identity_providers_returning_to_the_server() {
        assert!(web_sign_in(
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&response_type=code\
             &redirect_uri=https%3A%2F%2Fonyx.corp%2Fauth%2Foauth%2Fcallback&state=s"
        ));
        assert!(web_sign_in(
            "https://login.okta.example/authorize?redirect_uri=https://onyx.corp/auth/oidc/callback"
        ));
        assert!(web_sign_in(&saml_sign_in(
            "https://onyx.corp/auth/saml/callback"
        )));
    }

    fn saml_sign_in(return_url: &str) -> String {
        use base64::Engine;
        use std::io::Write;
        let xml =
            format!(r#"<samlp:AuthnRequest ID="x" AssertionConsumerServiceURL="{return_url}"/>"#);
        let mut encoder =
            flate2::write::DeflateEncoder::new(Vec::new(), flate2::Compression::default());
        encoder.write_all(xml.as_bytes()).unwrap();
        let request = base64::engine::general_purpose::STANDARD.encode(encoder.finish().unwrap());
        let mut url = Url::parse("https://idp.example/sso").unwrap();
        url.query_pairs_mut()
            .append_pair("SAMLRequest", &request)
            .append_pair("RelayState", "x");
        url.to_string()
    }

    #[test]
    fn another_services_saml_sign_in_is_not_web_sign_in() {
        assert!(!web_sign_in(&saml_sign_in(
            "https://other.example/saml/acs"
        )));
        assert!(!web_sign_in("https://idp.example/sso?SAMLRequest=abc"));
    }

    #[test]
    fn other_navigations_are_not_web_sign_in() {
        for url in [
            "https://onyx.corp/app",
            "https://onyx.corp/app?chatId=1",
            "https://onyx.corp/auth/logout",
            "https://onyx.corp/auth/app-handoff",
            "https://onyx.corp/auth/oauth/callback?code=c&state=s",
            "https://onyx.corp/admin/connectors/google-drive/auth/authorize",
            "https://onyx.corp/api/auth/mobile/oauth/authorize",
            "https://onyx.corp/api/connector/oauth/authorize/slack",
            "https://docs.onyx.app/",
            // Connector OAuth returns to a connector page, not a sign-in.
            "https://slack.com/oauth/v2/authorize?redirect_uri=https://onyx.corp/connector/oauth/callback/slack",
            // A sign-in for another site.
            "https://accounts.google.com/o/oauth2/v2/auth?redirect_uri=https://other.example/auth/oauth/callback",
            "http://onyx.corp/auth/login",
            "about:blank",
        ] {
            assert!(!web_sign_in(url), "{url}");
        }
    }

    #[test]
    fn returns_to_the_login_page_next_path() {
        let server = Url::parse("https://onyx.corp").unwrap();
        let path = |url: &str| return_path(&Url::parse(url).unwrap(), &server);
        assert_eq!(
            path("https://onyx.corp/auth/login?next=%2Fapp%3FchatId%3D1"),
            "/app?chatId=1"
        );
        assert_eq!(path("https://onyx.corp/auth/login"), "/app");
        assert_eq!(
            path("https://onyx.corp/auth/login?next=//evil.example"),
            "/app"
        );
        assert_eq!(
            path("https://onyx.corp/auth/login?next=/auth/login"),
            "/app"
        );
        assert_eq!(
            path("https://accounts.google.com/o/oauth2/v2/auth?next=/admin"),
            "/app"
        );
    }

    #[test]
    fn unknown_schemes_are_blocked() {
        assert_eq!(action("file:///etc/passwd"), LinkAction::Block);
        assert_eq!(action("javascript:alert(1)"), LinkAction::Block);
    }
}
