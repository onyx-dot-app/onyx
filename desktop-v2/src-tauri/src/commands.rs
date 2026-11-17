//! Commands for the bundled local windows. The capability in capabilities/local.json
//! limits them to those windows; the remote main window cannot call any of them.

use serde::Serialize;
use tauri::{AppHandle, Manager, State};

use crate::api::normalize_server_url;
use crate::main_window;
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
    signed_in: bool,
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
    let server = normalize_server_url(&url)?;
    state.config.update(|c| c.server_url = Some(server))?;
    windows::open_login(&app)?;
    windows::close(&app, windows::ONBOARDING);
    Ok(())
}

#[tauri::command]
pub async fn login(
    email: String,
    password: String,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let server = state.server()?;
    let token = state.api.login(&server, &email, &password).await?;
    state.set_token(&server, &token)?;
    main_window::open(&app, &server, &token, "/app").await?;
    windows::close(&app, windows::LOGIN);
    Ok(())
}

#[tauri::command]
pub fn get_prefs(state: State<'_, AppState>) -> Prefs {
    let config = state.config.get();
    let signed_in = config
        .server_url
        .as_deref()
        .is_some_and(|server| state.token(server).is_some());
    Prefs {
        server_url: config.server_url,
        signed_in,
    }
}

async fn end_session(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    let Ok(server) = state.server() else {
        return Ok(());
    };

    if let Some(token) = state.token(&server) {
        state.api.logout(&server, &token).await;
    }
    state.clear_token(&server)?;
    main_window::close(app, &server);
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
    end_session(&app).await?;
    state.config.update(|c| c.server_url = None)?;
    windows::open_onboarding(&app)?;
    windows::close(&app, windows::LOGIN);
    windows::close(&app, windows::PREFERENCES);
    Ok(())
}

#[tauri::command]
pub fn open_external(url: String, app: AppHandle) -> Result<(), String> {
    let parsed = url::Url::parse(&url).map_err(|e| e.to_string())?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err("Only web links can be opened.".into());
    }
    main_window::open_external(&app, parsed.as_str());
    Ok(())
}
