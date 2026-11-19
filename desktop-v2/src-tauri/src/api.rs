//! HTTP client for the Onyx server. All calls use the mobile bearer token, so the
//! local windows never hold credentials or talk to the network themselves.

use std::time::Duration;

use reqwest::{Client, Response, StatusCode};
use serde::{Deserialize, Serialize};
use serde_json::json;
use url::Url;

const USER_AGENT: &str = concat!("OnyxDesktop/", env!("CARGO_PKG_VERSION"));

pub struct Api {
    http: Client,
}

const MAX_REDIRECTS: usize = 10;

/// Redirects stay on the server's origin (scheme, host and port). A request
/// body (a password, an SSO code) must never go to another host or over plain HTTP.
fn redirect_allowed(previous: &[Url], next: &Url) -> bool {
    previous.len() <= MAX_REDIRECTS
        && previous
            .first()
            .is_some_and(|first| first.origin() == next.origin())
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchHit {
    pub document_id: String,
    pub title: String,
    pub link: Option<String>,
    pub blurb: String,
    pub source_type: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthMethods {
    pub password: bool,
    pub sso: Vec<SsoOption>,
}

/// The legacy built-in Google sign-in, configured by environment variables.
pub const LEGACY_OAUTH_AUTHORIZE: &str = "/api/auth/oauth/authorize";

/// One SSO button on the login window.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SsoOption {
    pub label: String,
    /// True when sign-in runs in the system browser, which already has the
    /// user's identity provider session; false for sign-in on the server's
    /// login page in an app window.
    pub browser: bool,
    /// The provider row this button starts (`None` for the legacy Google
    /// sign-in and for the server's login page).
    pub provider: Option<String>,
    /// Server path that starts the browser sign-in. Kept in the app: the page
    /// only names the button it was given.
    #[serde(skip)]
    pub authorize_path: Option<String>,
}

#[derive(Deserialize)]
struct SsoProvider {
    name: String,
    display_name: String,
    authorize_url: String,
    /// Set by servers whose provider sign-in takes the native-app parameters.
    #[serde(default)]
    native_app_sso: bool,
}

#[derive(Deserialize)]
struct AuthTypeResponse {
    #[serde(default)]
    multi_tenant: bool,
    #[serde(default = "default_true")]
    password_auth_enabled: bool,
    #[serde(default)]
    oauth_enabled: bool,
    #[serde(default)]
    sso_providers: Vec<SsoProvider>,
}

/// The SSO buttons for a server's `GET /api/auth/type` answer.
fn sso_options(parsed: &AuthTypeResponse) -> Vec<SsoOption> {
    // Cloud (multi-tenant) servers can require a CAPTCHA before the OAuth
    // callback, which only their login page can pass, so cloud sign-in
    // always uses that page in an app window.
    let browser_allowed = !parsed.multi_tenant;
    let mut sso: Vec<SsoOption> = parsed
        .sso_providers
        .iter()
        .map(|p| {
            // Only the OIDC router's authorize path takes the app parameters.
            let browser = browser_allowed
                && p.native_app_sso
                && p.authorize_url.starts_with("/api/auth/oidc/");
            SsoOption {
                label: p.display_name.clone(),
                browser,
                provider: Some(p.name.clone()),
                authorize_path: browser.then(|| p.authorize_url.clone()),
            }
        })
        .collect();
    // `oauth_enabled` is the legacy built-in Google sign-in. Servers that
    // list provider rows serve Google through a row instead.
    if browser_allowed && parsed.oauth_enabled && parsed.sso_providers.is_empty() {
        sso.push(SsoOption {
            label: "Continue with Google".into(),
            browser: true,
            provider: None,
            authorize_path: Some(LEGACY_OAUTH_AUTHORIZE.into()),
        });
    }
    // Cloud workspaces list no providers here; the server's login page
    // offers Google and finds a workspace's OIDC or SAML sign-in from the
    // email address.
    if parsed.multi_tenant {
        sso.push(SsoOption {
            label: "Continue with Google or SSO".into(),
            browser: false,
            provider: None,
            authorize_path: None,
        });
    }
    sso
}

fn default_true() -> bool {
    true
}

/// The web UI's default session cookie (`AUTH_COOKIE_NAME` unset).
pub const DEFAULT_SESSION_COOKIE: &str = "fastapiusersauth";

#[derive(Deserialize)]
struct CookieNameResponse {
    auth_cookie_name: Option<String>,
}

#[derive(Deserialize)]
struct VersionResponse {
    backend_version: String,
}

#[derive(Deserialize)]
struct TokenResponse {
    access_token: String,
}

#[derive(Deserialize)]
struct ChatSessionResponse {
    chat_session_id: String,
}

#[derive(Deserialize)]
struct SearchDoc {
    document_id: String,
    semantic_identifier: String,
    link: Option<String>,
    #[serde(default)]
    blurb: String,
    #[serde(default)]
    source_type: String,
}

#[derive(Deserialize)]
struct SearchResponse {
    #[serde(default)]
    search_docs: Vec<SearchDoc>,
    error: Option<String>,
}

/// Reduce user input to a server origin such as `https://cloud.onyx.app`.
pub fn normalize_server_url(input: &str) -> Result<String, String> {
    normalize(input, false)
}

/// Like `normalize_server_url`, but allows `http://` on any host: an admin
/// who sets the server in managed policy may run it on an intranet.
pub fn normalize_managed_server_url(input: &str) -> Result<String, String> {
    normalize(input, true)
}

fn normalize(input: &str, allow_any_http: bool) -> Result<String, String> {
    let trimmed = input.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        return Err("Enter a server URL.".into());
    }
    let with_scheme = if trimmed.contains("://") {
        trimmed.to_string()
    } else {
        format!("https://{trimmed}")
    };
    let url = Url::parse(&with_scheme).map_err(|_| "That is not a valid URL.".to_string())?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err("The server URL must start with http:// or https://.".into());
    }
    let Some(host) = url.host_str() else {
        return Err("The server URL must include a host.".into());
    };
    // Passwords and session tokens cross this connection: plain http is only
    // for a server on this computer.
    if url.scheme() == "http" && !allow_any_http && !is_loopback_host(host) {
        return Err(
            "Use https:// for this server. http:// only works for a server on this computer."
                .into(),
        );
    }
    Ok(url.origin().ascii_serialization())
}

