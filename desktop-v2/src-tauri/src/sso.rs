//! SSO sign-in, which the native email form cannot do.
//!
//! Preferred: the system browser, where the user is often already signed in to
//! the identity provider. The server's built-in OAuth flow, with Onyx's mobile
//! SSO parameters, ends at `onyx://auth/callback?code=..&state=..`, and the
//! app swaps the one-time code (with its PKCE verifier) for a session token.
//! It reuses the IdP redirect the web app already has.
//!
//! Fallback, for sign-in flows without the mobile parameters (SSO providers
//! configured as rows: OIDC, SAML): the server's login page runs in its own app
//! window. When the server sets its session cookie there, the app takes it (the
//! cookie is the same token the bearer API uses), stores it, closes the window
//! and opens Onyx.
//!
//! Every sign-in belongs to the session epoch it started in (see `AppState`).
//! Signing out or changing server cancels it; a late result is dropped.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use rand::RngCore;
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;
use url::Url;

use crate::state::AppState;
use crate::{main_window, windows};

pub const LABEL: &str = "sso";
/// Event sent to the login window when an SSO sign-in fails after it started.
pub const FAILED_EVENT: &str = "sso-failed";
// Google refuses sign-in from web views that do not look like a browser.
const BROWSER_USER_AGENT: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";

/// WKWebView's default user agent names no browser, so macOS sends Safari's.
/// WebView2 and WebKitGTK already send their own browser user agent, and
/// WebKitGTK applies its Google sign-in quirks only to that one.
fn user_agent_override(os: &str) -> Option<&'static str> {
    (os == "macos").then_some(BROWSER_USER_AGENT)
}

/// Not the login window's title, so the two windows can be told apart.
fn window_title(os: &str) -> &'static str {
    if os == "macos" {
        "Sign in to Onyx"
    } else {
        "Onyx web sign-in"
    }
}

fn report_failure(app: &AppHandle, message: &str) {
    log::warn!("SSO sign-in failed: {message}");
    #[cfg(not(target_os = "macos"))]
    show_login(app);
    let _ = app.emit_to(windows::LOGIN, FAILED_EVENT, message.to_string());
}

/// Shows the login window again, which is hidden while the sign-in window is open.
#[cfg(not(target_os = "macos"))]
fn show_login(app: &AppHandle) {
    if let Some(login) = app.get_webview_window(windows::LOGIN) {
        windows::bring_forward(app, &login);
    }
}

/// Stores the token and opens Onyx, unless the session this sign-in started in
/// has ended.
async fn finish(app: &AppHandle, server: &str, token: &str, epoch: u64) {
    // Stale if a sign-out, server change or password sign-in came first.
    match app.state::<AppState>().commit_sign_in(server, token, epoch) {
        // The other SSO flow, if the user started both, has nothing to finish.
        Ok(true) => cancel(app),
        Ok(false) => {
            log::warn!("dropped an SSO sign-in that finished after its session ended");
            return;
        }
        Err(e) => {
            report_failure(app, &e);
            return;
        }
    }
    match main_window::open(app, server, token, "/app").await {
        Ok(()) => windows::close(app, windows::LOGIN),
        Err(e) => report_failure(app, &e),
    }
}

pub fn open(app: &AppHandle, server: &str) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(LABEL) {
        let _ = window.set_focus();
        return Ok(());
    }
    let server_url = Url::parse(server).map_err(|e| e.to_string())?;
    let login = server_url.join("/auth/login").map_err(|e| e.to_string())?;
    let origin = server_url.origin().ascii_serialization();
    let nav_app = app.clone();
    // The identity provider can be any HTTPS site, as in an OAuth popup.
    let mut builder = WebviewWindowBuilder::new(app, LABEL, WebviewUrl::External(login))
        .title(window_title(std::env::consts::OS))
        .inner_size(520.0, 720.0)
        .center();
    if let Some(user_agent) = user_agent_override(std::env::consts::OS) {
        builder = builder.user_agent(user_agent);
    }
    let window = builder
        .on_navigation(move |url| match main_window::classify_popup(url, &origin) {
            main_window::LinkAction::Allow => true,
            main_window::LinkAction::External => {
                main_window::open_external(&nav_app, url.as_str());
                false
            }
            main_window::LinkAction::Block => false,
        })
        .on_new_window(windows::local_new_window(app))
        .build()
        .map_err(|e| e.to_string())?;
    let _ = window.set_focus();
    // One sign-in window at a time: the login window comes back when the user
    // closes this one or the sign-in fails.
    #[cfg(not(target_os = "macos"))]
    {
        if let Some(login) = app.get_webview_window(windows::LOGIN) {
            let _ = login.hide();
        }
        let close_app = app.clone();
        window.on_window_event(move |event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                show_login(&close_app);
            }
        });
    }

    let app = app.clone();
    let server = server.to_string();
    let epoch = app.state::<AppState>().epoch();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_millis(700)).await;
            let state = app.state::<AppState>();
            // Cancelled: `cancel` closed this worker's window, and a window
            // under the same label now belongs to a newer attempt.
            if state.epoch() != epoch {
                return;
            }
            let Some(window) = app.get_webview_window(LABEL) else {
                // Closed by the user, also before the close listener was in place.
                #[cfg(not(target_os = "macos"))]
                show_login(&app);
                return;
            };
            let Ok(cookie_name) = state.cookie_name(&server).await else {
                continue; // retried on the next poll
            };
            let token = window
                .cookies_for_url(server_url.clone())
                .ok()
                .and_then(|cookies| cookies.into_iter().find(|c| c.name() == cookie_name))
                .map(|c| c.value().to_string())
                .filter(|v| !v.is_empty());
            let Some(token) = token else {
                continue;
            };
            if !matches!(state.api.session_valid(&server, &token).await, Ok(true)) {
                continue;
            }
            let _ = window.destroy();
            finish(&app, &server, &token, epoch).await;
            return;
        }
    });
    Ok(())
}

