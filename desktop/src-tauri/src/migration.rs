//! First-launch import of the settings of the apps that this app replaces.
//!
//! - The earlier desktop app (same bundle ID, `app.onyx.desktop`) kept its
//!   `config.json` in another folder, in snake_case. Its server URL and a
//!   custom summon shortcut are imported.
//! - The preview build (`app.onyx.desktop.v2`) used this app's format. Its
//!   settings are copied. Session tokens stay in its own credential store
//!   entries, so the user signs in again.
//!
//! The imported file is then renamed to `config.json.imported`: it stays as
//! a backup, and a launch after the user deletes this app's data does not
//! import it again.

use std::fs;
use std::path::{Path, PathBuf};
use std::str::FromStr;

use tauri::Manager;
use tauri_plugin_global_shortcut::Shortcut;

use crate::config::Config;

const PREVIEW_IDENTIFIER: &str = "app.onyx.desktop.v2";
/// The earlier app's default on this platform, which is not imported (this
/// app has its own).
const EARLIER_DEFAULT_SHORTCUT: &str = if cfg!(target_os = "macos") {
    "Super+Shift+Space"
} else {
    "Ctrl+Alt+Space"
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    Preview,
    Earlier,
}

/// The config files of the replaced apps, if this platform has a config dir.
pub struct Sources {
    pub preview: Option<PathBuf>,
    pub earlier: Option<PathBuf>,
}

impl Sources {
    pub fn find(app: &tauri::AppHandle) -> Self {
        let Ok(base) = app.path().config_dir() else {
            return Self {
                preview: None,
                earlier: None,
            };
        };
        Self {
            preview: Some(base.join(PREVIEW_IDENTIFIER).join("config.json")),
            earlier: Some(earlier_config_path(&base)),
        }
    }
}

/// Where the earlier app kept `config.json` (the `directories` crate's
/// project dirs for "app", "onyx", "onyx-desktop").
fn earlier_config_path(config_dir: &Path) -> PathBuf {
    let dir = if cfg!(target_os = "macos") {
        config_dir.join("app.onyx.onyx-desktop")
    } else if cfg!(target_os = "windows") {
        config_dir.join("onyx").join("onyx-desktop").join("config")
    } else {
        config_dir.join("onyx-desktop")
    };
    dir.join("config.json")
}

/// Writes `config_path` from a replaced app's settings when it does not exist
/// yet. Returns what was imported. Never fails the launch: a file that cannot
/// be read or parsed is skipped.
pub fn import_previous(config_path: &Path, sources: &Sources) -> Option<Source> {
    if config_path.exists() {
        return None;
    }
    let (config, source) = sources
        .preview
        .as_deref()
        .and_then(read_preview)
        .map(|c| (c, Source::Preview))
        .or_else(|| {
            sources
                .earlier
                .as_deref()
                .and_then(read_earlier)
                .map(|c| (c, Source::Earlier))
        })?;
    if let Err(e) = write(config_path, &config) {
        log::warn!("could not save the imported settings: {e}");
        return None;
    }
    let imported = match source {
        Source::Preview => sources.preview.as_deref(),
        Source::Earlier => sources.earlier.as_deref(),
    };
    if let Some(path) = imported {
        if let Err(e) = fs::rename(path, path.with_extension("json.imported")) {
            log::warn!("could not rename {}: {e}", path.display());
        }
    }
    Some(source)
}

fn read_json(path: &Path) -> Option<serde_json::Value> {
    let raw = fs::read_to_string(path).ok()?;
    let raw = raw.strip_prefix('\u{feff}').unwrap_or(&raw);
    match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(value) if value.is_object() => Some(value),
        Ok(_) => {
            log::warn!("{} is not a JSON object; not imported", path.display());
            None
        }
        Err(e) => {
            log::warn!("{} is not valid JSON; not imported: {e}", path.display());
            None
        }
    }
}

