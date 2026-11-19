//! Commands for the bundled local windows. Each window's capability in capabilities/
//! grants only the commands its page uses; the remote main window cannot call any of them.

use serde::Serialize;
use tauri::ipc::Channel;
use tauri::{AppHandle, Manager, State};

use crate::api::{normalize_server_url, AuthMethods, SearchHit};
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
pub fn save_server(url: String, app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
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
        signed_in,
    }
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
    if let Some(token) = token {
        state.api.logout(&server, &token).await;
    }
    cleared?;
    main_window::close(app, &server);
    windows::reset_launcher(app);
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

#[tauri::command]
pub async fn ask(
    question: String,
    chat_session_id: Option<String>,
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
        &question,
        chat_session_id.as_deref(),
        &on_event,
        &current,
    )
    .await;
    crate::aonyx::answer_finished(&app, answer, result.is_ok());
    let event = match &result {
        Ok(_) => AskEvent::Done,
        Err(message) => AskEvent::Error {
            message: message.clone(),
        },
    };
    let _ = on_event.send(event);
    Ok(())
}

#[tauri::command]
pub async fn search(
    query: String,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<Vec<SearchHit>, String> {
    launcher_enabled(&app, &state)?;
    let epoch = state.epoch();
    let (server, token) = state.session()?;
    let hits = state.api.search(&server, &token, &query).await?;
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
pub fn toggle_aonyx(app: AppHandle, state: State<'_, AppState>) {
    if launcher_enabled(&app, &state).is_ok() {
        crate::aonyx::toggle(&app);
    }
}

/// A click on the pet opens (or closes) the launcher.
#[tauri::command]
pub fn aonyx_clicked(app: AppHandle) {
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
