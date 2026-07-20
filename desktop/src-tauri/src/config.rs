use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::{Mutex, RwLock};
use url::Url;

pub const DEFAULT_SERVER_URL: &str = "https://cloud.onyx.app";
const CONFIG_FILE_NAME: &str = "config.json";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub server_url: String,

    #[serde(default = "default_window_title")]
    pub window_title: String,

    #[serde(default = "default_show_menu_bar")]
    pub show_menu_bar: bool,

    #[serde(default)]
    pub hide_window_decorations: bool,
}

fn default_window_title() -> String {
    "Onyx".to_string()
}

fn default_show_menu_bar() -> bool {
    true
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            server_url: DEFAULT_SERVER_URL.to_string(),
            window_title: default_window_title(),
            show_menu_bar: true,
            hide_window_decorations: false,
        }
    }
}

/// Get the config directory path
pub fn get_config_dir() -> Option<PathBuf> {
    ProjectDirs::from("app", "onyx", "onyx-desktop").map(|dirs| dirs.config_dir().to_path_buf())
}

/// Get the full config file path
pub fn get_config_path() -> Option<PathBuf> {
    get_config_dir().map(|dir| dir.join(CONFIG_FILE_NAME))
}

/// Load config from file, or create default if it doesn't exist
pub fn load_config() -> (AppConfig, bool) {
    let config_path = match get_config_path() {
        Some(path) => path,
        None => {
            return (AppConfig::default(), false);
        }
    };

    if !config_path.exists() {
        return (AppConfig::default(), false);
    }

    match fs::read_to_string(&config_path) {
        Ok(contents) => match serde_json::from_str(&contents) {
            Ok(config) => (config, true),
            Err(_) => (AppConfig::default(), false),
        },
        Err(_) => (AppConfig::default(), false),
    }
}

/// Save config to file
pub fn save_config(config: &AppConfig) -> Result<(), String> {
    let config_dir = get_config_dir().ok_or("Could not determine config directory")?;
    let config_path = config_dir.join(CONFIG_FILE_NAME);

    // Ensure config directory exists
    fs::create_dir_all(&config_dir).map_err(|e| format!("Failed to create config dir: {}", e))?;

    let json = serde_json::to_string_pretty(config)
        .map_err(|e| format!("Failed to serialize config: {}", e))?;

    fs::write(&config_path, json).map_err(|e| format!("Failed to write config: {}", e))?;

    Ok(())
}

/// Shared app state: the live config plus a few process-lifetime flags. All
/// fields are behind locks so this can be safely handed out as managed Tauri
/// state and accessed from any thread/command.
pub struct ConfigState {
    config: RwLock<AppConfig>,
    config_initialized: RwLock<bool>,
    app_base_url: RwLock<Option<Url>>,
    pub debug_mode: bool,
    pub debug_log_file: Mutex<Option<fs::File>>,
}

impl ConfigState {
    pub fn new(
        config: AppConfig,
        config_initialized: bool,
        debug_mode: bool,
        debug_log_file: Option<fs::File>,
    ) -> Self {
        Self {
            config: RwLock::new(config),
            config_initialized: RwLock::new(config_initialized),
            app_base_url: RwLock::new(None),
            debug_mode,
            debug_log_file: Mutex::new(debug_log_file),
        }
    }

    /// A snapshot of the current config. A panic elsewhere while holding the
    /// write lock poisons it; recovering via `into_inner` means one bad
    /// mutation can't take down every future read.
    pub fn config(&self) -> AppConfig {
        self.config
            .read()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    /// Apply `f` to the config and return the resulting snapshot.
    pub fn update_config(&self, f: impl FnOnce(&mut AppConfig)) -> AppConfig {
        let mut guard = self.config.write().unwrap_or_else(|e| e.into_inner());
        f(&mut guard);
        guard.clone()
    }

    pub fn is_config_initialized(&self) -> bool {
        *self
            .config_initialized
            .read()
            .unwrap_or_else(|e| e.into_inner())
    }

    pub fn set_config_initialized(&self, value: bool) {
        *self
            .config_initialized
            .write()
            .unwrap_or_else(|e| e.into_inner()) = value;
    }

    pub fn app_base_url(&self) -> Option<Url> {
        self.app_base_url
            .read()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    pub fn set_app_base_url(&self, url: Option<Url>) {
        *self.app_base_url.write().unwrap_or_else(|e| e.into_inner()) = url;
    }
}
