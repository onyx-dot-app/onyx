//! HTTP client for the Onyx server. All calls use the mobile bearer token, so the
//! local windows never hold credentials or talk to the network themselves.

use std::time::Duration;

use reqwest::{Client, Response, StatusCode};
use serde::Deserialize;
use url::Url;

const USER_AGENT: &str = concat!("OnyxDesktop/", env!("CARGO_PKG_VERSION"));

pub struct Api {
    http: Client,
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

    pub async fn logout(&self, server: &str, token: &str) {
        let _ = self
            .http
            .post(format!("{server}/api/auth/mobile/logout"))
            .bearer_auth(token)
            .timeout(Duration::from_secs(10))
            .send()
            .await;
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
