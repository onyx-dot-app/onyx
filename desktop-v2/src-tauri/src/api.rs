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
    /// The server's OAuth sign-in (`/api/auth/oauth/authorize`) is configured,
    /// so SSO can run in the system browser.
    pub browser_sso: bool,
}

/// One SSO button on the login window.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SsoOption {
    pub label: String,
    /// True for the server's built-in Google sign-in, which runs in the
    /// system browser; false for sign-in on the server's own login page in an
    /// app window (provider rows, and cloud workspaces).
    pub browser: bool,
}

#[derive(Deserialize)]
struct SsoProvider {
    display_name: String,
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
    if url.scheme() == "http" && !is_loopback_host(host) {
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
        // `oauth_enabled` is the built-in Google sign-in, the only flow with
        // the mobile parameters the browser sign-in needs. Provider rows (OIDC,
        // SAML) have their own routes and use the in-app window instead.
        // Cloud (multi-tenant) servers can require a CAPTCHA before the OAuth
        // callback, which only their login page can pass, so cloud sign-in
        // always uses that page in an app window.
        let browser_sso =
            parsed.oauth_enabled && parsed.sso_providers.is_empty() && !parsed.multi_tenant;
        let mut sso: Vec<SsoOption> = parsed
            .sso_providers
            .into_iter()
            .map(|p| SsoOption {
                label: p.display_name,
                browser: false,
            })
            .collect();
        if browser_sso {
            sso.push(SsoOption {
                label: "Continue with Google".into(),
                browser: true,
            });
        }
        // Cloud workspaces list no providers here; the server's login page
        // offers Google and finds a workspace's OIDC or SAML sign-in from the
        // email address.
        if parsed.multi_tenant {
            sso.push(SsoOption {
                label: "Continue with Google or SSO".into(),
                browser: false,
            });
        }
        Ok(AuthMethods {
            password: parsed.password_auth_enabled,
            sso,
            browser_sso,
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
                "parent_message_id": null,
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
    use super::normalize_server_url;

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
        assert!(normalize_server_url("  ").is_err());
    }
}