fn is_loopback_host(host: &str) -> bool {
    let host = host.trim_start_matches('[').trim_end_matches(']');
    host == "localhost"
        || host.ends_with(".localhost")
        || host
            .parse::<std::net::IpAddr>()
            .is_ok_and(|ip| ip.is_loopback())
}

async fn error_detail(response: Response) -> String {
    let status = response.status();
    let body = response.text().await.unwrap_or_default();
    let detail = serde_json::from_str::<serde_json::Value>(&body)
        .ok()
        .and_then(|v| {
            v.get("detail")
                .or_else(|| v.get("message"))
                .and_then(|d| d.as_str().map(str::to_string))
        });
    match detail.as_deref() {
        Some("LOGIN_BAD_CREDENTIALS") => "Wrong email or password.".into(),
        Some("LOGIN_USER_NOT_VERIFIED") => "Verify your email address, then sign in.".into(),
        Some(d) => d.to_string(),
        None => format!("The server returned {status}."),
    }
}

impl Api {
    pub fn new() -> Self {
        let http = Client::builder()
            .user_agent(USER_AGENT)
            .connect_timeout(Duration::from_secs(10))
            .redirect(reqwest::redirect::Policy::custom(|attempt| {
                if redirect_allowed(attempt.previous(), attempt.url()) {
                    attempt.follow()
                } else {
                    attempt.error("the server redirected to another site")
                }
            }))
            .build()
            .expect("failed to build HTTP client");
        Self { http }
    }

