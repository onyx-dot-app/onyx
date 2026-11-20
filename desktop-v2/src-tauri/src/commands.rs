//! Commands for the bundled local windows. Each window's capability in capabilities/
//! grants only the commands its page uses; the remote main window cannot call any of them.
//!
//! A command that can open a window must be `async`. Sync commands run on the
//! main thread inside the WebView2 message handler, and building a window
//! there deadlocks on Windows.

use serde::Serialize;
use tauri::ipc::{Channel, InvokeBody, Request};
use tauri::{AppHandle, Manager, State};

use crate::api::{self, normalize_server_url, Agent, AttachedFile, AuthMethods, SearchHit};
use crate::ask::{self, AskEvent};
use crate::login_item;
use crate::main_window;
use crate::policy;
use crate::shortcut;
use crate::state::AppState;
use crate::windows;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ServerInfo {
    url: String,
    backend_version: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Prefs {
    server_url: Option<String>,
    hotkey: String,
    signed_in: bool,
    /// Set when the launcher shortcut may not work.
    shortcut_notice: Option<String>,
    launch_at_login: bool,
    /// Which settings managed policy sets; Preferences shows them read-only.
    server_managed: bool,
    server_locked: bool,
    hotkey_managed: bool,
    launcher_disabled: bool,
    launch_at_login_managed: bool,
    auto_update_disabled: bool,
    notifications_disabled: bool,
    /// The managed policy exists but is not valid.
    policy_invalid: bool,
    notify_answers: bool,
}

const MANAGED: &str = "This setting is managed by your organization.";
const POLICY_INVALID: &str =
    "Your organization's Onyx policy is invalid, so this setting is locked. Contact your IT team.";

fn server_locked(state: &AppState) -> Result<(), String> {
    let policy = state.policy();
    if !policy.lock_server_url {
        return Ok(());
    }
    Err(if policy.invalid {
        POLICY_INVALID
    } else {
        MANAGED
    }
    .into())
}

/// Launcher commands refuse while managed policy turns the launcher off.
fn launcher_enabled(app: &AppHandle, state: &AppState) -> Result<(), String> {
    if !state.policy().disable_launcher {
        return Ok(());
    }
    windows::hide_launcher(app);
    Err("Your organization turned off the launcher.".into())
}

#[tauri::command]
pub async fn check_server(url: String, state: State<'_, AppState>) -> Result<ServerInfo, String> {
    let server = normalize_server_url(&url)?;
    let backend_version = state.api.version(&server).await?;
    Ok(ServerInfo {
        url: server,
        backend_version,
    })
}

#[tauri::command]
pub async fn save_server(
    url: String,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    server_locked(&state)?;
    let server = normalize_server_url(&url)?;
    state.config.update(|c| c.server_url = Some(server))?;
    windows::open_login(&app)?;
    windows::close(&app, windows::ONBOARDING);
    Ok(())
}

#[tauri::command]
pub async fn get_auth_methods(state: State<'_, AppState>) -> Result<AuthMethods, String> {
    let server = state.server()?;
    state.api.auth_methods(&server).await
}

/// Returns "browser" when sign-in continues in the system browser, or
/// "window" when it fell back to the in-app sign-in window.
#[tauri::command]
pub async fn sign_in_with_sso(
    browser: bool,
    provider: Option<String>,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let server = state.server()?;
    if browser && crate::sso::start_in_browser(&app, &server, provider.as_deref()).await? {
        return Ok("browser".into());
    }
    crate::sso::open(&app, &server)?;
    Ok("window".into())
}

#[tauri::command]
pub async fn login(
    email: String,
    password: String,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let server = state.server()?;
    let epoch = state.epoch();
    let token = state.api.login(&server, &email, &password).await?;
    // Fails if the user changed server, signed out or finished SSO meanwhile.
    if !state.commit_sign_in(&server, &token, epoch)? {
        return Err("Sign-in was cancelled.".into());
    }
    // A pending SSO sign-in (possibly another account) must not replace this one.
    crate::sso::cancel(&app);
    main_window::open(&app, &server, &token, "/app").await?;
    windows::close(&app, windows::LOGIN);
    Ok(())
}

/// Preferences calls this when it opens, so managed policy is read again then.
#[tauri::command]
pub fn get_prefs(app: AppHandle, state: State<'_, AppState>) -> Prefs {
    policy::refresh(&app);
    let policy = state.policy();
    let server_url = state.server().ok();
    let signed_in = server_url
        .as_deref()
        .is_some_and(|server| state.token(server).is_some());
    let hotkey = policy
        .launcher_shortcut
        .clone()
        .unwrap_or_else(|| state.config.get().hotkey());
    Prefs {
        shortcut_notice: if policy.disable_launcher {
            None
        } else {
            shortcut::notice(&app, &hotkey)
        },
        server_managed: server_url.is_some() && server_url == policy.server_url,
        server_locked: policy.lock_server_url,
        hotkey_managed: policy.hotkey_managed(),
        launcher_disabled: policy.disable_launcher,
        launch_at_login_managed: policy.launch_at_login.is_some(),
        auto_update_disabled: policy.disable_auto_update,
        notifications_disabled: policy.disable_notifications,
        policy_invalid: policy.invalid,
        hotkey,
        launch_at_login: login_item::is_enabled(&app).unwrap_or(false),
        server_url,
        notify_answers: crate::notify::enabled(&state),
        signed_in,
    }
}

#[tauri::command]
pub fn set_notify_answers(enabled: bool, state: State<'_, AppState>) -> Result<(), String> {
    if state.policy().disable_notifications {
        return Err(MANAGED.into());
    }
    state.config.update(|c| c.notify_answers = Some(enabled))
}

/// The launcher started a new chat; its old answer must not notify.
#[tauri::command]
pub fn discard_answer(app: AppHandle) {
    crate::aonyx::answer_discarded(&app);
}

#[tauri::command]
pub fn set_hotkey(
    hotkey: String,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    if state.policy().hotkey_managed() {
        return Err(MANAGED.into());
    }
    let previous = shortcut::applied();
    shortcut::apply(&app, Some(&hotkey))?;
    // A shortcut that cannot be saved is not kept: it would revert on restart.
    if let Err(e) = state.config.update(|c| c.hotkey = Some(hotkey.clone())) {
        let _ = shortcut::apply(&app, previous.as_deref());
        return Err(e);
    }
    Ok(())
}

#[tauri::command]
pub fn set_launch_at_login(
    enabled: bool,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    if state.policy().launch_at_login.is_some() {
        return Err(MANAGED.into());
    }
    login_item::set(&app, enabled).map_err(|e| {
        log::warn!("could not change launch at login: {e}");
        "Could not change this setting. Try again.".to_string()
    })
}

async fn end_session(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    // Requests read the epoch before the token: one that starts during this
    // either sees no token or goes stale.
    let Ok(server) = state.server() else {
        state.end_epoch();
        crate::sso::cancel(app);
        return Ok(());
    };
    let (token, cleared) = state.end_session(&server);
    crate::sso::cancel(app);
    crate::offline::dismiss(app);
    let revoked = match token {
        Some(token) => crate::revocation::end_server_session(app, &server, &token).await,
        None => true,
    };
    cleared?;
    main_window::close(app, &server);
    windows::reset_launcher(app);
    if !revoked {
        windows::notify(
            app,
            "Signed out",
            "Signed out on this computer. Onyx could not reach the server to end the \
             session. Onyx tries again while it is open.",
        );
    }
    Ok(())
}

#[tauri::command]
pub async fn sign_out(app: AppHandle) -> Result<(), String> {
    end_session(&app).await?;
    windows::open_login(&app)?;
    windows::close(&app, windows::PREFERENCES);
    Ok(())
}

#[tauri::command]
pub async fn change_server(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    server_locked(&state)?;
    end_session(&app).await?;
    // The session has ended either way; if the server cannot be cleared, the
    // user still gets a window (sign-in for the same server) and the error.
    if let Err(e) = state.config.update(|c| c.server_url = None) {
        let _ = windows::open_login(&app);
        return Err(e);
    }
    windows::open_onboarding(&app)?;
    windows::close(&app, windows::LOGIN);
    windows::close(&app, windows::PREFERENCES);
    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LauncherAgents {
    agents: Vec<Agent>,
    /// The saved agent, if the user can still use it; `None` is the default agent.
    selected: Option<i64>,
    /// "Always Start with an Agent": `agents` has no default agent, and a new
    /// chat needs one of them.
    default_agent_disabled: bool,
}

/// The saved agent if the list has it; otherwise the default agent, or the
/// first agent when the default one is off.
fn selected_agent(agents: &[Agent], saved: Option<i64>, default_disabled: bool) -> Option<i64> {
    saved
        .filter(|id| agents.iter().any(|a| a.id == *id))
        .or_else(|| {
            default_disabled
                .then(|| agents.first().map(|a| a.id))
                .flatten()
        })
}

/// An error means the list could not be read now; the launcher keeps what it had.
#[tauri::command]
pub async fn list_agents(state: State<'_, AppState>) -> Result<LauncherAgents, String> {
    let epoch = state.epoch();
    let (server, token) = state.session()?;
    // Without the settings the launcher cannot tell whether the default agent is on.
    let default_disabled = state
        .api
        .server_settings(&server, &token)
        .await
        .ok_or_else(|| "Could not read the server settings.".to_string())?
        .default_agent_disabled;
    let agents = state
        .api
        .list_agents(&server, &token, default_disabled)
        .await?;
    if state.epoch() != epoch {
        return Err("Signed out.".into());
    }
    let saved = state.config.get().launcher_agents.get(&server).copied();
    Ok(LauncherAgents {
        selected: selected_agent(&agents, saved, default_disabled),
        agents,
        default_agent_disabled: default_disabled,
    })
}

/// The largest file the launcher can attach, in bytes: the server's limit,
/// within the app's own.
#[tauri::command]
pub async fn get_upload_limit(state: State<'_, AppState>) -> Result<u64, String> {
    let (server, token) = state.session()?;
    let settings = state.api.server_settings(&server, &token).await;
    Ok(api::upload_limit(settings.as_ref()))
}

/// Saves the launcher's agent for the current server (`None`: the default agent).
#[tauri::command]
pub fn set_launcher_agent(agent_id: Option<i64>, state: State<'_, AppState>) -> Result<(), String> {
    let server = state.server()?;
    state.config.update(|c| match agent_id {
        Some(id) if id != ask::DEFAULT_AGENT_ID => {
            c.launcher_agents.insert(server, id);
        }
        _ => {
            c.launcher_agents.remove(&server);
        }
    })
}

/// A request header the page set with `encodeURIComponent`.
fn encoded_header(request: &Request<'_>, name: &str) -> Option<String> {
    decode_component(request.headers().get(name)?.to_str().ok()?)
}

/// Reverses `encodeURIComponent`, which never leaves a raw `+`, `&` or `=`.
fn decode_component(raw: &str) -> Option<String> {
    url::form_urlencoded::parse(raw.as_bytes())
        .next()
        .map(|(decoded, _)| decoded.into_owned())
}

/// Uploads one file for the next question and waits until the server has
/// processed it. The body is the file's bytes; `Onyx-File-Name` and
/// `Onyx-File-Type` name it, and `Onyx-Upload-Id` is the id `cancel_upload` takes.
#[tauri::command]
pub async fn upload_file(
    request: Request<'_>,
    state: State<'_, AppState>,
) -> Result<AttachedFile, String> {
    let epoch = state.epoch();
    let (server, token) = state.session()?;
    let InvokeBody::Raw(bytes) = request.body() else {
        return Err("The file could not be read.".into());
    };
    let name = encoded_header(&request, "onyx-file-name")
        .filter(|n| !n.trim().is_empty())
        .unwrap_or_else(|| "file".into());
    let mime = encoded_header(&request, "onyx-file-type").unwrap_or_default();
    let upload_id = encoded_header(&request, "onyx-upload-id")
        .and_then(|id| id.parse::<u64>().ok())
        .ok_or_else(|| "The upload has no id.".to_string())?;
    let entry = state.begin_upload(upload_id);
    if bytes.is_empty() {
        return Err(format!("{name} is empty."));
    }
    if bytes.len() as u64 > api::MAX_UPLOAD_BYTES {
        return Err(too_large(&name, api::MAX_UPLOAD_BYTES));
    }
    let limit = api::upload_limit(state.api.server_settings(&server, &token).await.as_ref());
    if bytes.len() as u64 > limit {
        return Err(too_large(&name, limit));
    }
    let current = || state.epoch() == epoch && !entry.cancelled();
    if !current() {
        return Err("The upload was cancelled.".into());
    }
    let row = state
        .api
        .upload_file(&server, &token, &name, &mime, bytes, entry.cancel_flag())
        .await
        .map_err(|e| {
            if current() {
                e
            } else {
                "The upload was cancelled.".into()
            }
        })?;
    let user_file_id = row.id.clone();
    let result = state
        .api
        .wait_for_file(&server, &token, row, &current)
        .await;
    // Removed, or from a session that has ended.
    let stale = !current();
    if stale || result.is_err() {
        // A removed or failed file must not stay in the user's files; the
        // launcher gets no id to delete it with.
        if let Err(e) = state
            .api
            .delete_user_file(&server, &token, &user_file_id)
            .await
        {
            log::warn!("could not delete an unused attachment: {e}");
        }
    }
    if stale {
        return Err("The upload was cancelled.".into());
    }
    result
}

fn too_large(name: &str, limit: u64) -> String {
    format!(
        "{name} is larger than {} MB, the largest file you can attach.",
        limit / (1024 * 1024)
    )
}

/// Stops an upload in flight; `upload_file` deletes the file if the server has it.
#[tauri::command]
pub fn cancel_upload(upload_id: u64, state: State<'_, AppState>) {
    state.cancel_upload(upload_id);
}

/// Deletes an uploaded file that was not sent (a removed attachment).
#[tauri::command]
pub async fn delete_user_file(
    user_file_id: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let (server, token) = state.session()?;
    state
        .api
        .delete_user_file(&server, &token, &user_file_id)
        .await
}

#[tauri::command]
pub async fn ask(
    question: String,
    chat_session_id: Option<String>,
    agent_id: Option<i64>,
    files: Vec<AttachedFile>,
    on_event: Channel<AskEvent>,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    launcher_enabled(&app, &state)?;
    let epoch = state.epoch();
    let (server, token) = state.session()?;
    let current = || state.epoch() == epoch;
    let answer = crate::aonyx::answer_started(&app);
    let result = ask::run(
        &state.api,
        &server,
        &token,
        &ask::Question {
            text: &question,
            follow_up_of: chat_session_id.as_deref(),
            agent_id,
            files: &files,
        },
        &on_event,
        &current,
    )
    .await;
    crate::aonyx::answer_finished(&app, answer, result.is_ok());
    let outcome = match &result {
        Ok(a) if a.awaiting_approval => crate::notify::Outcome::NeedsApproval,
        Ok(_) => crate::notify::Outcome::Answered,
        Err(_) => crate::notify::Outcome::Failed,
    };
    let event = match &result {
        Ok(_) => AskEvent::Done,
        Err(message) => AskEvent::Error {
            message: message.clone(),
        },
    };
    let _ = on_event.send(event);
    // After the answer ends in the launcher: the first notification can wait
    // for the permission prompt.
    let notify_app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        crate::notify::answer_finished(
            &notify_app,
            crate::notify::Answer { id: answer, epoch },
            outcome,
        );
    });
    Ok(())
}

