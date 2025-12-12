// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::RwLock;
use std::time::Duration;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};
use tokio::time::sleep;
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};

// ============================================================================
// Configuration
// ============================================================================

const DEFAULT_SERVER_URL: &str = "https://cloud.onyx.app";
const CONFIG_FILE_NAME: &str = "config.json";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    /// The Onyx server URL (default: https://cloud.onyx.app)
    pub server_url: String,
    
    /// Optional: Custom window title
    #[serde(default = "default_window_title")]
    pub window_title: String,
}

fn default_window_title() -> String {
    "Onyx".to_string()
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            server_url: DEFAULT_SERVER_URL.to_string(),
            window_title: default_window_title(),
        }
    }
}

/// Get the config directory path
fn get_config_dir() -> Option<PathBuf> {
    ProjectDirs::from("app", "onyx", "desktop").map(|dirs| dirs.config_dir().to_path_buf())
}

/// Get the full config file path
fn get_config_path() -> Option<PathBuf> {
    get_config_dir().map(|dir| dir.join(CONFIG_FILE_NAME))
}

/// Load config from file, or create default if it doesn't exist
fn load_config() -> AppConfig {
    let config_path = match get_config_path() {
        Some(path) => path,
        None => {
            eprintln!("Could not determine config directory, using defaults");
            return AppConfig::default();
        }
    };

    if config_path.exists() {
        match fs::read_to_string(&config_path) {
            Ok(contents) => match serde_json::from_str(&contents) {
                Ok(config) => {
                    println!("Loaded config from {:?}", config_path);
                    return config;
                }
                Err(e) => {
                    eprintln!("Failed to parse config: {}, using defaults", e);
                }
            },
            Err(e) => {
                eprintln!("Failed to read config: {}, using defaults", e);
            }
        }
    } else {
        // Create default config file
        if let Err(e) = save_config(&AppConfig::default()) {
            eprintln!("Failed to create default config: {}", e);
        } else {
            println!("Created default config at {:?}", config_path);
        }
    }

    AppConfig::default()
}

/// Save config to file
fn save_config(config: &AppConfig) -> Result<(), String> {
    let config_dir = get_config_dir().ok_or("Could not determine config directory")?;
    let config_path = config_dir.join(CONFIG_FILE_NAME);

    // Ensure config directory exists
    fs::create_dir_all(&config_dir).map_err(|e| format!("Failed to create config dir: {}", e))?;

    let json = serde_json::to_string_pretty(config)
        .map_err(|e| format!("Failed to serialize config: {}", e))?;

    fs::write(&config_path, json).map_err(|e| format!("Failed to write config: {}", e))?;

    Ok(())
}

// Global config state
struct ConfigState(RwLock<AppConfig>);

// ============================================================================
// Tauri Commands
// ============================================================================

/// Get the current server URL
#[tauri::command]
fn get_server_url(state: tauri::State<ConfigState>) -> String {
    state.0.read().unwrap().server_url.clone()
}

/// Set a new server URL and save to config
#[tauri::command]
fn set_server_url(state: tauri::State<ConfigState>, url: String) -> Result<String, String> {
    // Validate URL
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err("URL must start with http:// or https://".to_string());
    }

    let mut config = state.0.write().unwrap();
    config.server_url = url.trim_end_matches('/').to_string();
    save_config(&config)?;
    
    Ok(config.server_url.clone())
}

/// Get the config file path (so users know where to edit)
#[tauri::command]
fn get_config_path_cmd() -> Result<String, String> {
    get_config_path()
        .map(|p| p.to_string_lossy().to_string())
        .ok_or_else(|| "Could not determine config path".to_string())
}

/// Open the config file in the default editor
#[tauri::command]
fn open_config_file() -> Result<(), String> {
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
            .map_err(|e| format!("Failed to open config: {}", e))?;
    }

    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&config_path)
            .spawn()
            .map_err(|e| format!("Failed to open config: {}", e))?;
    }

    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("notepad")
            .arg(&config_path)
            .spawn()
            .map_err(|e| format!("Failed to open config: {}", e))?;
    }

    Ok(())
}