    pub async fn version(&self, server: &str) -> Result<String, String> {
        let response = self
            .http
            .get(format!("{server}/api/version"))
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|e| format!("Could not reach {server}: {e}"))?;
        if !response.status().is_success() {
            return Err(format!(
                "{server} does not look like an Onyx server ({}).",
                response.status()
            ));
        }
        response
            .json::<VersionResponse>()
            .await
            .map(|v| v.backend_version)
            .map_err(|_| format!("{server} does not look like an Onyx server."))
    }

    /// The session cookie name from `GET /api/auth/type`. A server that
    /// answers without the field (older versions) uses the default; a failed
    /// request is an error, so a guess is never cached.
    pub async fn session_cookie_name(&self, server: &str) -> Result<String, String> {
        let response = self
            .http
            .get(format!("{server}/api/auth/type"))
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .map_err(|e| format!("Could not reach {server}: {e}"))?;
        if !response.status().is_success() {
            return Err(error_detail(response).await);
        }
        let reported = response
            .json::<CookieNameResponse>()
            .await
            .map_err(|e| format!("Unexpected response: {e}"))?
            .auth_cookie_name;
        Ok(reported
            .filter(|name| !name.is_empty())
            .unwrap_or_else(|| DEFAULT_SESSION_COOKIE.to_string()))
    }

    /// Which sign-in methods the server offers (`GET /api/auth/type`).
    pub async fn auth_methods(&self, server: &str) -> Result<AuthMethods, String> {
        let response = self
            .http
            .get(format!("{server}/api/auth/type"))
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|e| format!("Could not reach the server: {e}"))?;
        if !response.status().is_success() {
            return Err(error_detail(response).await);
        }
        let parsed = response
            .json::<AuthTypeResponse>()
            .await
            .map_err(|e| format!("Unexpected response: {e}"))?;
        Ok(AuthMethods {
            password: parsed.password_auth_enabled,
            sso: sso_options(&parsed),
        })
    }

    /// Swaps a one-time SSO code (and its PKCE verifier) for a session token.
    pub async fn mobile_sso_exchange(
        &self,
        server: &str,
        code: &str,
        verifier: &str,
    ) -> Result<String, String> {
        let response = self
            .http
            .post(format!("{server}/api/auth/mobile/sso/exchange"))
            .json(&json!({ "code": code, "code_verifier": verifier }))
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !response.status().is_success() {
            return Err(error_detail(response).await);
        }
        response
            .json::<TokenResponse>()
            .await
            .map(|t| t.access_token)
            .map_err(|e| e.to_string())
    }

    pub async fn login(&self, server: &str, email: &str, password: &str) -> Result<String, String> {
        let response = self
            .http
            .post(format!("{server}/api/auth/mobile/login"))
            .form(&[("username", email), ("password", password)])
            .timeout(Duration::from_secs(30))
            .send()
            .await
            .map_err(|e| format!("Could not reach the server: {e}"))?;
        if response.status() == StatusCode::NOT_FOUND {
            return Err(
                "This server does not support desktop sign-in. Update it to v4.2 or later.".into(),
            );
        }
        if !response.status().is_success() {
            return Err(error_detail(response).await);
        }
        response
            .json::<TokenResponse>()
            .await
            .map(|t| t.access_token)
            .map_err(|e| format!("Unexpected sign-in response: {e}"))
    }

    /// `Ok(false)` means the server rejected the stored token.
    pub async fn session_valid(&self, server: &str, token: &str) -> Result<bool, String> {
        let response = self
            .http
            .get(format!("{server}/api/me"))
            .bearer_auth(token)
            // At launch the app waits for this before showing a window.
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .map_err(|e| format!("Could not reach {server}: {e}"))?;
        match response.status() {
            s if s.is_success() => Ok(true),
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => Ok(false),
            s => Err(format!("The server returned {s}.")),
        }
    }

    /// Exchanges a valid session token for a fresh one with a new lifetime.
    pub async fn refresh(&self, server: &str, token: &str) -> Result<String, String> {
        let response = self
            .http
            .post(format!("{server}/api/auth/mobile/refresh"))
            .bearer_auth(token)
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !response.status().is_success() {
            return Err(error_detail(response).await);
        }
        response
            .json::<TokenResponse>()
            .await
            .map(|t| t.access_token)
            .map_err(|e| e.to_string())
    }

    pub async fn logout(&self, server: &str, token: &str) {
        let _ = self
            .http
            .post(format!("{server}/api/auth/mobile/logout"))
            .bearer_auth(token)
            .timeout(Duration::from_secs(10))
            .send()
            .await;
    }

    pub async fn create_chat_session(&self, server: &str, token: &str) -> Result<String, String> {
        let response = self
            .http
            .post(format!("{server}/api/chat/create-chat-session"))
            .bearer_auth(token)
            .json(&json!({ "persona_id": 0, "description": null }))
            .timeout(Duration::from_secs(30))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !response.status().is_success() {
            return Err(error_detail(response).await);
        }
        response
            .json::<ChatSessionResponse>()
            .await
            .map(|r| r.chat_session_id)
            .map_err(|e| e.to_string())
    }

    pub async fn send_message(
        &self,
        server: &str,
        token: &str,
        chat_session_id: &str,
        message: &str,
        // A follow-up goes after the chat's latest message (-1); a new chat starts at the root.
        follow_up: bool,
    ) -> Result<Response, String> {
        // Bounds the wait for the response headers only; the streamed answer
        // that follows has its own idle timeout in `ask::run`.
        let request = self
            .http
            .post(format!("{server}/api/chat/send-chat-message"))
            .bearer_auth(token)
            .json(&json!({
                "message": message,
                "chat_session_id": chat_session_id,
                "parent_message_id": if follow_up { json!(-1) } else { json!(null) },
                "file_descriptors": [],
                "deep_research": false,
                "origin": "unknown",
            }))
            .send();
        let response = tokio::time::timeout(Duration::from_secs(120), request)
            .await
            .map_err(|_| "The server did not start answering.".to_string())?
            .map_err(|e| e.to_string())?;
        if !response.status().is_success() {
            return Err(error_detail(response).await);
        }
        Ok(response)
    }

    pub async fn search(
        &self,
        server: &str,
        token: &str,
        query: &str,
    ) -> Result<Vec<SearchHit>, String> {
        let response = self
            .http
            .post(format!("{server}/api/search/send-search-message"))
            .bearer_auth(token)
            .json(&json!({
                "search_query": query,
                "num_hits": 15,
                "include_content": false,
                "stream": false,
            }))
            .timeout(Duration::from_secs(60))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if response.status() == StatusCode::NOT_FOUND || response.status() == StatusCode::FORBIDDEN
        {
            return Err("Knowledge search is not available on this server.".into());
        }
        if !response.status().is_success() {
            return Err(error_detail(response).await);
        }
        let parsed = response
            .json::<SearchResponse>()
            .await
            .map_err(|e| format!("Unexpected search response: {e}"))?;
        if let Some(error) = parsed.error {
            return Err(error);
        }
        Ok(parsed
            .search_docs
            .into_iter()
            .map(|doc| SearchHit {
                document_id: doc.document_id,
                title: doc.semantic_identifier,
                link: doc.link,
                blurb: doc.blurb,
                source_type: doc.source_type,
            })
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    use super::{
        normalize_managed_server_url, normalize_server_url, redirect_allowed, sso_options, Api,
        AuthTypeResponse,
    };
    use url::Url;

    /// A local HTTP server that answers every request with `response(path)`
    /// and counts the requests. Returns its base URL.
    fn serve(response: impl Fn(&str) -> String + Send + 'static) -> (String, Arc<AtomicUsize>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let hits = Arc::new(AtomicUsize::new(0));
        let counter = hits.clone();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { return };
                counter.fetch_add(1, Ordering::SeqCst);
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut request_line = String::new();
                let _ = reader.read_line(&mut request_line);
                let path = request_line.split(' ').nth(1).unwrap_or("/").to_string();
                // The headers end at the first empty line; the body is not needed.
                let mut line = String::new();
                while reader.read_line(&mut line).is_ok_and(|n| n > 2) {
                    line.clear();
                }
                let _ = stream.write_all(response(&path).as_bytes());
            }
        });
        (base, hits)
    }

    fn redirect_to(location: &str) -> String {
        format!("HTTP/1.1 307 Temporary Redirect\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    }

    const OK: &str = "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok";

    fn post(url: &str) -> Result<reqwest::StatusCode, reqwest::Error> {
        tauri::async_runtime::block_on(async {
            Api::new()
                .http
                .post(url)
                .body("password=secret")
                .send()
                .await
                .map(|r| r.status())
        })
    }

    #[test]
    fn redirects_to_another_origin_are_not_followed() {
        let (other, other_hits) = serve(|_| OK.to_string());
        let target = format!("{other}/steal");
        let (server, _) = serve(move |_| redirect_to(&target));
        assert!(post(&format!("{server}/api/auth/mobile/login")).is_err());
        assert_eq!(other_hits.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn redirects_on_the_same_origin_are_followed() {
        let (server, hits) = serve(|path| {
            if path == "/start" {
                redirect_to("/end")
            } else {
                OK.to_string()
            }
        });
        assert_eq!(
            post(&format!("{server}/start")).unwrap(),
            reqwest::StatusCode::OK
        );
        assert_eq!(hits.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn redirect_rule() {
        let url = |s: &str| Url::parse(s).unwrap();
        let start = [url("https://onyx.corp/api/x")];
        assert!(redirect_allowed(&start, &url("https://onyx.corp/api/y")));
        assert!(!redirect_allowed(&start, &url("https://evil.example/")));
        assert!(!redirect_allowed(&start, &url("http://onyx.corp/api/y")));
        assert!(!redirect_allowed(&start, &url("https://onyx.corp:8443/")));
        let long = vec![url("https://onyx.corp/"); 11];
        assert!(!redirect_allowed(&long, &url("https://onyx.corp/")));
    }

    fn options(json: &str) -> Vec<(String, bool, Option<String>)> {
        let parsed: AuthTypeResponse = serde_json::from_str(json).unwrap();
        sso_options(&parsed)
            .into_iter()
            .map(|o| (o.label, o.browser, o.authorize_path))
            .collect()
    }

    #[test]
    fn provider_rows_use_the_browser_only_when_the_server_says_so() {
        let row = |flag: &str| {
            format!(
                r#"{{"oauth_enabled":true,"sso_providers":[{{"name":"google","display_name":"Continue with Google","authorize_url":"/api/auth/oidc/google/authorize"{flag}}}]}}"#
            )
        };
        assert_eq!(
            options(&row(r#","native_app_sso":true"#)),
            vec![(
                "Continue with Google".into(),
                true,
                Some("/api/auth/oidc/google/authorize".into())
            )]
        );
        // An older server: its provider routes ignore the app parameters.
        assert_eq!(
            options(&row("")),
            vec![("Continue with Google".into(), false, None)]
        );
    }

    #[test]
    fn saml_and_cloud_stay_in_the_window() {
        let saml = r#"{"sso_providers":[{"name":"okta","display_name":"Okta","authorize_url":"/api/auth/saml/okta/authorize","native_app_sso":true}]}"#;
        assert_eq!(options(saml), vec![("Okta".into(), false, None)]);
        let cloud = r#"{"multi_tenant":true,"oauth_enabled":true}"#;
        assert_eq!(
            options(cloud),
            vec![("Continue with Google or SSO".into(), false, None)]
        );
    }

    #[test]
    fn legacy_google_uses_the_browser() {
        assert_eq!(
            options(r#"{"oauth_enabled":true}"#),
            vec![(
                "Continue with Google".into(),
                true,
                Some(super::LEGACY_OAUTH_AUTHORIZE.into())
            )]
        );
    }

    #[test]
    fn normalizes_server_urls() {
        assert_eq!(
            normalize_server_url("http://localhost:3000/app/").unwrap(),
            "http://localhost:3000"
        );
        assert_eq!(
            normalize_server_url("cloud.onyx.app").unwrap(),
            "https://cloud.onyx.app"
        );
        assert!(normalize_server_url("ftp://example.com").is_err());
        assert_eq!(
            normalize_server_url("http://127.0.0.1:8080").unwrap(),
            "http://127.0.0.1:8080"
        );
        assert!(normalize_server_url("http://[::1]:3000").is_ok());
        assert!(normalize_server_url("http://onyx.example.com").is_err());
        assert_eq!(
            normalize_managed_server_url("http://onyx.corp.internal/").unwrap(),
            "http://onyx.corp.internal"
        );
        assert!(normalize_managed_server_url("ftp://onyx.corp.internal").is_err());
        assert!(normalize_server_url("  ").is_err());
    }
}