#[tauri::command]
pub async fn search(
    query: String,
    sources: Vec<String>,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<Vec<SearchHit>, String> {
    launcher_enabled(&app, &state)?;
    let epoch = state.epoch();
    let (server, token) = state.session()?;
    let hits = state.api.search(&server, &token, &query, &sources).await?;
    // Results for a session that has since ended are dropped.
    if state.epoch() != epoch {
        return Err("Signed out.".into());
    }
    Ok(hits)
}

#[tauri::command]
pub async fn open_chat_in_main(
    chat_session_id: Option<String>,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    launcher_enabled(&app, &state)?;
    let (server, token) = state.session()?;
    let path = match chat_session_id {
        Some(id) => format!("/app?chatId={id}"),
        None => "/app".to_string(),
    };
    windows::hide_launcher(&app);
    main_window::open(&app, &server, &token, &path).await
}

#[tauri::command]
pub async fn open_external(
    url: String,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    launcher_enabled(&app, &state)?;
    // Relative links (search results, citations) belong to the server.
    let server = state.server().ok();
    let base = server.as_deref().and_then(|s| url::Url::parse(s).ok());
    let parsed = match &base {
        Some(base) => base.join(&url),
        None => url::Url::parse(&url),
    }
    .map_err(|e| e.to_string())?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err("Only web links can be opened.".into());
    }
    // A page on the signed-in server opens in the Onyx window, which has the
    // session; the browser would show the web sign-in page instead.
    if let (Some(base), Ok((server, token))) = (&base, state.session()) {
        // The parsed URL, not its path: a path such as `//host/x` joined to
        // the server again names another host.
        if parsed.origin() == base.origin() {
            windows::hide_launcher(&app);
            return main_window::open_url(&app, &server, &token, parsed).await;
        }
    }
    main_window::open_external(&app, parsed.as_str());
    Ok(())
}

