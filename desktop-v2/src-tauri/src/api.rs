//! HTTP client for the Onyx server. All calls use the mobile bearer token, so the
//! local windows never hold credentials or talk to the network themselves.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use reqwest::{Client, Response, StatusCode};
use serde::{Deserialize, Serialize};
use serde_json::json;
use url::Url;

use crate::reachability::{self, Unreachable};

/// `version` is the app version from the Tauri config, which builds set;
/// the Cargo.toml version is only a placeholder.
fn user_agent(version: &str) -> String {
    format!("OnyxDesktop/{version}")
}

/// The `origin` of launcher questions (the server's `MessageOrigin`).
const ORIGIN: &str = "desktop";
const FALLBACK_ORIGIN: &str = "unknown";

pub struct Api {
    http: Client,
    /// Follows no redirects: any answer from the web UI counts, wherever it points.
    probe: Client,
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

/// An agent (persona) the user can chat with.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Agent {
    pub id: i64,
    pub name: String,
    pub description: String,
}

#[derive(Deserialize)]
struct AgentRow {
    id: i64,
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    builtin_persona: bool,
}

/// The server's default agent (`ask::DEFAULT_AGENT_ID`).
const DEFAULT_AGENT_ID: i64 = 0;

/// The agents in a `GET /api/persona` answer, as the web chat offers them.
/// The server already leaves out agents the user cannot use. Built-in agents
/// other than the default one are left out, and the default one too when
/// "Always Start with an Agent" is on. Rows the app cannot read are skipped,
/// so one odd agent does not hide the others.
fn parse_agents(body: &str, default_disabled: bool) -> Result<Vec<Agent>, String> {
    let rows: Vec<serde_json::Value> =
        serde_json::from_str(body).map_err(|e| format!("Unexpected agent list: {e}"))?;
    Ok(rows
        .into_iter()
        .filter_map(|row| serde_json::from_value::<AgentRow>(row).ok())
        .filter(|row| !row.name.trim().is_empty())
        .filter(|row| {
            if row.id == DEFAULT_AGENT_ID {
                !default_disabled
            } else {
                !row.builtin_persona
            }
        })
        .map(|row| Agent {
            id: row.id,
            name: row.name,
            description: row.description.unwrap_or_default(),
        })
        .collect())
}

/// A file uploaded for the next question.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AttachedFile {
    /// The user file row.
    pub user_file_id: String,
    /// The stored file the chat reads.
    pub file_id: String,
    pub name: String,
    /// `image`, `document`, `plain_text` or `tabular`.
    pub chat_file_type: String,
}

impl AttachedFile {
    /// The `file_descriptors` entry of `send-chat-message`.
    fn descriptor(&self) -> serde_json::Value {
        json!({
            "id": self.file_id,
            "type": self.chat_file_type,
            "name": self.name,
            "user_file_id": self.user_file_id,
        })
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct UserFileRow {
    pub id: String,
    file_id: String,
    name: String,
    pub status: String,
    chat_file_type: String,
}

impl UserFileRow {
    pub fn attached(self) -> AttachedFile {
        AttachedFile {
            user_file_id: self.id,
            file_id: self.file_id,
            name: self.name,
            chat_file_type: self.chat_file_type,
        }
    }
}

#[derive(Debug, PartialEq)]
pub enum FileState {
    Ready,
    Processing,
    Failed,
}

/// The web chat sends a file once its processing is complete. A status this
/// app does not know yet counts as processing, within the caller's time limit.
pub fn file_state(status: &str) -> FileState {
    match status {
        "COMPLETED" | "SKIPPED" => FileState::Ready,
        "FAILED" | "CANCELED" | "DELETING" => FileState::Failed,
        _ => FileState::Processing,
    }
}

#[derive(Deserialize)]
struct RejectedRow {
    file_name: String,
    reason: String,
}

#[derive(Deserialize)]
struct UploadResponse {
    #[serde(default)]
    user_files: Vec<UserFileRow>,
    #[serde(default)]
    rejected_files: Vec<RejectedRow>,
}

/// The one file of an upload answer, or why the server did not take it.
fn upload_outcome(body: &str, name: &str) -> Result<UserFileRow, String> {
    let parsed: UploadResponse =
        serde_json::from_str(body).map_err(|e| format!("Unexpected upload response: {e}"))?;
    if let Some(rejected) = parsed.rejected_files.into_iter().next() {
        return Err(format!(
            "Could not attach {}: {}.",
            rejected.file_name,
            rejected.reason.trim_end_matches('.')
        ));
    }
    parsed
        .user_files
        .into_iter()
        .next()
        .ok_or_else(|| format!("The server did not accept {name}."))
}

#[derive(Deserialize)]
struct SettingsResponse {
    #[serde(default)]
    user_file_max_upload_size_mb: Option<u64>,
    #[serde(default)]
    disable_default_assistant: Option<bool>,
}

/// The parts of `GET /api/settings` the launcher uses.
#[derive(Debug, Default, Clone, PartialEq)]
pub struct ServerSettings {
    /// The upload size limit for chat files, if the server sets one.
    pub upload_limit_bytes: Option<u64>,
    /// "Always Start with an Agent": the default agent cannot start a chat.
    pub default_agent_disabled: bool,
}

fn parse_settings(body: &str) -> Option<ServerSettings> {
    let parsed: SettingsResponse = serde_json::from_str(body).ok()?;
    Some(ServerSettings {
        upload_limit_bytes: parsed
            .user_file_max_upload_size_mb
            .filter(|mb| *mb > 0)
            .map(|mb| mb.saturating_mul(1024 * 1024)),
        default_agent_disabled: parsed.disable_default_assistant.unwrap_or(false),
    })
}

/// The largest file the app uploads, whatever the server allows, because the
/// file is in memory while it uploads. The server's own ceiling defaults to this.
pub const MAX_UPLOAD_BYTES: u64 = 250 * 1024 * 1024;

/// The smaller of the app's limit and the server's.
pub fn upload_limit(settings: Option<&ServerSettings>) -> u64 {
    settings
        .and_then(|s| s.upload_limit_bytes)
        .map_or(MAX_UPLOAD_BYTES, |limit| limit.min(MAX_UPLOAD_BYTES))
}

/// A user file id is a UUID; anything else must not reach a URL path.
fn is_file_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 64 && id.chars().all(|c| c.is_ascii_hexdigit() || c == '-')
}

/// `multipart/form-data` with one `files` part, as a browser sends it.
fn multipart_body(boundary: &str, name: &str, mime: &str, bytes: &[u8]) -> Vec<u8> {
    // Browsers percent-encode these in a part's file name.
    let safe_name = name
        .replace('"', "%22")
        .replace('\r', "%0D")
        .replace('\n', "%0A");
    let safe_mime = if mime.is_empty() || mime.contains(['\r', '\n']) {
        "application/octet-stream"
    } else {
        mime
    };
    let head = format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{safe_name}\"\r\nContent-Type: {safe_mime}\r\n\r\n"
    );
    let tail = format!("\r\n--{boundary}--\r\n");
    // Sized once, so a large file is copied only one time.
    let mut body = Vec::with_capacity(head.len() + bytes.len() + tail.len());
    body.extend_from_slice(head.as_bytes());
    body.extend_from_slice(bytes);
    body.extend_from_slice(tail.as_bytes());
    body
}

