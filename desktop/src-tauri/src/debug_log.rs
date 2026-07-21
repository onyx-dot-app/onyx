use crate::config::{get_config_dir, ConfigState};
use crate::window::open_in_default_browser;
use std::fs;
use std::io::Write as IoWrite;
use std::path::PathBuf;
use std::time::SystemTime;
use tauri::{AppHandle, Manager, Webview};

pub const MENU_TOGGLE_DEVTOOLS_ID: &str = "toggle_devtools";
pub const MENU_OPEN_DEBUG_LOG_ID: &str = "open_debug_log";

const CONSOLE_CAPTURE_SCRIPT: &str = include_str!("scripts/console_capture.js");

pub fn is_debug_mode(cli_debug: bool) -> bool {
    cli_debug || std::env::var("ONYX_DEBUG").is_ok()
}

pub fn get_debug_log_path() -> Option<PathBuf> {
    get_config_dir().map(|dir| dir.join("frontend_debug.log"))
}

pub fn init_debug_log_file() -> Option<fs::File> {
    let log_path = get_debug_log_path()?;
    if let Some(parent) = log_path.parent() {
        if let Err(e) = fs::create_dir_all(parent) {
            eprintln!(
                "[ONYX ERROR] Failed to create debug log directory {}: {e}",
                parent.display()
            );
        }
    }

    match fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
    {
        Ok(file) => Some(file),
        Err(e) => {
            eprintln!(
                "[ONYX ERROR] Failed to open debug log file {}: {e}",
                log_path.display()
            );
            None
        }
    }
}

pub fn format_utc_timestamp() -> String {
    let now = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default();
    let total_secs = now.as_secs();
    let millis = now.subsec_millis();

    let days = total_secs / 86400;
    let secs_of_day = total_secs % 86400;
    let hours = secs_of_day / 3600;
    let mins = (secs_of_day % 3600) / 60;
    let secs = secs_of_day % 60;

    // Days since Unix epoch -> Y/M/D via civil calendar arithmetic
    let z = days as i64 + 719468;
    let era = z / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };

    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        y, m, d, hours, mins, secs, millis
    )
}

/// Surface a Rust-side failure the same way frontend errors already are:
/// always to stderr, and also into the debug log file when debug mode is on.
/// Used in place of silently swallowing a `Result` with `let _ = ...` for
/// failures worth knowing about.
pub fn log_backend_error(app: &AppHandle, message: &str) {
    eprintln!("[ONYX ERROR] {}", message);

    let state = app.state::<ConfigState>();
    if !state.debug_mode {
        return;
    }
    // Bind the lock result to a named local rather than matching on it
    // directly in the `if let` scrutinee: `if let Ok(x) = mutex.lock() { }`
    // extends the whole `Result<MutexGuard, _>` temporary's lifetime to the
    // end of the enclosing block, which the borrow checker rejects here
    // since that block also owns `state` (the guard's ultimate borrow
    // source). A named binding is scoped by normal liveness instead.
    let lock_result = state.debug_log_file.lock();
    if let Ok(mut guard) = lock_result {
        if let Some(ref mut file) = *guard {
            let line = format!("[{}] [ERROR] {}", format_utc_timestamp(), message);
            let _ = writeln!(file, "{}", line);
            let _ = file.flush();
        }
    }
}

pub fn inject_console_capture(webview: &Webview) {
    if let Err(e) = webview.eval(CONSOLE_CAPTURE_SCRIPT) {
        log_backend_error(
            webview.app_handle(),
            &format!("Failed to inject console-capture script: {e}"),
        );
    }
}

pub fn maybe_open_devtools(app: &AppHandle, window: &tauri::WebviewWindow) {
    #[cfg(any(debug_assertions, feature = "devtools"))]
    {
        let state = app.state::<ConfigState>();
        if state.debug_mode {
            window.open_devtools();
        }
    }
    #[cfg(not(any(debug_assertions, feature = "devtools")))]
    {
        let _ = (app, window);
    }
}

pub fn handle_toggle_devtools(app: &AppHandle) {
    #[cfg(any(debug_assertions, feature = "devtools"))]
    {
        let windows: Vec<_> = app.webview_windows().into_values().collect();
        let any_open = windows.iter().any(|w| w.is_devtools_open());
        for window in &windows {
            if any_open {
                window.close_devtools();
            } else {
                window.open_devtools();
            }
        }
    }
    #[cfg(not(any(debug_assertions, feature = "devtools")))]
    {
        let _ = app;
    }
}

pub fn handle_open_debug_log() {
    let log_path = match get_debug_log_path() {
        Some(p) => p,
        None => return,
    };

    if !log_path.exists() {
        eprintln!("[ONYX DEBUG] Log file does not exist yet: {:?}", log_path);
        return;
    }

    let url_path = log_path.to_string_lossy().replace('\\', "/");
    if !open_in_default_browser(&format!("file:///{}", url_path.trim_start_matches('/'))) {
        eprintln!("[ONYX ERROR] Failed to open debug log at {:?}", log_path);
    }
}

/// Mirrors `console.log`/`warn`/`error`/etc. captured from the webview (see
/// `scripts/console_capture.js`) to stderr and the debug log file. Only
/// active in debug mode -- this is high-volume and not meant for normal runs.
#[tauri::command]
pub fn log_from_frontend(level: String, message: String, state: tauri::State<ConfigState>) {
    if !state.debug_mode {
        return;
    }
    let timestamp = format_utc_timestamp();
    let log_line = format!("[{}] [{}] {}", timestamp, level.to_uppercase(), message);

    eprintln!("{}", log_line);

    if let Ok(mut guard) = state.debug_log_file.lock() {
        if let Some(ref mut file) = *guard {
            let _ = writeln!(file, "{}", log_line);
            let _ = file.flush();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::format_utc_timestamp;

    #[test]
    fn timestamp_has_expected_shape() {
        let ts = format_utc_timestamp();
        // e.g. "2026-07-20T12:34:56.789Z"
        assert_eq!(ts.len(), 24);
        assert_eq!(ts.as_bytes()[4], b'-');
        assert_eq!(ts.as_bytes()[7], b'-');
        assert_eq!(ts.as_bytes()[10], b'T');
        assert_eq!(ts.as_bytes()[13], b':');
        assert_eq!(ts.as_bytes()[16], b':');
        assert_eq!(ts.as_bytes()[19], b'.');
        assert!(ts.ends_with('Z'));
    }
}