fn read_preview(path: &Path) -> Option<Config> {
    let mut config: Config = match serde_json::from_value(read_json(path)?) {
        Ok(config) => config,
        Err(e) => {
            log::warn!(
                "{} has values of the wrong type; not imported: {e}",
                path.display()
            );
            return None;
        }
    };
    // The preview's tokens are under its own credential service, and the
    // managed server is read again from the policy.
    config.session_servers.clear();
    config.managed_server_url = None;
    Some(config)
}

fn read_earlier(path: &Path) -> Option<Config> {
    let value = read_json(path)?;
    let server_url = value
        .get("server_url")
        .and_then(serde_json::Value::as_str)
        .and_then(|url| match crate::api::normalize_server_url(url) {
            Ok(url) => Some(url),
            Err(e) => {
                log::warn!("the earlier app's server URL is not imported: {e}");
                None
            }
        });
    let hotkey = value
        .get("summon_shortcut")
        .and_then(serde_json::Value::as_str)
        .map(str::trim)
        .filter(|s| *s != EARLIER_DEFAULT_SHORTCUT && Shortcut::from_str(s).is_ok())
        .map(str::to_string);
    if server_url.is_none() && hotkey.is_none() {
        return None;
    }
    Some(Config {
        server_url,
        hotkey,
        ..Config::default()
    })
}