#[tauri::command]
pub fn hide_launcher(app: AppHandle) {
    windows::hide_launcher(&app);
}

/// The launcher logo's easter egg: brings Aonyx onto the screen or sends it away.
#[tauri::command]
pub async fn toggle_aonyx(app: AppHandle) {
    if launcher_enabled(&app, &app.state::<AppState>()).is_ok() {
        crate::aonyx::toggle(&app);
    }
}

/// A click on the pet opens (or closes) the launcher.
#[tauri::command]
pub async fn aonyx_clicked(app: AppHandle) {
    windows::toggle_launcher(&app);
}

#[tauri::command]
pub fn aonyx_menu(app: AppHandle) -> Result<(), String> {
    crate::aonyx::show_menu(&app)
}

#[tauri::command]
pub fn get_offline_status(app: AppHandle) -> Option<crate::offline::OfflineStatus> {
    crate::offline::status(&app)
}

#[tauri::command]
pub fn retry_connection(app: AppHandle) {
    crate::offline::retry_now(&app);
}

#[cfg(test)]
mod tests {
    use super::{decode_component, selected_agent};
    use crate::api::Agent;

    fn agent(id: i64) -> Agent {
        Agent {
            id,
            name: format!("Agent {id}"),
            description: String::new(),
        }
    }

