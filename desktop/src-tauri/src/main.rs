// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::RwLock;
#[cfg(target_os = "macos")]
use std::time::Duration;
use tauri::image::Image;
use tauri::menu::{
    CheckMenuItem, Menu, MenuBuilder, MenuItem, PredefinedMenuItem, SubmenuBuilder, HELP_SUBMENU_ID,
};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
#[cfg(target_os = "macos")]
use tauri::WebviewWindow;
use tauri::Wry;
use tauri::{
    webview::PageLoadPayload, AppHandle, Manager, Webview, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};
#[cfg(target_os = "macos")]
use tokio::time::sleep;
use url::Url;
#[cfg(target_os = "macos")]
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};

// ============================================================================
// Configuration
// ============================================================================

const DEFAULT_SERVER_URL: &str = "https://cloud.onyx.app";
const CONFIG_FILE_NAME: &str = "config.json";
#[cfg(target_os = "macos")]
const TITLEBAR_SCRIPT: &str = include_str!("../../src/titlebar.js");
const TRAY_ID: &str = "onyx-tray";
const TRAY_ICON_BYTES: &[u8] = include_bytes!("../icons/tray-icon.png");
const TRAY_MENU_OPEN_APP_ID: &str = "tray_open_app";
const TRAY_MENU_OPEN_CHAT_ID: &str = "tray_open_chat";
const TRAY_MENU_SHOW_IN_BAR_ID: &str = "tray_show_in_menu_bar";
const TRAY_MENU_QUIT_ID: &str = "tray_quit";

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
    ProjectDirs::from("app", "onyx", "onyx-desktop").map(|dirs| dirs.config_dir().to_path_buf())
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

fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    } else {
        trigger_new_window(app);
    }
}

fn trigger_new_chat(app: &AppHandle) {
    let state = app.state::<ConfigState>();
    let server_url = state.0.read().unwrap().server_url.clone();

    if let Some(window) = app.get_webview_window("main") {
        let url = format!("{}/chat", server_url);
        let _ = window.eval(&format!("window.location.href = '{}'", url));
    }
}

fn trigger_new_window(app: &AppHandle) {
    let state = app.state::<ConfigState>();
    let server_url = state.0.read().unwrap().server_url.clone();
    let handle = app.clone();

    tauri::async_runtime::spawn(async move {
        let window_label = format!("onyx-{}", uuid::Uuid::new_v4());
        let builder = WebviewWindowBuilder::new(
            &handle,
            &window_label,
            WebviewUrl::External(server_url.parse().unwrap()),
        )
        .title("Onyx")
        .inner_size(1200.0, 800.0)
        .min_inner_size(800.0, 600.0)
        .transparent(true);

        #[cfg(target_os = "macos")]
        let builder = builder
            .title_bar_style(tauri::TitleBarStyle::Overlay)
            .hidden_title(true);

        #[cfg(target_os = "linux")]
        let builder = builder.background_color(tauri::window::Color(0x1a, 0x1a, 0x2e, 0xff));

        if let Ok(window) = builder.build() {
            #[cfg(target_os = "macos")]
            {
                let _ = apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None);
                inject_titlebar(window.clone());
            }

            let _ = window.set_focus();
        }
    });
}

fn open_docs() {
    let url = "https://docs.onyx.app";
    #[cfg(target_os = "macos")]
    {
        let _ = Command::new("open").arg(url).status();
    }
    #[cfg(target_os = "linux")]
    {
        let _ = Command::new("xdg-open").arg(url).status();
    }
    #[cfg(target_os = "windows")]
    {
        let _ = Command::new("rundll32")
            .arg("url.dll,FileProtocolHandler")
            .arg(url)
            .status();
    }
}

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

    let builder = WebviewWindowBuilder::new(
        &app,
        &window_label,
        WebviewUrl::External(
            server_url
                .parse()
                .map_err(|e| format!("Invalid URL: {}", e))?,
        ),
    )
    .title("Onyx")
    .inner_size(1200.0, 800.0)
    .min_inner_size(800.0, 600.0)
    .transparent(true);

    #[cfg(target_os = "macos")]
    let builder = builder
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true);

    #[cfg(target_os = "linux")]
    let builder = builder.background_color(tauri::window::Color(0x1a, 0x1a, 0x2e, 0xff));

    #[cfg(target_os = "macos")]
    {
        let window = builder.build().map_err(|e| e.to_string())?;
        // Apply vibrancy effect and inject titlebar
        let _ = apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None);
        inject_titlebar(window.clone());
    }

    #[cfg(not(target_os = "macos"))]
    {
        let _window = builder.build().map_err(|e| e.to_string())?;
    }

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