/// Open the config directory in file manager
#[tauri::command]
fn open_config_directory() -> Result<(), String> {
    let config_dir = get_config_dir().ok_or("Could not determine config directory")?;
    
    // Ensure directory exists
    fs::create_dir_all(&config_dir).map_err(|e| format!("Failed to create config dir: {}", e))?;

    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&config_dir)
            .spawn()
            .map_err(|e| format!("Failed to open directory: {}", e))?;
    }

    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&config_dir)
            .spawn()
            .map_err(|e| format!("Failed to open directory: {}", e))?;
    }

    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer")
            .arg(&config_dir)
            .spawn()
            .map_err(|e| format!("Failed to open directory: {}", e))?;
    }

    Ok(())
}

/// Navigate to a specific path on the configured server
#[tauri::command]
fn navigate_to(window: tauri::WebviewWindow, state: tauri::State<ConfigState>, path: &str) {
    let base_url = state.0.read().unwrap().server_url.clone();
    let url = format!("{}{}", base_url, path);
    let _ = window.eval(&format!("window.location.href = '{}'", url));
}

/// Reload the current page
#[tauri::command]
fn reload_page(window: tauri::WebviewWindow) {
    let _ = window.eval("window.location.reload()");
}

/// Go back in history
#[tauri::command]
fn go_back(window: tauri::WebviewWindow) {
    let _ = window.eval("window.history.back()");
}

/// Go forward in history
#[tauri::command]
fn go_forward(window: tauri::WebviewWindow) {
    let _ = window.eval("window.history.forward()");
}

/// Open a new window
#[tauri::command]
async fn new_window(app: AppHandle, state: tauri::State<'_, ConfigState>) -> Result<(), String> {
    let server_url = state.0.read().unwrap().server_url.clone();
    let window_label = format!("onyx-{}", uuid::Uuid::new_v4());

    let window = WebviewWindowBuilder::new(
        &app,
        &window_label,
        WebviewUrl::External(server_url.parse().map_err(|e| format!("Invalid URL: {}", e))?),
    )
    .title("Onyx")
    .inner_size(1200.0, 800.0)
    .min_inner_size(800.0, 600.0)
    .transparent(true)
    .title_bar_style(tauri::TitleBarStyle::Overlay)
    .hidden_title(true)
    .build()
    .map_err(|e| e.to_string())?;

    // Apply vibrancy effect
    #[cfg(target_os = "macos")]
    {
        let _ = apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None);
    }

    // Inject title bar script after window loads (with retries)
    let window_clone = window.clone();
    tauri::async_runtime::spawn(async move {
        let titlebar_script = include_str!("../../src/titlebar.js");
        for i in 0..5 {
            sleep(Duration::from_millis(1000 + i * 1000)).await;
            let _ = window_clone.eval(titlebar_script);
        }
    });

    Ok(())
}

/// Reset config to defaults
#[tauri::command]
fn reset_config(state: tauri::State<ConfigState>) -> Result<(), String> {
    let mut config = state.0.write().unwrap();
    *config = AppConfig::default();
    save_config(&config)?;
    Ok(())
}

/// Start dragging the window
#[tauri::command]
async fn start_drag_window(window: tauri::Window) -> Result<(), String> {
    window.start_dragging().map_err(|e| e.to_string())
}

// ============================================================================
// Shortcuts Setup
// ============================================================================

