// Tauri command handlers must take IPC-deserialized args (`String`) and
// extractors (`State`/`WebviewWindow`/`AppHandle`/`Window`) by value -- that's
// the framework's calling convention, not an oversight.
#![allow(clippy::needless_pass_by_value)]

use crate::config::{get_config_dir, get_config_path, save_config, AppConfig, ConfigState};
use crate::window::{build_and_setup_window, open_in_default_browser};
use serde::Serialize;
use std::fs;
use tauri::Manager;
use url::Url;

#[tauri::command]
pub async fn check_server_reachable(state: tauri::State<'_, ConfigState>) -> Result<(), String> {
    let url = state.config().server_url;
    let parsed = Url::parse(&url).map_err(|e| format!("Invalid URL: {e}"))?;
    match parsed.scheme() {
        "http" | "https" => {}
        _ => return Err("URL must use http or https".to_string()),
    }

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .map_err(|e| format!("Failed to build HTTP client: {e}"))?;

    match client.head(parsed).send().await {
        // Only definitive "server didn't answer" errors count as unreachable.
        // TLS / decode / redirect errors imply the server is listening — the
        // webview, which has its own trust store, is likely to succeed even
        // when rustls rejects a self-signed cert.
        Err(e) if e.is_connect() || e.is_timeout() => Err(e.to_string()),
        _ => Ok(()),
    }
}

#[tauri::command]
pub fn open_in_browser(url: String) -> Result<(), String> {
    let parsed_url = Url::parse(&url).map_err(|_| "Invalid URL".to_string())?;
    match parsed_url.scheme() {
        "http" | "https" | "mailto" | "tel" => {}
        _ => return Err("Unsupported URL scheme".to_string()),
    }

    if open_in_default_browser(parsed_url.as_str()) {
        Ok(())
    } else {
        Err("Failed to open URL in default browser".to_string())
    }
}

/// Get the current server URL
#[tauri::command]
pub fn get_server_url(state: tauri::State<ConfigState>) -> String {
    state.config().server_url
}

#[derive(Serialize)]
pub struct BootstrapState {
    server_url: String,
    config_exists: bool,
}

/// Get the server URL plus whether a config file exists
#[tauri::command]
pub fn get_bootstrap_state(state: tauri::State<ConfigState>) -> BootstrapState {
    let server_url = state.config().server_url;
    let config_exists =
        state.is_config_initialized() && get_config_path().is_some_and(|path| path.exists());

    BootstrapState {
        server_url,
        config_exists,
    }
}

/// Set a new server URL and save to config
#[tauri::command]
pub fn set_server_url(state: tauri::State<ConfigState>, url: String) -> Result<String, String> {
    // Validate URL
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err("URL must start with http:// or https://".to_string());
    }

    let config =
        state.update_and_persist(|c| c.server_url = url.trim_end_matches('/').to_string())?;
    state.set_config_initialized(true);

    Ok(config.server_url)
}

/// Get the config file path (so users know where to edit)
#[tauri::command]
pub fn get_config_path_cmd() -> Result<String, String> {
    get_config_path()
        .map(|p| p.to_string_lossy().to_string())
        .ok_or_else(|| "Could not determine config path".to_string())
}

/// Open the config file in the default editor
#[tauri::command]
pub fn open_config_file() -> Result<(), String> {
    let config_path = get_config_path().ok_or("Could not determine config path")?;

    // Ensure config exists
    if !config_path.exists() {
        save_config(&AppConfig::default())?;
    }

    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg("-t")
            .arg(&config_path)
            .spawn()
            .map_err(|e| format!("Failed to open config: {e}"))?;
    }

    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&config_path)
            .spawn()
            .map_err(|e| format!("Failed to open config: {e}"))?;
    }

    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("notepad")
            .arg(&config_path)
            .spawn()
            .map_err(|e| format!("Failed to open config: {e}"))?;
    }

    Ok(())
}

/// Open the config directory in file manager
#[tauri::command]
pub fn open_config_directory() -> Result<(), String> {
    let config_dir = get_config_dir().ok_or("Could not determine config directory")?;

    // Ensure directory exists
    fs::create_dir_all(&config_dir).map_err(|e| format!("Failed to create config dir: {e}"))?;

    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&config_dir)
            .spawn()
            .map_err(|e| format!("Failed to open directory: {e}"))?;
    }

    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&config_dir)
            .spawn()
            .map_err(|e| format!("Failed to open directory: {e}"))?;
    }

    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer")
            .arg(&config_dir)
            .spawn()
            .map_err(|e| format!("Failed to open directory: {e}"))?;
    }

    Ok(())
}

/// Navigate to a specific path on the configured server
#[tauri::command]
pub fn navigate_to(window: tauri::WebviewWindow, state: tauri::State<ConfigState>, path: &str) {
    let base_url = state.config().server_url;
    let url = format!("{base_url}{path}");
    if let Err(e) = window.eval(format!("window.location.href = '{url}'")) {
        crate::debug_log::log_backend_error(
            window.app_handle(),
            &format!("Failed to navigate to {path}: {e}"),
        );
    }
}

/// Reload the current page
#[tauri::command]
pub fn reload_page(window: tauri::WebviewWindow) {
    if let Err(e) = window.eval("window.location.reload()") {
        crate::debug_log::log_backend_error(
            window.app_handle(),
            &format!("Failed to reload page: {e}"),
        );
    }
}

/// Go back in history
#[tauri::command]
pub fn go_back(window: tauri::WebviewWindow) {
    if let Err(e) = window.eval("window.history.back()") {
        crate::debug_log::log_backend_error(
            window.app_handle(),
            &format!("Failed to go back: {e}"),
        );
    }
}

/// Go forward in history
#[tauri::command]
pub fn go_forward(window: tauri::WebviewWindow) {
    if let Err(e) = window.eval("window.history.forward()") {
        crate::debug_log::log_backend_error(
            window.app_handle(),
            &format!("Failed to go forward: {e}"),
        );
    }
}

/// Open a new window
#[tauri::command]
pub async fn new_window(app: tauri::AppHandle) -> Result<(), String> {
    build_and_setup_window(&app).map(|_| ())
}

/// Reset config to defaults
#[tauri::command]
pub fn reset_config(state: tauri::State<ConfigState>) -> Result<(), String> {
    state.update_and_persist(|c| *c = AppConfig::default())?;
    state.set_config_initialized(true);
    Ok(())
}

/// Start dragging the window
#[tauri::command]
pub async fn start_drag_window(window: tauri::Window) -> Result<(), String> {
    window.start_dragging().map_err(|e| e.to_string())
}

/// Windows-only DOM-listener fallback for the Alt-alone menu-bar toggle (see
/// `scripts/alt_menu_windows.js`); Linux hooks the native GTK window instead.
#[tauri::command]
pub fn toggle_menu_bar(app: tauri::AppHandle) {
    crate::menu::handle_menu_bar_toggle(&app);
}
