//! Brings OAuth callbacks that finished in the system browser back into the
//! app. The web app marks desktop attempts with a `.desktop` state suffix, the
//! browser-side callback page opens `onyx://oauth-callback?path=...`, and this
//! module loads that callback on the configured server, where the app's own
//! session completes it.

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, Wry};
use tauri_plugin_deep_link::DeepLinkExt;
use url::Url;

use crate::config::ConfigState;
use crate::debug_log::log_backend_error;
use crate::window::{focus_main_window, redact_url, POPUP_LABEL_PREFIX};

const SCHEME: &str = "onyx";
const HOST: &str = "oauth-callback";
const DESKTOP_STATE_SUFFIX: &str = ".desktop";
const CALLBACK_WINDOW_SIZE: (f64, f64) = (650.0, 760.0);
const CALLBACK_WINDOW_SCRIPT: &str = "window.__ONYX_DESKTOP__ = Object.assign(window.__ONYX_DESKTOP__ || {}, { oauthCallbackWindow: true });";

const EXACT_PATHS: &[&str] = &[
    "/mcp/oauth/callback",
    "/federated/oauth/callback",
    "/craft/v1/apps/oauth/callback",
    "/oauth-config/callback",
];

fn is_slug(segment: &str) -> bool {
    !segment.is_empty()
        && segment
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

fn is_allowed_path(path: &str) -> bool {
    if EXACT_PATHS.contains(&path) {
        return true;
    }
    let segments: Vec<&str> = path.split('/').collect();
    match segments.as_slice() {
        ["", "admin", "connectors", source, "oauth", "callback"]
        | ["", "connector", "oauth", "callback", source] => is_slug(source),
        _ => false,
    }
}

/// Maps a deep link to the callback URL on the configured server, or `None`
/// when the link is not a well-formed desktop OAuth callback.
pub fn callback_url(server: &Url, deep_link: &Url) -> Option<Url> {
    if deep_link.scheme() != SCHEME || deep_link.host_str() != Some(HOST) {
        return None;
    }
    let path = deep_link
        .query_pairs()
        .find_map(|(key, value)| (key == "path").then(|| value.into_owned()))?;
    if !path.starts_with('/') || path.starts_with("//") || path.contains('\\') {
        return None;
    }
    let mut url = server.join(&path).ok()?;
    if url.origin() != server.origin() || !is_allowed_path(url.path()) {
        return None;
    }
    let mut saw_desktop_state = false;
    let pairs: Vec<(String, String)> = url
        .query_pairs()
        .map(|(key, value)| {
            if key == "state" {
                if let Some(state) = value.strip_suffix(DESKTOP_STATE_SUFFIX) {
                    saw_desktop_state = true;
                    return (key.into_owned(), state.to_string());
                }
            }
            (key.into_owned(), value.into_owned())
        })
        .collect();
    if !saw_desktop_state {
        return None;
    }
    url.query_pairs_mut().clear().extend_pairs(pairs);
    url.set_fragment(None);
    Some(url)
}

fn open_callback_window(app: &AppHandle, url: Url) -> Result<(), String> {
    let label = format!("{POPUP_LABEL_PREFIX}oauth-{}", uuid::Uuid::new_v4());
    let config = app.state::<ConfigState>().config();
    let window = WebviewWindowBuilder::new(app, &label, WebviewUrl::External(url))
        .title(config.window_title)
        .inner_size(CALLBACK_WINDOW_SIZE.0, CALLBACK_WINDOW_SIZE.1)
        .initialization_script(CALLBACK_WINDOW_SCRIPT)
        .build()
        .map_err(|e| e.to_string())?;
    #[cfg(target_os = "macos")]
    crate::macos_webview::install_ui_delegate_extensions(&window);
    window.set_focus().map_err(|e| e.to_string())
}

pub fn handle_deep_link(app: &AppHandle, deep_link: &Url) {
    let Ok(server) = app
        .state::<ConfigState>()
        .config()
        .server_url
        .parse::<Url>()
    else {
        return;
    };
    let Some(url) = callback_url(&server, deep_link) else {
        log_backend_error(
            app,
            &format!("Ignored deep link: {}", redact_url(deep_link)),
        );
        return;
    };
    focus_main_window(app);
    if let Err(e) = open_callback_window(app, url) {
        log_backend_error(app, &format!("Failed to open OAuth callback: {e}"));
    }
}

// The single-instance plugin passes owned arguments.
#[allow(clippy::needless_pass_by_value)]
pub fn on_second_instance(app: &AppHandle, args: Vec<String>, _cwd: String) {
    focus_main_window(app);
    for arg in args {
        if let Ok(url) = Url::parse(&arg) {
            if url.scheme() == SCHEME {
                handle_deep_link(app, &url);
            }
        }
    }
}

/// Registers the plugins this module needs. Single-instance must be the first
/// plugin: a second launch (e.g. from an onyx:// link) hands off and exits.
pub fn with_plugins(builder: tauri::Builder<Wry>) -> tauri::Builder<Wry> {
    builder
        .plugin(tauri_plugin_single_instance::init(on_second_instance))
        .plugin(tauri_plugin_deep_link::init())
}

pub fn setup(app: &AppHandle) {
    #[cfg(any(target_os = "linux", target_os = "windows"))]
    if let Err(e) = app.deep_link().register_all() {
        log_backend_error(app, &format!("Failed to register onyx:// links: {e}"));
    }
    let handle = app.clone();
    app.deep_link().on_open_url(move |event| {
        for url in event.urls() {
            handle_deep_link(&handle, &url);
        }
    });
    if let Ok(Some(urls)) = app.deep_link().get_current() {
        for url in urls {
            handle_deep_link(app, &url);
        }
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    fn server() -> Url {
        Url::parse("https://onyx.example.com").unwrap()
    }

    fn link(path: &str) -> Url {
        let mut url = Url::parse("onyx://oauth-callback").unwrap();
        url.query_pairs_mut().append_pair("path", path);
        url
    }

    #[test]
    fn maps_allowed_callbacks_and_strips_the_desktop_suffix() {
        let url = callback_url(
            &server(),
            &link("/mcp/oauth/callback?code=abc&state=s1.desktop"),
        )
        .unwrap();
        assert_eq!(
            url.as_str(),
            "https://onyx.example.com/mcp/oauth/callback?code=abc&state=s1"
        );
        for path in [
            "/federated/oauth/callback?code=c&state=s.desktop",
            "/craft/v1/apps/oauth/callback?code=c&state=s.desktop",
            "/oauth-config/callback?code=c&state=s.desktop",
            "/admin/connectors/google-drive/oauth/callback?code=c&state=s.desktop",
            "/connector/oauth/callback/egnyte?code=c&state=s.desktop",
            "/mcp/oauth/callback?error=access_denied&state=s.desktop",
        ] {
            assert!(callback_url(&server(), &link(path)).is_some(), "{path}");
        }
    }

    #[test]
    fn keeps_the_server_path_prefix_origin() {
        let server = Url::parse("http://127.0.0.1:3000").unwrap();
        let url = callback_url(&server, &link("/mcp/oauth/callback?state=s.desktop")).unwrap();
        assert_eq!(url.origin(), server.origin());
    }

    #[test]
    fn rejects_other_links() {
        for path in [
            "//evil.example/mcp/oauth/callback?state=s.desktop",
            "https://evil.example/mcp/oauth/callback?state=s.desktop",
            "/\\evil.example/mcp/oauth/callback?state=s.desktop",
            "mcp/oauth/callback?state=s.desktop",
            "/app?state=s.desktop",
            "/mcp/oauth/callback/../../app?state=s.desktop",
            "/admin/connectors/../oauth/callback?state=s.desktop",
            "/admin/connectors/a.b/oauth/callback?state=s.desktop",
            "/mcp/oauth/callback?code=c&state=plain",
            "/mcp/oauth/callback?code=c",
        ] {
            assert!(callback_url(&server(), &link(path)).is_none(), "{path}");
        }
        let wrong_host = Url::parse("onyx://other?path=%2Fmcp%2Foauth%2Fcallback").unwrap();
        assert!(callback_url(&server(), &wrong_host).is_none());
        let wrong_scheme =
            Url::parse("https://oauth-callback/?path=%2Fmcp%2Foauth%2Fcallback").unwrap();
        assert!(callback_url(&server(), &wrong_scheme).is_none());
    }
}