#[cfg(target_os = "macos")]
fn inject_titlebar(window: WebviewWindow) {
    let script = TITLEBAR_SCRIPT.to_string();
    tauri::async_runtime::spawn(async move {
        // Keep trying for a few seconds to survive navigations and slow loads
        let delays = [0u64, 200, 600, 1200, 2000, 4000, 6000, 8000, 10000];
        for delay in delays {
            if delay > 0 {
                sleep(Duration::from_millis(delay)).await;
            }
            let _ = window.eval(&script);
        }
    });
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
    let show_app = Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::Space);
    let open_settings = Shortcut::new(Some(Modifiers::SUPER), Code::Comma);

    let app_handle = app.clone();

    // Avoid hijacking the system-wide Cmd+R on macOS.
    #[cfg(target_os = "macos")]
    let shortcuts = [
        new_chat,
        back,
        forward,
        new_window_shortcut,
        show_app,
        open_settings,
    ];

    #[cfg(not(target_os = "macos"))]
    let shortcuts = [
        new_chat,
        reload,
        back,
        forward,
        new_window_shortcut,
        show_app,
        open_settings,
    ];

    app.global_shortcut().on_shortcuts(
        shortcuts,
        move |_app, shortcut, _event| {
            if shortcut == &new_chat {
                trigger_new_chat(&app_handle);
            }

            if let Some(window) = app_handle.get_webview_window("main") {
                if shortcut == &reload {
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
                trigger_new_window(&app_handle);
            } else if shortcut == &show_app {
                focus_main_window(&app_handle);
            }
        },
    )?;

    Ok(())
}

// ============================================================================
// Menu Setup
// ============================================================================

fn setup_app_menu(app: &AppHandle) -> tauri::Result<()> {
    let menu = app.menu().unwrap_or(Menu::default(app)?);

    let new_chat_item = MenuItem::with_id(app, "new_chat", "New Chat", true, Some("CmdOrCtrl+N"))?;
    let new_window_item = MenuItem::with_id(
        app,
        "new_window",
        "New Window",
        true,
        Some("CmdOrCtrl+Shift+N"),
    )?;
    let docs_item = MenuItem::with_id(app, "open_docs", "Onyx Documentation", true, None::<&str>)?;

    if let Some(file_menu) = menu
        .items()?
        .into_iter()
        .filter_map(|item| item.as_submenu().cloned())
        .find(|submenu| submenu.text().ok().as_deref() == Some("File"))
    {
        file_menu.insert_items(&[&new_chat_item, &new_window_item], 0)?;
    } else {
        let file_menu = SubmenuBuilder::new(app, "File")
            .items(&[
                &new_chat_item,
                &new_window_item,
                &PredefinedMenuItem::close_window(app, None)?,
            ])
            .build()?;
        menu.prepend(&file_menu)?;
    }

    if let Some(help_menu) = menu
        .get(HELP_SUBMENU_ID)
        .and_then(|item| item.as_submenu().cloned())
    {
        help_menu.append(&docs_item)?;
    } else {
        let help_menu = SubmenuBuilder::with_id(app, HELP_SUBMENU_ID, "Help")
            .item(&docs_item)
            .build()?;
        menu.append(&help_menu)?;
    }

    app.set_menu(menu)?;
    Ok(())
}

