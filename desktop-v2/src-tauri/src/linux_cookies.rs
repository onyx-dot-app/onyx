//! WebKitGTK keeps cookies in memory only.
//!
//! wry writes cookies to a text file in the app's data directory, so the
//! server's session cookie (it has a `Max-Age`) sat on disk in plain text,
//! outside the Secret Service. The app hands the session to the main window
//! each time it opens the window, so cookies need not outlive the process.
//! Local storage and the HTTP cache stay on disk.

use std::path::Path;

/// The file that wry gives WebKit for cookies.
const COOKIE_FILE: &str = "cookies";

/// Removes the cookie file that older builds wrote. Returns whether a file was there.
pub fn remove_cookie_file(data_dir: &Path) -> std::io::Result<bool> {
    match std::fs::remove_file(data_dir.join(COOKIE_FILE)) {
        Ok(()) => Ok(true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(e),
    }
}

/// Runs at startup, before the first web view loads.
#[cfg(target_os = "linux")]
pub fn remove_old_cookies(app: &tauri::AppHandle) {
    use tauri::Manager;
    let Ok(dir) = app.path().app_local_data_dir() else {
        return;
    };
    match remove_cookie_file(&dir) {
        Ok(true) => log::info!("removed the old cookie file"),
        Ok(false) => {}
        Err(e) => log::warn!("could not remove the old cookie file: {e}"),
    }
}

/// Points the shared cookie store at an SQLite in-memory database: libsoup
/// keeps every cookie in memory and writes nothing to disk. WebKit ignores the
/// call when the storage is already set, so each new web view may call it.
#[cfg(target_os = "linux")]
pub fn plugin() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    tauri::plugin::Builder::new("onyx-memory-cookies")
        .on_webview_ready(|webview| {
            let result = webview.with_webview(|platform| {
                use webkit2gtk::{
                    CookieManagerExt, CookiePersistentStorage, WebContextExt, WebViewExt,
                    WebsiteDataManagerExt,
                };
                let manager = WebViewExt::context(&platform.inner())
                    .and_then(|context| context.website_data_manager())
                    .and_then(|data| data.cookie_manager());
                match manager {
                    Some(manager) => {
                        manager.set_persistent_storage(":memory:", CookiePersistentStorage::Sqlite)
                    }
                    None => log::warn!("the web view has no cookie manager"),
                }
            });
            if let Err(e) = result {
                log::warn!("could not keep cookies in memory: {e}");
            }
        })
        .build()
}

#[cfg(test)]
mod tests {
    use super::remove_cookie_file;

    #[test]
    fn removes_the_old_cookie_file_once() {
        let dir = std::env::temp_dir().join(format!("onyx-cookie-file-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("cookies"), "# Netscape HTTP Cookie File\n").unwrap();
        std::fs::write(dir.join("localstorage"), "kept").unwrap();

        assert!(remove_cookie_file(&dir).unwrap());
        assert!(!dir.join("cookies").exists());
        assert!(dir.join("localstorage").exists());
        assert!(!remove_cookie_file(&dir).unwrap());

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn a_missing_data_directory_is_not_an_error() {
        let dir = std::env::temp_dir().join(format!("onyx-no-data-{}", std::process::id()));
        assert!(!remove_cookie_file(&dir).unwrap());
    }
}