/// Written beside the file, then renamed over it, as `ConfigStore` does.
fn write(path: &Path, config: &Config) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let raw = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, raw).map_err(|e| e.to_string())?;
    fs::rename(&tmp, path).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::ConfigStore;

    struct Dirs {
        root: PathBuf,
        target: PathBuf,
        sources: Sources,
    }

    impl Drop for Dirs {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn dirs(name: &str) -> Dirs {
        let root =
            std::env::temp_dir().join(format!("onyx-migration-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        Dirs {
            target: root.join("app.onyx.desktop").join("config.json"),
            sources: Sources {
                preview: Some(root.join(PREVIEW_IDENTIFIER).join("config.json")),
                earlier: Some(earlier_config_path(&root)),
            },
            root,
        }
    }

    fn put(path: &Path, contents: &str) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, contents).unwrap();
    }

    fn earlier(d: &Dirs) -> &Path {
        d.sources.earlier.as_deref().unwrap()
    }

    fn preview(d: &Dirs) -> &Path {
        d.sources.preview.as_deref().unwrap()
    }

    #[test]
    fn imports_the_earlier_server_url_and_keeps_a_backup() {
        let d = dirs("earlier");
        put(
            earlier(&d),
            &format!(
                r#"{{"server_url": "https://onyx.example.com/", "window_title": "Onyx",
                "show_menu_bar": false, "summon_shortcut": "{EARLIER_DEFAULT_SHORTCUT}",
                "summon_opens_new_chat": true, "future_key": [1, 2]}}"#
            ),
        );
        assert_eq!(
            import_previous(&d.target, &d.sources),
            Some(Source::Earlier)
        );
        let config = ConfigStore::load(d.target.clone()).get();
        assert_eq!(
            config.server_url.as_deref(),
            Some("https://onyx.example.com")
        );
        assert_eq!(config.hotkey, None);
        assert!(!earlier(&d).exists());
        assert!(earlier(&d).with_extension("json.imported").exists());
        // Once only.
        fs::remove_file(&d.target).unwrap();
        assert_eq!(import_previous(&d.target, &d.sources), None);
    }

    #[test]
    fn imports_a_custom_earlier_shortcut() {
        let d = dirs("shortcut");
        put(
            earlier(&d),
            r#"{"server_url": "https://onyx.example.com", "summon_shortcut": "Alt+Space"}"#,
        );
        import_previous(&d.target, &d.sources);
        assert_eq!(
            ConfigStore::load(d.target.clone()).get().hotkey(),
            "Alt+Space"
        );
    }

    #[test]
    fn the_other_platforms_default_is_a_custom_shortcut() {
        let other = if cfg!(target_os = "macos") {
            "Ctrl+Alt+Space"
        } else {
            "Super+Shift+Space"
        };
        let d = dirs("other-default");
        put(
            earlier(&d),
            &format!(
                r#"{{"server_url": "https://onyx.example.com", "summon_shortcut": "{other}"}}"#
            ),
        );
        import_previous(&d.target, &d.sources);
        assert_eq!(ConfigStore::load(d.target.clone()).get().hotkey(), other);
    }

    #[test]
    fn skips_earlier_values_that_do_not_map() {
        let d = dirs("bad-values");
        put(
            earlier(&d),
            r#"{"server_url": "ftp://onyx.example.com", "summon_shortcut": "Not A Key"}"#,
        );
        assert_eq!(import_previous(&d.target, &d.sources), None);
        assert!(!d.target.exists());
        assert!(earlier(&d).exists());

        put(
            earlier(&d),
            r#"{"server_url": 42, "summon_shortcut": null}"#,
        );
        assert_eq!(import_previous(&d.target, &d.sources), None);
    }

    #[test]
    fn broken_files_are_not_imported() {
        let d = dirs("broken");
        put(earlier(&d), r#"{"server_url": "https://onyx.example.com""#);
        put(preview(&d), "[]");
        assert_eq!(import_previous(&d.target, &d.sources), None);
        assert!(!d.target.exists());
        put(preview(&d), r#"{"serverUrl": 7}"#);
        assert_eq!(import_previous(&d.target, &d.sources), None);
    }

    #[test]
    fn imports_the_preview_once_without_its_session_record() {
        let d = dirs("preview");
        put(
            preview(&d),
            "\u{feff}{\"serverUrl\": \"https://preview.example.com\", \"hotkey\": \"Alt+Space\",
              \"sessionServers\": [\"https://preview.example.com\"],
              \"managedServerUrl\": \"https://preview.example.com\", \"unknown\": true}",
        );
        put(
            earlier(&d),
            r#"{"server_url": "https://earlier.example.com"}"#,
        );
        assert_eq!(
            import_previous(&d.target, &d.sources),
            Some(Source::Preview)
        );
        let config = ConfigStore::load(d.target.clone()).get();
        assert_eq!(
            config.server_url.as_deref(),
            Some("https://preview.example.com")
        );
        assert_eq!(config.hotkey(), "Alt+Space");
        assert!(config.session_servers.is_empty());
        assert_eq!(config.managed_server_url, None);
        assert!(!preview(&d).exists());
        assert!(preview(&d).with_extension("json.imported").exists());
        assert!(earlier(&d).exists());
        // Deleting this app's data does not bring the preview's settings back.
        fs::remove_file(&d.target).unwrap();
        assert_eq!(
            import_previous(&d.target, &d.sources),
            Some(Source::Earlier)
        );
        let config = ConfigStore::load(d.target.clone()).get();
        assert_eq!(
            config.server_url.as_deref(),
            Some("https://earlier.example.com")
        );
        fs::remove_file(&d.target).unwrap();
        assert_eq!(import_previous(&d.target, &d.sources), None);
    }

    #[test]
    fn an_existing_config_is_never_replaced() {
        let d = dirs("existing");
        put(&d.target, r#"{"serverUrl": "https://mine.example.com"}"#);
        put(
            earlier(&d),
            r#"{"server_url": "https://earlier.example.com"}"#,
        );
        assert_eq!(import_previous(&d.target, &d.sources), None);
        let config = ConfigStore::load(d.target.clone()).get();
        assert_eq!(
            config.server_url.as_deref(),
            Some("https://mine.example.com")
        );
        assert!(earlier(&d).exists());
    }

    #[test]
    fn earlier_config_paths_match_the_earlier_app() {
        let path = earlier_config_path(Path::new("/c"));
        let expected = if cfg!(target_os = "macos") {
            "/c/app.onyx.onyx-desktop/config.json"
        } else if cfg!(target_os = "windows") {
            "/c/onyx/onyx-desktop/config/config.json"
        } else {
            "/c/onyx-desktop/config.json"
        };
        assert_eq!(path, Path::new(expected));
    }
}