fn build_tray_menu(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let open_app = MenuItem::with_id(
        app,
        TRAY_MENU_OPEN_APP_ID,
        "Open Onyx",
        true,
        Some("CmdOrCtrl+Shift+Space"),
    )?;
    let open_chat = MenuItem::with_id(
        app,
        TRAY_MENU_OPEN_CHAT_ID,
        "Open Chat Window",
        true,
        None::<&str>,
    )?;
    let show_in_menu_bar = CheckMenuItem::with_id(
        app,
        TRAY_MENU_SHOW_IN_BAR_ID,
        "Show in Menu Bar",
        true,
        true,
        None::<&str>,
    )?;
    // Keep it visible/pinned without letting users uncheck (avoids orphaning the tray)
    let _ = show_in_menu_bar.set_enabled(false);
    let quit = PredefinedMenuItem::quit(app, Some("Quit Onyx"))?;

    MenuBuilder::new(app)
        .item(&open_app)
        .item(&open_chat)
        .separator()
        .item(&show_in_menu_bar)
        .separator()
        .item(&quit)
        .build()
}

fn handle_tray_menu_event(app: &AppHandle, id: &str) {
    match id {
        TRAY_MENU_OPEN_APP_ID => {
            focus_main_window(app);
        }
        TRAY_MENU_OPEN_CHAT_ID => {
            focus_main_window(app);
            trigger_new_chat(app);
        }
        TRAY_MENU_QUIT_ID => {
            app.exit(0);
        }
        TRAY_MENU_SHOW_IN_BAR_ID => {
            // No-op for now; the item stays checked/disabled to indicate it's pinned.
        }
        _ => {}
    }
}

fn setup_tray_icon(app: &AppHandle) -> tauri::Result<()> {
    let mut builder = TrayIconBuilder::with_id(TRAY_ID).tooltip("Onyx");

    let tray_icon = Image::from_bytes(TRAY_ICON_BYTES)
        .ok()
        .or_else(|| app.default_window_icon().cloned());

    if let Some(icon) = tray_icon {
        builder = builder.icon(icon);

        #[cfg(target_os = "macos")]
        {
            builder = builder.icon_as_template(true);
        }
    }

    if let Ok(menu) = build_tray_menu(app) {
        builder = builder.menu(&menu);
    }

    builder
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { .. } = event {
                focus_main_window(tray.app_handle());
            }
        })
        .on_menu_event(|app, event| handle_tray_menu_event(app, event.id().as_ref()))
        .build(app)?;

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
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open_docs" => open_docs(),
            "new_chat" => trigger_new_chat(app),
            "new_window" => trigger_new_window(app),
            _ => {}
        })
        .setup(move |app| {
            let app_handle = app.handle();

            // Setup global shortcuts
            if let Err(e) = setup_shortcuts(&app_handle) {
                eprintln!("Failed to setup shortcuts: {}", e);
            }

            if let Err(e) = setup_app_menu(&app_handle) {
                eprintln!("Failed to setup menu: {}", e);
            }

            if let Err(e) = setup_tray_icon(&app_handle) {
                eprintln!("Failed to setup tray icon: {}", e);
            }

            // Update main window URL to configured server and inject title bar
            if let Some(window) = app.get_webview_window("main") {
                // Apply vibrancy effect for translucent glass look
                #[cfg(target_os = "macos")]
                {
                    let _ = apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None);
                }

                if let Ok(target) = Url::parse(&server_url) {
                    if let Ok(current) = window.url() {
                        if current != target {
                            let _ = window.navigate(target);
                        }
                    } else {
                        let _ = window.navigate(target);
                    }
                }

                #[cfg(target_os = "macos")]
                inject_titlebar(window.clone());

                let _ = window.set_focus();
            }

            Ok(())
        })
        .on_page_load(|_webview: &Webview, _payload: &PageLoadPayload| {
            // Re-inject titlebar after every navigation/page load (macOS only)
            #[cfg(target_os = "macos")]
            let _ = _webview.eval(TITLEBAR_SCRIPT);
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