    #[test]
    fn selects_the_saved_agent_or_a_usable_default() {
        let agents = [agent(0), agent(7)];
        assert_eq!(selected_agent(&agents, Some(7), false), Some(7));
        assert_eq!(selected_agent(&agents, Some(9), false), None);
        assert_eq!(selected_agent(&agents, None, false), None);
        let without_default = [agent(7), agent(8)];
        assert_eq!(selected_agent(&without_default, None, true), Some(7));
        assert_eq!(selected_agent(&without_default, Some(8), true), Some(8));
        assert_eq!(selected_agent(&[], None, true), None);
    }

    /// Calls that can build a window (directly or through a main-thread hop).
    const OPENS_WINDOWS: &[&str] = &[
        "windows::open_",
        "windows::route",
        "windows::show_",
        "windows::toggle_launcher",
        "windows::end_rejected_session",
        "launcher::toggle",
        "launcher::show",
        "launcher::preload",
        "aonyx::toggle",
        "aonyx::restore",
        "sso::open",
        "main_window::open(",
        "main_window::open_url",
        "offline::show",
    ];

    /// Each command in `source`: its signature line and body.
    fn commands(source: &str) -> Vec<(&str, &str)> {
        let marker = concat!("#[tauri::", "command]");
        source
            .split(marker)
            .skip(1)
            .map(|chunk| {
                let end = chunk.find("\n}\n").unwrap_or(chunk.len());
                let body = &chunk[..end];
                let signature = body
                    .lines()
                    .find(|line| line.starts_with("pub "))
                    .unwrap_or_default();
                (signature, body)
            })
            .collect()
    }