fn setup_shortcuts(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let new_chat = Shortcut::new(Some(Modifiers::SUPER), Code::KeyN);
    let reload = Shortcut::new(Some(Modifiers::SUPER), Code::KeyR);
    let back = Shortcut::new(Some(Modifiers::SUPER), Code::BracketLeft);
    let forward = Shortcut::new(Some(Modifiers::SUPER), Code::BracketRight);
    let new_window_shortcut = Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::KeyN);
    let open_settings = Shortcut::new(Some(Modifiers::SUPER), Code::Comma);

    let app_handle = app.clone();

    app.global_shortcut().on_shortcuts(
        [new_chat, reload, back, forward, new_window_shortcut, open_settings],
        move |_app, shortcut, _event| {
            let state = app_handle.state::<ConfigState>();
            let server_url = state.0.read().unwrap().server_url.clone();

            if let Some(window) = app_handle.get_webview_window("main") {
                if shortcut == &new_chat {
                    let url = format!("{}/chat", server_url);
                    let _ = window.eval(&format!("window.location.href = '{}'", url));
                } else if shortcut == &reload {
                    let _ = window.eval("window.location.reload()");
                } else if shortcut == &back {
                    let _ = window.eval("window.history.back()");
                } else if shortcut == &forward {
                    let _ = window.eval("window.history.forward()");
                } else if shortcut == &open_settings {
                    // Open config file for editing
                    let _ = open_config_file();
                }
            }

            if shortcut == &new_window_shortcut {
                let handle = app_handle.clone();
                let url = server_url.clone();
                tauri::async_runtime::spawn(async move {
                    let window_label = format!("onyx-{}", uuid::Uuid::new_v4());
                    if let Ok(window) = WebviewWindowBuilder::new(
                        &handle,
                        &window_label,
                        WebviewUrl::External(url.parse().unwrap()),
                    )
                    .title("Onyx")
                    .inner_size(1200.0, 800.0)
                    .min_inner_size(800.0, 600.0)
                    .transparent(true)
                    .title_bar_style(tauri::TitleBarStyle::Overlay)
                    .hidden_title(true)
                    .build() {
                        // Apply vibrancy
                        #[cfg(target_os = "macos")]
                        {
                            let _ = apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None);
                        }

                        // Inject title bar (with retries)
                        let window_clone = window.clone();
                        tauri::async_runtime::spawn(async move {
                            let titlebar_script = include_str!("../../src/titlebar.js");
                            for i in 0..5 {
                                sleep(Duration::from_millis(1000 + i * 1000)).await;
                                let _ = window_clone.eval(titlebar_script);
                            }
                        });
                    }
                });
            }
        },
    )?;

    Ok(())
}

// ============================================================================
// Main
// ============================================================================

fn main() {
    // Load config at startup
    let config = load_config();
    let server_url = config.server_url.clone();
    
    println!("Starting Onyx Desktop");
    println!("Server URL: {}", server_url);
    if let Some(path) = get_config_path() {
        println!("Config file: {:?}", path);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .manage(ConfigState(RwLock::new(config)))
        .invoke_handler(tauri::generate_handler![
            get_server_url,
            set_server_url,
            get_config_path_cmd,
            open_config_file,
            open_config_directory,
            navigate_to,
            reload_page,
            go_back,
            go_forward,
            new_window,
            reset_config,
            start_drag_window
        ])
        .setup(move |app| {
            // Setup global shortcuts
            if let Err(e) = setup_shortcuts(app.handle()) {
                eprintln!("Failed to setup shortcuts: {}", e);
            }

            // Update main window URL to configured server and inject title bar
            if let Some(window) = app.get_webview_window("main") {
                // Apply vibrancy effect for translucent glass look
                #[cfg(target_os = "macos")]
                {
                    let _ = apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None);
                }

                let _ = window.eval(&format!("window.location.href = '{}'", server_url));

                // Inject title bar script after page loads (with retries)
                let window_clone = window.clone();
                tauri::async_runtime::spawn(async move {
                    let titlebar_script = include_str!("../../src/titlebar.js");

                    // Try injecting multiple times to ensure it works
                    for i in 0..5 {
                        sleep(Duration::from_millis(1000 + i * 1000)).await;
                        let _ = window_clone.eval(titlebar_script);
                    }
                });

                let _ = window.set_focus();
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