const UPLOAD_CHUNK: usize = 64 * 1024;

/// Sends `body` in chunks and fails once `cancelled` is set. The server then
/// gets an incomplete request and stores no file.
fn cancellable_body(body: Vec<u8>, cancelled: Arc<AtomicBool>) -> reqwest::Body {
    reqwest::Body::wrap_stream(body_chunks(body, cancelled))
}

fn body_chunks(
    body: Vec<u8>,
    cancelled: Arc<AtomicBool>,
) -> impl futures_util::Stream<Item = Result<Vec<u8>, std::io::Error>> {
    futures_util::stream::unfold(0, move |at| {
        let next = if at >= body.len() {
            None
        } else if cancelled.load(Ordering::SeqCst) {
            let error = std::io::Error::other("The upload was cancelled.");
            Some((Err(error), body.len()))
        } else {
            let end = body.len().min(at + UPLOAD_CHUNK);
            Some((Ok(body[at..end].to_vec()), end))
        };
        std::future::ready(next)
    })
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
    /// Google sign-in, which shows the Google logo.
    pub google: bool,
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
    #[serde(default)]
    provider_type: String,
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
                google: p.provider_type == "GOOGLE_OAUTH",
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
            google: true,
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
            google: false,
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
    // Only the origin is kept, so credentials in the URL would be lost.
    if !url.username().is_empty() || url.password().is_some() {
        return Err("Remove the user name and password from the server URL.".into());
    }
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

/// Windows, and Linux without nss-myhostname, can send `*.localhost` names to
/// DNS, which may answer with a remote address. macOS keeps the name rule.
const LOCALHOST_SUBDOMAINS_ALLOWED: bool = cfg!(target_os = "macos");

/// Whether a server saved by the user (`config.json`) is still allowed. One
/// saved before `*.localhost` lost plain `http://` on Windows and Linux is not.
pub fn saved_server_allowed(server: &str) -> bool {
    let Ok(url) = Url::parse(server) else {
        return true;
    };
    !(url.scheme() == "http"
        && url
            .host_str()
            .is_some_and(|host| host.ends_with(".localhost"))
        && !LOCALHOST_SUBDOMAINS_ALLOWED)
}

fn is_loopback_host(host: &str) -> bool {
    let host = host.trim_start_matches('[').trim_end_matches(']');
    host == "localhost"
        || (LOCALHOST_SUBDOMAINS_ALLOWED && host.ends_with(".localhost"))
        || host
            .parse::<std::net::IpAddr>()
            .is_ok_and(|ip| ip.is_loopback())
}

/// The web UI's Next.js `/api` route answers with this text when no proxy
/// sends `/api` to the API server.
const API_NOT_ROUTED_TEXT: &str = "only available in development mode";

fn api_not_routed(status: StatusCode, body: &str) -> bool {
    status == StatusCode::NOT_FOUND && body.contains(API_NOT_ROUTED_TEXT)
}

/// The backend version in a `GET /api/version` answer. Any answer other than
/// the Onyx API's JSON means the address is not a working Onyx server.
fn parse_version(status: StatusCode, body: &str) -> Result<String, Unreachable> {
    if let Some(reason) = Unreachable::from_status(status) {
        return Err(reason);
    }
    if api_not_routed(status, body) {
        return Err(Unreachable::ApiNotRouted);
    }
    if !status.is_success() {
        return Err(Unreachable::NotOnyx);
    }
    serde_json::from_str::<VersionResponse>(body)
        .map(|v| v.backend_version)
        .map_err(|_| Unreachable::NotOnyx)
}

/// Why a request failed. A redirect to another site is an answer from
/// something other than the Onyx server.
fn request_failed(error: &reqwest::Error) -> Unreachable {
    if error.is_redirect() {
        return Unreachable::NotOnyx;
    }
    Unreachable::from_reqwest(error).unwrap_or(Unreachable::Unknown)
}

/// The most of a short answer (version, sign-in settings, an error) that is
/// read. A longer one is not from the Onyx API.
const MAX_SHORT_BODY_BYTES: usize = 64 * 1024;

/// The body of a short answer, or `None` if it is longer than
/// `MAX_SHORT_BODY_BYTES`. Reading stops at the limit, with or without a
/// `Content-Length`.
async fn read_short_body(mut response: Response) -> Result<Option<String>, reqwest::Error> {
    if response
        .content_length()
        .is_some_and(|len| len > MAX_SHORT_BODY_BYTES as u64)
    {
        return Ok(None);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await? {
        if body.len() + chunk.len() > MAX_SHORT_BODY_BYTES {
            return Ok(None);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(Some(String::from_utf8_lossy(&body).into_owned()))
}

/// The JSON of a successful short answer. A body that does not come in is a
/// connection error; a body that is not the expected JSON is not Onyx.
async fn read_json<T: serde::de::DeserializeOwned>(
    server: &str,
    response: Response,
) -> Result<T, String> {
    let body = read_short_body(response)
        .await
        .map_err(|e| reachability::describe(server, &e))?;
    body.and_then(|body| serde_json::from_str::<T>(&body).ok())
        .ok_or_else(|| Unreachable::NotOnyx.message(server))
}

async fn error_detail(server: &str, response: Response) -> String {
    let status = response.status();
    let body = read_short_body(response)
        .await
        .ok()
        .flatten()
        .unwrap_or_default();
    if api_not_routed(status, &body) {
        return Unreachable::ApiNotRouted.message(server);
    }
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

/// A connection error or a 5xx status fails; any other answer passes.
async fn probe(client: &Client, url: &str) -> Result<(), Unreachable> {
    let response = client
        .get(url)
        .timeout(Duration::from_secs(10))
        .send()
        .await
        .map_err(|e| request_failed(&e))?;
    match Unreachable::from_status(response.status()) {
        Some(reason) => Err(reason),
        None => Ok(()),
    }
}

impl Api {
    /// Fails if the TLS library cannot start (for example, a broken OpenSSL
    /// configuration).
    pub fn new(version: &str) -> Result<Self, String> {
        let user_agent = user_agent(version);
        let http = Client::builder()
            .user_agent(&user_agent)
            .connect_timeout(Duration::from_secs(10))
            .redirect(reqwest::redirect::Policy::custom(|attempt| {
                if redirect_allowed(attempt.previous(), attempt.url()) {
                    attempt.follow()
                } else {
                    attempt.error("the server redirected to another site")
                }
            }))
            .build()
            .map_err(|e| e.to_string())?;
        let probe = Client::builder()
            .user_agent(user_agent)
            .connect_timeout(Duration::from_secs(10))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| e.to_string())?;
        Ok(Self { http, probe })
    }

    /// The backend version, for the onboarding check.
    pub async fn version(&self, server: &str) -> Result<String, String> {
        self.backend_version(server, Duration::from_secs(15))
            .await
            .map_err(|reason| reason.message(server))
    }

    async fn backend_version(
        &self,
        server: &str,
        timeout: Duration,
    ) -> Result<String, Unreachable> {
        let response = self
            .http
            .get(format!("{server}/api/version"))
            .timeout(timeout)
            .send()
            .await
            .map_err(|e| request_failed(&e))?;
        let status = response.status();
        // A 5xx is the answer, whatever its body does.
        if let Some(reason) = Unreachable::from_status(status) {
            return Err(reason);
        }
        let body = read_short_body(response)
            .await
            .map_err(|e| request_failed(&e))?
            .ok_or(Unreachable::NotOnyx)?;
        parse_version(status, &body)
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
            .map_err(|e| reachability::describe(server, &e))?;
        if !response.status().is_success() {
            return Err(error_detail(server, response).await);
        }
        let reported = read_json::<CookieNameResponse>(server, response)
            .await?
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
            .map_err(|e| reachability::describe(server, &e))?;
        if !response.status().is_success() {
            return Err(error_detail(server, response).await);
        }
        let parsed = read_json::<AuthTypeResponse>(server, response).await?;
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
            return Err(error_detail(server, response).await);
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
            .map_err(|e| reachability::describe(server, &e))?;
        if response.status() == StatusCode::NOT_FOUND {
            let body = read_short_body(response)
                .await
                .ok()
                .flatten()
                .unwrap_or_default();
            if api_not_routed(StatusCode::NOT_FOUND, &body) {
                return Err(Unreachable::ApiNotRouted.message(server));
            }
            return Err(
                "This server does not support desktop sign-in. Update it to v4.2 or later.".into(),
            );
        }
        if !response.status().is_success() {
            return Err(error_detail(server, response).await);
        }
        response
            .json::<TokenResponse>()
            .await
            .map(|t| t.access_token)
            .map_err(|e| format!("Unexpected sign-in response: {e}"))
    }

    /// Whether the Onyx API answers `GET /api/version` with its JSON, and
    /// the web UI (`GET /`) answers without a 5xx error. Behind a proxy they
    /// are separate servers, so one can fail while the other answers. No
    /// sign-in needed.
    pub async fn health(&self, server: &str) -> Result<(), Unreachable> {
        self.backend_version(server, Duration::from_secs(10))
            .await?;
        probe(&self.probe, &format!("{server}/")).await
    }

    /// `Ok(false)` means the server rejected the stored token.
    pub async fn session_valid(&self, server: &str, token: &str) -> Result<bool, Unreachable> {
        let response = self
            .http
            .get(format!("{server}/api/me"))
            .bearer_auth(token)
            // At launch the app waits for this before showing a window.
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .map_err(|e| Unreachable::from_reqwest(&e).unwrap_or(Unreachable::Unknown))?;
        match response.status() {
            s if s.is_success() => Ok(true),
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => Ok(false),
            s => Err(Unreachable::ServerError { status: s.as_u16() }),
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
            return Err(error_detail(server, response).await);
        }
        response
            .json::<TokenResponse>()
            .await
            .map(|t| t.access_token)
            .map_err(|e| e.to_string())
    }

    /// Ends the session on the server. Returns false if the request did not
    /// reach a working server (no answer, or a 5xx), so it can be tried again.
    pub async fn logout(&self, server: &str, token: &str) -> bool {
        match self
            .http
            .post(format!("{server}/api/auth/mobile/logout"))
            .bearer_auth(token)
            .timeout(Duration::from_secs(10))
            .send()
            .await
        {
            Ok(response) => !response.status().is_server_error(),
            Err(e) => {
                log::warn!("server sign-out failed: {e}");
                false
            }
        }
    }

    /// The agents the user can chat with (`GET /api/persona`). A server
    /// without the list answers with none.
    pub async fn list_agents(
        &self,
        server: &str,
        token: &str,
        default_disabled: bool,
    ) -> Result<Vec<Agent>, String> {
        let response = self
            .http
            .get(format!("{server}/api/persona"))
            .bearer_auth(token)
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if matches!(
            response.status(),
            StatusCode::NOT_FOUND | StatusCode::METHOD_NOT_ALLOWED
        ) {
            return Ok(Vec::new());
        }
        if !response.status().is_success() {
            return Err(error_detail(server, response).await);
        }
        let body = response.text().await.map_err(|e| e.to_string())?;
        parse_agents(&body, default_disabled)
    }

    /// The settings the launcher uses; `None` if the server could not say.
    pub async fn server_settings(&self, server: &str, token: &str) -> Option<ServerSettings> {
        let response = self
            .http
            .get(format!("{server}/api/settings"))
            .bearer_auth(token)
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .ok()?;
        if !response.status().is_success() {
            return None;
        }
        parse_settings(&response.text().await.ok()?)
    }

    /// Deletes one of the user's files (`DELETE /api/user/projects/file/{id}`,
    /// as the web app does). A file that is already gone counts as deleted.
    pub async fn delete_user_file(
        &self,
        server: &str,
        token: &str,
        id: &str,
    ) -> Result<(), String> {
        if !is_file_id(id) {
            return Err("Not a file id.".into());
        }
        let response = self
            .http
            .delete(format!("{server}/api/user/projects/file/{id}"))
            .bearer_auth(token)
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if response.status().is_success() || response.status() == StatusCode::NOT_FOUND {
            return Ok(());
        }
        Err(error_detail(server, response).await)
    }

    /// Uploads one chat file (`POST /api/user/projects/file/upload`, as the
    /// web chat does). The file can still be processing when this returns.
    /// Setting `cancelled` stops the request while the file is still being sent.
    pub async fn upload_file(
        &self,
        server: &str,
        token: &str,
        name: &str,
        mime: &str,
        bytes: &[u8],
        cancelled: Arc<AtomicBool>,
    ) -> Result<UserFileRow, String> {
        use rand::distributions::{Alphanumeric, DistString};
        let boundary = format!(
            "----OnyxDesktop{}",
            Alphanumeric.sample_string(&mut rand::thread_rng(), 24)
        );
        let body = multipart_body(&boundary, name, mime, bytes);
        let length = body.len();
        let response = self
            .http
            .post(format!("{server}/api/user/projects/file/upload"))
            .bearer_auth(token)
            .header(
                reqwest::header::CONTENT_TYPE,
                format!("multipart/form-data; boundary={boundary}"),
            )
            .header(reqwest::header::CONTENT_LENGTH, length)
            .body(cancellable_body(body, cancelled))
            .timeout(Duration::from_secs(300))
            .send()
            .await
            .map_err(|e| format!("Could not upload {name}: {e}"))?;
        if response.status() == StatusCode::PAYLOAD_TOO_LARGE {
            return Err(format!("{name} is too large for this server."));
        }
        if !response.status().is_success() {
            return Err(error_detail(server, response).await);
        }
        let body = response.text().await.map_err(|e| e.to_string())?;
        upload_outcome(&body, name)
    }

    /// The current rows of the user's files (`POST /api/user/projects/file/statuses`).
    pub async fn file_statuses(
        &self,
        server: &str,
        token: &str,
        ids: &[String],
    ) -> Result<Vec<UserFileRow>, String> {
        let response = self
            .http
            .post(format!("{server}/api/user/projects/file/statuses"))
            .bearer_auth(token)
            .json(&json!({ "file_ids": ids }))
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !response.status().is_success() {
            return Err(error_detail(server, response).await);
        }
        response
            .json::<Vec<UserFileRow>>()
            .await
            .map_err(|e| format!("Unexpected file status response: {e}"))
    }

    /// Waits until the server has processed an uploaded file, as the web chat
    /// does before it sends one.
    pub async fn wait_for_file(
        &self,
        server: &str,
        token: &str,
        mut row: UserFileRow,
        is_current: &(dyn Fn() -> bool + Sync),
    ) -> Result<AttachedFile, String> {
        const POLL: Duration = Duration::from_secs(1);
        const LIMIT: Duration = Duration::from_secs(300);
        let started = std::time::Instant::now();
        let mut failed_polls = 0;
        loop {
            match file_state(&row.status) {
                FileState::Ready => return Ok(row.attached()),
                FileState::Failed => {
                    return Err(format!("The server could not process {}.", row.name))
                }
                FileState::Processing => {}
            }
            if started.elapsed() > LIMIT {
                return Err(format!(
                    "{} is still processing. Try attaching it again later.",
                    row.name
                ));
            }
            tokio::time::sleep(POLL).await;
            if !is_current() {
                return Err("Signed out.".into());
            }
            match self
                .file_statuses(server, token, std::slice::from_ref(&row.id))
                .await
            {
                Ok(rows) => {
                    failed_polls = 0;
                    row = rows
                        .into_iter()
                        .find(|r| r.id == row.id)
                        .ok_or_else(|| format!("{} was removed from your files.", row.name))?;
                }
                // A short network problem does not fail the file.
                Err(e) => {
                    failed_polls += 1;
                    if failed_polls >= 5 {
                        return Err(e);
                    }
                }
            }
        }
    }

    pub async fn create_chat_session(
        &self,
        server: &str,
        token: &str,
        persona_id: i64,
    ) -> Result<String, String> {
        let response = self
            .http
            .post(format!("{server}/api/chat/create-chat-session"))
            .bearer_auth(token)
            .json(&json!({ "persona_id": persona_id, "description": null }))
            .timeout(Duration::from_secs(30))
            .send()
            .await
            .map_err(|e| reachability::describe(server, &e))?;
        if !response.status().is_success() {
            return Err(error_detail(server, response).await);
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
        files: &[AttachedFile],
    ) -> Result<Response, SendError> {
        let file_descriptors: Vec<serde_json::Value> =
            files.iter().map(AttachedFile::descriptor).collect();
        let mut body = json!({
            "message": message,
            "chat_session_id": chat_session_id,
            "parent_message_id": if follow_up { json!(-1) } else { json!(null) },
            "file_descriptors": file_descriptors,
            "deep_research": false,
            "origin": ORIGIN,
        });
        let response = self.post_message(server, token, &body).await?;
        // Servers older than the desktop origin reject it before they take the
        // question; ask again as an unknown client.
        let response = if response.status() == StatusCode::UNPROCESSABLE_ENTITY {
            body["origin"] = json!(FALLBACK_ORIGIN);
            self.post_message(server, token, &body).await?
        } else {
            response
        };
        if !response.status().is_success() {
            // The server answered and refused the question (for example a usage limit).
            return Err(SendError {
                message: error_detail(server, response).await,
                not_sent: true,
            });
        }
        Ok(response)
    }

    async fn post_message(
        &self,
        server: &str,
        token: &str,
        body: &serde_json::Value,
    ) -> Result<Response, SendError> {
        // Bounds the wait for the response headers only; the streamed answer
        // that follows has its own idle timeout in `ask::run`.
        let request = self
            .http
            .post(format!("{server}/api/chat/send-chat-message"))
            .bearer_auth(token)
            .json(body)
            .send();
        tokio::time::timeout(Duration::from_secs(120), request)
            .await
            .map_err(|_| SendError {
                message: "The server did not start answering.".into(),
                not_sent: false,
            })?
            .map_err(|e| SendError {
                message: reachability::describe(server, &e),
                // A connection that never opened carried no question.
                not_sent: e.is_connect(),
            })
    }

    pub async fn search(
        &self,
        server: &str,
        token: &str,
        query: &str,
        // Source types (`google_drive`, `slack`); empty searches every source.
        sources: &[String],
    ) -> Result<Vec<SearchHit>, String> {
        let filters = if sources.is_empty() {
            json!(null)
        } else {
            json!({ "source_type": sources })
        };
        let response = self
            .http
            .post(format!("{server}/api/search/send-search-message"))
            .bearer_auth(token)
            .json(&json!({
                "search_query": query,
                "filters": filters,
                "num_hits": 15,
                "include_content": false,
                "stream": false,
            }))
            .timeout(Duration::from_secs(60))
            .send()
            .await
            .map_err(|e| reachability::describe(server, &e))?;
        if response.status() == StatusCode::NOT_FOUND || response.status() == StatusCode::FORBIDDEN
        {
            return Err("Knowledge search is not available on this server.".into());
        }
        if !response.status().is_success() {
            return Err(error_detail(server, response).await);
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

/// Why `send_message` failed, and whether the server surely did not take
/// the question (so its attachments can go back to the user).
pub struct SendError {
    pub message: String,
    pub not_sent: bool,
}

#[cfg(test)]
mod tests {
    use std::io::{BufRead, BufReader, Read, Write};
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};

    use super::{
        body_chunks, file_state, is_file_id, multipart_body, normalize_managed_server_url,
        normalize_server_url, parse_agents, parse_settings, parse_version, redirect_allowed,
        saved_server_allowed, sso_options, upload_limit, upload_outcome, user_agent, Agent, Api,
        AttachedFile, AuthTypeResponse, FileState, ServerSettings, MAX_UPLOAD_BYTES,
    };
    use crate::reachability::Unreachable;
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
            Api::new("0.0.0-test")
                .unwrap()
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

    /// A send-chat-message endpoint that rejects origins it does not know, as
    /// a server's request validation does. Returns the origins it received.
    fn chat_server(known: &'static [&'static str]) -> (String, Arc<Mutex<Vec<String>>>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let origins = Arc::new(Mutex::new(Vec::new()));
        let seen = origins.clone();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { return };
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut length = 0;
                let mut line = String::new();
                while reader.read_line(&mut line).is_ok_and(|n| n > 2) {
                    let header = line.to_ascii_lowercase();
                    if let Some(value) = header.strip_prefix("content-length:") {
                        length = value.trim().parse().unwrap_or(0);
                    }
                    line.clear();
                }
                let mut body = vec![0; length];
                let _ = reader.read_exact(&mut body);
                let body: serde_json::Value = serde_json::from_slice(&body).unwrap_or_default();
                let origin = body["origin"].as_str().unwrap_or_default().to_string();
                let status = if known.contains(&origin.as_str()) {
                    "200 OK"
                } else {
                    "422 Unprocessable Entity"
                };
                seen.lock().unwrap().push(origin);
                let response = format!(
                    "HTTP/1.1 {status}\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
                );
                let _ = stream.write_all(response.as_bytes());
            }
        });
        (base, origins)
    }

    fn send(server: &str) -> bool {
        tauri::async_runtime::block_on(async {
            Api::new("0.0.0-test")
                .unwrap()
                .send_message(server, "token", "chat", "hello", false, &[])
                .await
                .is_ok()
        })
    }

    #[test]
    fn launcher_questions_say_they_come_from_the_desktop_app() {
        let (server, origins) = chat_server(&["desktop", "unknown"]);
        assert!(send(&server));
        assert_eq!(*origins.lock().unwrap(), ["desktop"]);
    }

    #[test]
    fn older_servers_get_the_question_as_an_unknown_client() {
        let (server, origins) = chat_server(&["unknown"]);
        assert!(send(&server));
        assert_eq!(*origins.lock().unwrap(), ["desktop", "unknown"]);
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

    #[test]
    fn reads_agents_and_skips_rows_it_cannot_use() {
        let body = r#"[
            {"id": 0, "name": "Assistant", "description": "Default", "tools": [], "is_listed": true},
            {"id": 7, "name": "Sales", "description": null},
            {"id": "bad", "name": "Broken"},
            {"id": 9, "name": "  "},
            {"id": 12, "name": "No description"}
        ]"#;
        assert_eq!(
            parse_agents(body, false).unwrap(),
            vec![
                Agent {
                    id: 0,
                    name: "Assistant".into(),
                    description: "Default".into()
                },
                Agent {
                    id: 7,
                    name: "Sales".into(),
                    description: String::new()
                },
                Agent {
                    id: 12,
                    name: "No description".into(),
                    description: String::new()
                },
            ]
        );
        assert!(parse_agents(r#"{"detail": "x"}"#, false).is_err());
    }

    #[test]
    fn offers_agents_as_the_web_chat_does() {
        let body = r#"[
            {"id": 0, "name": "Assistant", "builtin_persona": true},
            {"id": 3, "name": "Old built-in", "builtin_persona": true},
            {"id": 7, "name": "Sales", "builtin_persona": false}
        ]"#;
        let ids = |disabled| -> Vec<i64> {
            parse_agents(body, disabled)
                .unwrap()
                .into_iter()
                .map(|a| a.id)
                .collect()
        };
        assert_eq!(ids(false), vec![0, 7]);
        assert_eq!(ids(true), vec![7]);
    }

    #[test]
    fn reads_server_settings_and_bounds_uploads() {
        let settings = parse_settings(
            r#"{"user_file_max_upload_size_mb": 10, "disable_default_assistant": true, "other": 1}"#,
        )
        .unwrap();
        assert_eq!(
            settings,
            ServerSettings {
                upload_limit_bytes: Some(10 * 1024 * 1024),
                default_agent_disabled: true,
            }
        );
        assert_eq!(upload_limit(Some(&settings)), 10 * 1024 * 1024);
        // No limit (0) or a limit above the app's: the app's limit applies.
        let unlimited = parse_settings(r#"{"user_file_max_upload_size_mb": 0}"#).unwrap();
        assert_eq!(unlimited, ServerSettings::default());
        assert_eq!(upload_limit(Some(&unlimited)), MAX_UPLOAD_BYTES);
        let large = parse_settings(r#"{"user_file_max_upload_size_mb": 4096}"#).unwrap();
        assert_eq!(upload_limit(Some(&large)), MAX_UPLOAD_BYTES);
        assert_eq!(upload_limit(None), MAX_UPLOAD_BYTES);
        assert!(parse_settings("not json").is_none());
    }

    #[test]
    fn a_cancelled_upload_stops_sending() {
        use futures_util::StreamExt;
        let body = vec![7u8; super::UPLOAD_CHUNK * 2 + 10];
        let cancelled = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let sent = tauri::async_runtime::block_on(async {
            let mut chunks = Box::pin(body_chunks(body.clone(), cancelled.clone()));
            let first = chunks.next().await.unwrap().unwrap();
            cancelled.store(true, Ordering::SeqCst);
            let second = chunks.next().await.unwrap();
            (first.len(), second.is_err(), chunks.next().await.is_none())
        });
        assert_eq!(sent, (super::UPLOAD_CHUNK, true, true));
        let all: Vec<u8> = tauri::async_runtime::block_on(
            body_chunks(body.clone(), Arc::default())
                .map(|c| c.unwrap())
                .concat(),
        );
        assert_eq!(all, body);
    }

    #[test]
    fn only_uuid_like_file_ids_reach_the_path() {
        assert!(is_file_id("3f2a9c1e-0b7d-4c55-9a61-1d2e3f4a5b6c"));
        assert!(!is_file_id(""));
        assert!(!is_file_id("../../persona/1"));
        assert!(!is_file_id("abc?x=1"));
    }

    #[test]
    fn reads_upload_answers() {
        let ok = r#"{"user_files": [{"id": "u1", "file_id": "f1", "name": "a.png",
            "status": "PROCESSING", "chat_file_type": "image", "project_id": null}],
            "rejected_files": []}"#;
        let row = upload_outcome(ok, "a.png").unwrap();
        assert_eq!(file_state(&row.status), FileState::Processing);
        let attached = row.attached();
        assert_eq!(
            attached,
            AttachedFile {
                user_file_id: "u1".into(),
                file_id: "f1".into(),
                name: "a.png".into(),
                chat_file_type: "image".into(),
            }
        );
        assert_eq!(
            attached.descriptor(),
            serde_json::json!({"id": "f1", "type": "image", "name": "a.png", "user_file_id": "u1"})
        );

        let rejected = r#"{"user_files": [], "rejected_files": [
            {"file_name": "big.pdf", "reason": "Exceeds 100 MB file size limit"}]}"#;
        assert_eq!(
            upload_outcome(rejected, "big.pdf").unwrap_err(),
            "Could not attach big.pdf: Exceeds 100 MB file size limit."
        );
        assert!(upload_outcome(r#"{"user_files": []}"#, "x").is_err());
        assert!(upload_outcome("not json", "x").is_err());
    }

    #[test]
    fn file_states_follow_the_web_chat() {
        assert_eq!(file_state("COMPLETED"), FileState::Ready);
        assert_eq!(file_state("SKIPPED"), FileState::Ready);
        assert_eq!(file_state("INDEXING"), FileState::Processing);
        assert_eq!(file_state("SOMETHING_NEW"), FileState::Processing);
        assert_eq!(file_state("FAILED"), FileState::Failed);
        assert_eq!(file_state("CANCELED"), FileState::Failed);
    }

    #[test]
    fn multipart_names_cannot_break_the_part_headers() {
        let body = multipart_body("B", "a\"b\r\n.txt", "text/plain\r\nX: y", b"hi");
        let text = String::from_utf8(body).unwrap();
        assert_eq!(
            text,
            "--B\r\nContent-Disposition: form-data; name=\"files\"; filename=\"a%22b%0D%0A.txt\"\r\nContent-Type: application/octet-stream\r\n\r\nhi\r\n--B--\r\n"
        );
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
    fn google_sign_in_shows_the_google_logo() {
        let json = r#"{"oauth_enabled":true,"sso_providers":[
            {"name":"google","display_name":"Continue with Google","authorize_url":"/api/auth/oidc/google/authorize","provider_type":"GOOGLE_OAUTH"},
            {"name":"okta","display_name":"Okta","authorize_url":"/api/auth/oidc/okta/authorize","provider_type":"OIDC"}]}"#;
        let parsed: AuthTypeResponse = serde_json::from_str(json).unwrap();
        let google: Vec<bool> = sso_options(&parsed).iter().map(|o| o.google).collect();
        assert_eq!(google, vec![true, false]);
        let legacy: AuthTypeResponse = serde_json::from_str(r#"{"oauth_enabled":true}"#).unwrap();
        assert!(sso_options(&legacy)[0].google);
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
        // A page URL reduces to the server; credentials are refused.
        assert_eq!(
            normalize_managed_server_url("  HTTPS://Onyx.Example.com/some/path/?q=1#x  ").unwrap(),
            "https://onyx.example.com"
        );
        for with_credentials in [
            "https://user:pw@example.com",
            "https://user@example.com",
            "https://:pw@example.com",
        ] {
            assert!(normalize_server_url(with_credentials).is_err());
            assert!(normalize_managed_server_url(with_credentials).is_err());
        }
    }

    #[test]
    fn plain_http_to_localhost_subdomains_only_on_macos() {
        assert!(normalize_server_url("http://localhost").is_ok());
        assert_eq!(
            normalize_server_url("http://onyx.localhost:3000").is_ok(),
            cfg!(target_os = "macos")
        );
        assert!(normalize_managed_server_url("http://onyx.localhost").is_ok());
    }

    const NOT_ROUTED: &str = r#"{"message":"This API is only available in development mode. In production, something else (e.g. nginx) should handle this."}"#;

    fn json(code: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {code}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    fn html_page() -> String {
        let body = "<html><body>Sign in to the Wi-Fi</body></html>";
        format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    #[test]
    fn only_the_onyx_version_json_is_an_onyx_server() {
        use reqwest::StatusCode;
        assert_eq!(
            parse_version(StatusCode::OK, r#"{"backend_version":"5.1.0"}"#),
            Ok("5.1.0".into())
        );
        assert_eq!(
            parse_version(StatusCode::OK, "<html></html>"),
            Err(Unreachable::NotOnyx)
        );
        assert_eq!(
            parse_version(StatusCode::OK, r#"{"status":"ok"}"#),
            Err(Unreachable::NotOnyx)
        );
        assert_eq!(
            parse_version(StatusCode::NOT_FOUND, "Not Found"),
            Err(Unreachable::NotOnyx)
        );
        assert_eq!(
            parse_version(StatusCode::NOT_FOUND, NOT_ROUTED),
            Err(Unreachable::ApiNotRouted)
        );
        assert_eq!(
            parse_version(StatusCode::BAD_GATEWAY, ""),
            Err(Unreachable::ServerError { status: 502 })
        );
    }

    #[test]
    fn the_user_agent_names_the_app_version() {
        assert_eq!(user_agent("0.1.0"), "OnyxDesktop/0.1.0");
    }

    #[test]
    fn health_fails_for_a_page_that_is_not_onyx() {
        let (server, _) = serve(|_| html_page());
        let api = Api::new("0.0.0-test").unwrap();
        assert_eq!(
            tauri::async_runtime::block_on(api.health(&server)),
            Err(Unreachable::NotOnyx)
        );
        let message = tauri::async_runtime::block_on(api.version(&server)).unwrap_err();
        assert!(
            message.contains("does not look like an Onyx server"),
            "{message}"
        );
    }

    #[test]
    fn an_unrouted_api_is_named_in_health_and_sign_in() {
        let (server, _) = serve(|path| {
            if path.starts_with("/api/") {
                json("404 Not Found", NOT_ROUTED)
            } else {
                html_page()
            }
        });
        let api = Api::new("0.0.0-test").unwrap();
        assert_eq!(
            tauri::async_runtime::block_on(api.health(&server)),
            Err(Unreachable::ApiNotRouted)
        );
        let expected = Unreachable::ApiNotRouted.message(&server);
        assert_eq!(
            tauri::async_runtime::block_on(api.version(&server)).unwrap_err(),
            expected
        );
        assert_eq!(
            tauri::async_runtime::block_on(api.auth_methods(&server))
                .err()
                .unwrap(),
            expected
        );
        assert_eq!(
            tauri::async_runtime::block_on(api.login(&server, "a@b.c", "pw")).unwrap_err(),
            expected
        );
    }

    #[test]
    fn saved_localhost_subdomains_follow_the_same_rule() {
        assert_eq!(
            saved_server_allowed("http://onyx.localhost:3000"),
            cfg!(target_os = "macos")
        );
        assert!(saved_server_allowed("https://onyx.localhost"));
        assert!(saved_server_allowed("http://localhost:3000"));
        assert!(saved_server_allowed("https://cloud.onyx.app"));
    }

    #[test]
    fn a_long_answer_is_not_onyx_and_is_not_read_to_the_end() {
        // Chunked, so there is no Content-Length to reject it early.
        let (server, _) = serve(|_| {
            // Valid version JSON, made long with whitespace.
            let json = r#"{"backend_version":"5.1.0"}"#;
            let chunk = " ".repeat(16 * 1024);
            let mut response = format!(
                "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n{:x}\r\n{json}\r\n",
                json.len()
            );
            for _ in 0..64 {
                response.push_str(&format!("{:x}\r\n{chunk}\r\n", chunk.len()));
            }
            response.push_str("0\r\n\r\n");
            response
        });
        let api = Api::new("0.0.0-test").unwrap();
        assert_eq!(
            tauri::async_runtime::block_on(api.health(&server)),
            Err(Unreachable::NotOnyx)
        );
    }

    #[test]
    fn a_body_cut_short_is_a_connection_error_not_a_wrong_server() {
        let (server, _) = serve(|_| {
            "HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\n{\"pass".to_string()
        });
        let api = Api::new("0.0.0-test").unwrap();
        let message = tauri::async_runtime::block_on(api.auth_methods(&server))
            .err()
            .unwrap();
        assert!(
            !message.contains("does not look like an Onyx server"),
            "{message}"
        );
        assert_ne!(
            tauri::async_runtime::block_on(api.health(&server)),
            Err(Unreachable::NotOnyx)
        );
    }

    #[test]
    fn an_old_server_without_desktop_sign_in_is_still_named() {
        let (server, _) = serve(|_| json("404 Not Found", r#"{"detail":"Not Found"}"#));
        let message = tauri::async_runtime::block_on(
            Api::new("0.0.0-test")
                .unwrap()
                .login(&server, "a@b.c", "pw"),
        )
        .unwrap_err();
        assert!(message.contains("v4.2"), "{message}");
    }

    fn status(code: &str) -> String {
        format!("HTTP/1.1 {code}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    }

    fn health(root: impl Fn() -> String + Send + 'static) -> Result<(), Unreachable> {
        let (server, _) = serve(move |path| {
            if path == "/api/version" {
                json("200 OK", r#"{"backend_version":"5.1.0"}"#)
            } else {
                root()
            }
        });
        tauri::async_runtime::block_on(Api::new("0.0.0-test").unwrap().health(&server))
    }

    #[test]
    fn health_fails_while_the_web_ui_fails() {
        assert_eq!(
            health(|| status("502 Bad Gateway")),
            Err(Unreachable::ServerError { status: 502 })
        );
    }

    #[test]
    fn health_passes_for_any_web_ui_answer() {
        assert_eq!(health(|| OK.to_string()), Ok(()));
        assert_eq!(health(|| redirect_to("/app")), Ok(()));
        assert_eq!(health(|| status("404 Not Found")), Ok(()));
        // A redirect to another site (cloud landing page) is not followed.
        let (other, other_hits) = serve(|_| status("500 Internal Server Error"));
        assert_eq!(health(move || redirect_to(&other)), Ok(()));
        assert_eq!(other_hits.load(Ordering::SeqCst), 0);
    }
}