    fn sync_commands_that_open_windows(source: &str) -> Vec<String> {
        commands(source)
            .into_iter()
            .filter(|(signature, body)| {
                !signature.contains("async fn")
                    && OPENS_WINDOWS.iter().any(|call| body.contains(call))
            })
            .map(|(signature, _)| signature.to_string())
            .collect()
    }

    #[test]
    fn commands_that_open_windows_are_async() {
        let source = include_str!("commands.rs");
        assert!(commands(source).len() > 20, "commands were not found");
        assert_eq!(
            sync_commands_that_open_windows(source),
            Vec::<String>::new()
        );
    }

    #[test]
    fn finds_a_sync_command_that_opens_a_window() {
        let source = concat!(
            "#[tauri::",
            "command]\npub fn a(app: AppHandle) {\n    windows::open_login(&app);\n}\n",
            "#[tauri::",
            "command]\npub async fn b(app: AppHandle) {\n    windows::open_login(&app);\n}\n",
            "#[tauri::",
            "command]\npub fn c(app: AppHandle) {\n    windows::hide_launcher(&app);\n}\n",
        );
        assert_eq!(
            sync_commands_that_open_windows(source),
            vec!["pub fn a(app: AppHandle) {".to_string()]
        );
    }

    #[test]
    fn decodes_file_name_headers() {
        assert_eq!(
            decode_component("Q3%20report%20%26%20notes%3Dfinal%2Bv2%20%C3%BC.pdf").as_deref(),
            Some("Q3 report & notes=final+v2 ü.pdf")
        );
        assert_eq!(decode_component(""), None);
    }
}
