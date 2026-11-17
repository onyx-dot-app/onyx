//! The main window renders the server's own web UI. It gets no IPC; the shell only
//! hands in the session cookie and decides where links, popups and downloads go.

use std::sync::atomic::{AtomicUsize, Ordering};

use tauri::webview::cookie::{Cookie, SameSite};
use tauri::webview::{DownloadEvent, NewWindowResponse};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;
use url::Url;

pub const LABEL: &str = "main";
const SESSION_COOKIE: &str = "fastapiusersauth";
static POPUP_COUNTER: AtomicUsize = AtomicUsize::new(0);

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

pub fn open_external(app: &AppHandle, url: &str) {
    if let Err(e) = app.opener().open_url(url, None::<&str>) {
        log::warn!("could not open {url}: {e}");
    }
}

fn session_cookie(server: &Url, token: &str) -> Result<Cookie<'static>, String> {
    let host = server
        .host_str()
        .ok_or_else(|| "server URL has no host".to_string())?
        .to_string();
    let mut cookie = Cookie::build((SESSION_COOKIE, token.to_string()))
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
    token: &str,
) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let result =
        crate::macos_cookies::set_session_cookie(window, server_url, SESSION_COOKIE, token);
    #[cfg(not(target_os = "macos"))]
    let result = window
        .set_cookie(session_cookie(server_url, token)?)
        .map_err(|e| e.to_string());
    result.map_err(|e| format!("Could not hand the session to the window: {e}"))
}

/// Opens (or reuses) the main window logged in as `token`, at `path` on the server.
pub async fn open(app: &AppHandle, server: &str, token: &str, path: &str) -> Result<(), String> {
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

    let blank = WebviewUrl::External("about:blank".parse().map_err(|_| "bad url")?);
    let builder = WebviewWindowBuilder::new(app, LABEL, blank)
        .title("Onyx")
        .inner_size(1280.0, 840.0)
        .min_inner_size(800.0, 600.0)
        .center()
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
        .on_new_window(move |url, features| match classify(&url, &popup_origin) {
            LinkAction::Allow => {
                let label = format!("popup-{}", POPUP_COUNTER.fetch_add(1, Ordering::Relaxed));
                let blank = WebviewUrl::External("about:blank".parse().expect("valid url"));
                match WebviewWindowBuilder::new(&popup_app, label, blank)
                    .title("Onyx")
                    .window_features(features)
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
                open_external(&popup_app, url.as_str());
                NewWindowResponse::Deny
            }
            LinkAction::Block => NewWindowResponse::Deny,
        })
        .on_download(move |_webview, event| match event {
            DownloadEvent::Requested { destination, .. } => choose_download_path(destination),
            DownloadEvent::Finished { url, success, .. } => {
                log::info!("download of {url} finished (success: {success})");
                true
            }
            _ => true,
        });

    let window = builder.build().map_err(|e| e.to_string())?;

    #[cfg(target_os = "macos")]
    crate::macos_dialogs::install(&window);

    hand_over_session(&window, &server_url, token)?;
    window.navigate(target).map_err(|e| e.to_string())?;
    let _ = window.set_focus();
    Ok(())
}

/// Removes the session cookie and closes the main window and its popups.
pub fn close(app: &AppHandle, server: &str) {
    let Some(window) = app.get_webview_window(LABEL) else {
        return;
    };
    if let Ok(server_url) = Url::parse(server) {
        #[cfg(target_os = "macos")]
        let _ = crate::macos_cookies::clear_session_cookie(&window, &server_url, SESSION_COOKIE);
        if let Ok(cookie) = session_cookie(&server_url, "") {
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