/// The system-browser sign-in that is waiting for its `onyx://` callback.
struct PendingBrowserSignIn {
    server: String,
    state: String,
    verifier: String,
    epoch: u64,
    attempt: u64,
}

static PENDING: Mutex<Option<PendingBrowserSignIn>> = Mutex::new(None);
/// The latest browser sign-in attempt. Starting again or cancelling moves it
/// on, so an exchange that is still running for an older attempt is dropped.
static ATTEMPT: AtomicU64 = AtomicU64::new(0);
pub const CALLBACK: &str = "onyx://auth/callback";

fn random_token() -> String {
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}

/// Drops any sign-in in progress: the pending browser sign-in and the fallback
/// window. Called when a session ends.
pub fn cancel(app: &AppHandle) {
    ATTEMPT.fetch_add(1, Ordering::SeqCst);
    *PENDING.lock().unwrap_or_else(|p| p.into_inner()) = None;
    if let Some(window) = app.get_webview_window(LABEL) {
        let _ = window.destroy();
    }
}

/// Starts SSO for `provider` (a provider row, or `None` for the legacy Google
/// sign-in) in the system browser. Returns `Ok(false)` when it has no browser
/// flow, so the caller can fall back to the in-app window.
///
/// The browser itself opens the provider's authorize URL (`redirect=true`), so it receives the CSRF and PKCE cookies and the identity
/// provider returns to the web callback that is already registered. The mobile
/// parameters make that callback finish with `onyx://auth/callback?code=..`
/// instead of a web session, so no extra redirect URI is needed at the IdP.
/// Starting again replaces the previous attempt.
pub async fn start_in_browser(
    app: &AppHandle,
    server: &str,
    provider: Option<&str>,
) -> Result<bool, String> {
    let state = app.state::<AppState>();
    let epoch = state.epoch();
    let methods = state.api.auth_methods(server).await?;
    if state.epoch() != epoch {
        return Err("Sign-in was cancelled.".into());
    }
    // The path comes from the server's own list, never from the page.
    let Some(path) = methods
        .sso
        .into_iter()
        .find(|o| o.browser && o.provider.as_deref() == provider)
        .and_then(|o| o.authorize_path)
    else {
        return Ok(false);
    };
    let verifier = random_token();
    let app_state = random_token();
    let challenge = URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
    // `server` is an origin (see api::normalize), so the path is appended.
    let mut authorize = Url::parse(&format!("{server}{path}")).map_err(|e| e.to_string())?;
    authorize
        .query_pairs_mut()
        .append_pair("redirect", "true")
        .append_pair("mobile_redirect_uri", CALLBACK)
        .append_pair("app_state", &app_state)
        .append_pair("app_code_challenge", &challenge);
    let attempt = ATTEMPT.fetch_add(1, Ordering::SeqCst) + 1;
    *PENDING.lock().unwrap_or_else(|p| p.into_inner()) = Some(PendingBrowserSignIn {
        server: server.to_string(),
        state: app_state,
        verifier,
        epoch,
        attempt,
    });
    app.opener()
        .open_url(authorize.as_str(), None::<&str>)
        .map_err(|e| format!("Could not open your browser: {e}"))?;
    Ok(true)
}

/// Handles `onyx://auth/callback?code=..&state=..` from the browser.
pub fn handle_callback(app: &AppHandle, url: &Url) {
    if url.scheme() != "onyx" || url.host_str() != Some("auth") || url.path() != "/callback" {
        return;
    }
    let param = |key: &str| {
        url.query_pairs()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.into_owned())
    };
    let (Some(code), Some(state)) = (param("code"), param("state")) else {
        return;
    };
    let pending = {
        let mut guard = PENDING.lock().unwrap_or_else(|p| p.into_inner());
        match guard.as_ref() {
            // Only the sign-in this app started; a stray or replayed link is ignored.
            Some(p) if p.state == state => guard.take(),
            _ => None,
        }
    };
    let Some(pending) = pending else {
        log::warn!("ignored an onyx:// sign-in callback that this app did not start");
        return;
    };
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let exchanged = app
            .state::<AppState>()
            .api
            .mobile_sso_exchange(&pending.server, &code, &pending.verifier)
            .await;
        if ATTEMPT.load(Ordering::SeqCst) != pending.attempt {
            log::warn!("dropped a browser sign-in that a newer attempt replaced");
            return;
        }
        match exchanged {
            Ok(token) => finish(&app, &pending.server, &token, pending.epoch).await,
            Err(e) => report_failure(&app, &format!("Sign-in did not finish: {e}")),
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_macos_replaces_the_user_agent() {
        assert_eq!(user_agent_override("macos"), Some(BROWSER_USER_AGENT));
        assert_eq!(user_agent_override("windows"), None);
        assert_eq!(user_agent_override("linux"), None);
    }

    #[test]
    fn the_sign_in_window_title_differs_from_the_login_window_off_macos() {
        assert_eq!(window_title("macos"), "Sign in to Onyx");
        assert_ne!(window_title("windows"), "Sign in to Onyx");
        assert_ne!(window_title("linux"), "Sign in to Onyx");
    }
}
