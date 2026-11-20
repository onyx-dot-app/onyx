//! Debug-only QA harness. Drives the running app with real AppKit events posted
//! to its own event queue (no Accessibility permission needed), so keyboard
//! shortcuts go through menu key equivalents and the web view, and drags go
//! through Tauri's drag handler, as if a person did them.
//!
//! Protocol: write one action to a temporary file in `<dir>` and rename it to
//! `<name>.json` when complete (the harness reads any `.json` it sees). The app
//! deletes the request and answers in `<name>.out.json`, which appears only
//! once fully written. The harness can drive signed-in windows, so it only
//! runs when the app is started with `ONYX_DESKTOP_QA_DIR` set to a directory
//! that the current user owns and nobody else can access (mode 0700; it is
//! created that way if missing). A plain debug launch never reads requests. Global shortcuts cannot be posted from
//! inside the app (macOS routes them before any app sees the key), so
//! `shortcut` reports registration and `toggle_launcher` calls its handler.

use std::path::{Path, PathBuf};
use std::sync::{mpsc, OnceLock};
use std::thread;
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

use crate::state::AppState;
use crate::{menu, shortcut, windows};

/// The QA directory, if this launch opted in with a private directory.
fn qa_dir() -> Option<&'static Path> {
    static DIR: OnceLock<Option<PathBuf>> = OnceLock::new();
    DIR.get_or_init(|| {
        if !cfg!(debug_assertions) {
            return None;
        }
        let dir = PathBuf::from(std::env::var_os("ONYX_DESKTOP_QA_DIR")?);
        // Later file access uses the checked, resolved path.
        match private_dir(&dir).and_then(|()| dir.canonicalize().map_err(|e| e.to_string())) {
            Ok(dir) => Some(dir),
            Err(e) => {
                log::warn!("QA harness off: {e}");
                None
            }
        }
    })
    .as_deref()
}

/// Creates `dir` owner-only if missing, and accepts it only if it is a real
/// directory (not a symlink) owned by this process's effective user that no
/// one else can access. Nothing is written inside it before that check.
#[cfg(unix)]
fn private_dir(dir: &Path) -> Result<(), String> {
    use std::os::unix::fs::{DirBuilderExt, MetadataExt};
    if !dir.exists() {
        std::fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(dir)
            .map_err(|e| format!("could not create {}: {e}", dir.display()))?;
    }
    let meta = std::fs::symlink_metadata(dir).map_err(|e| e.to_string())?;
    // SAFETY: geteuid has no preconditions and cannot fail.
    let uid = unsafe { libc::geteuid() };
    if !meta.file_type().is_dir() || meta.uid() != uid || meta.mode() & 0o077 != 0 {
        return Err(format!(
            "{} must be a directory owned by this user with mode 0700",
            dir.display()
        ));
    }
    Ok(())
}

/// Device, inode, owner and mode of the checked folder, to notice a
/// replacement after startup.
#[cfg(unix)]
fn dir_identity(dir: &Path) -> Option<(u64, u64, u32, u32)> {
    use std::os::unix::fs::MetadataExt;
    let meta = std::fs::symlink_metadata(dir).ok()?;
    meta.file_type()
        .is_dir()
        .then(|| (meta.dev(), meta.ino(), meta.uid(), meta.mode()))
}

#[cfg(not(unix))]
fn dir_identity(_dir: &Path) -> Option<(u64, u64, u32, u32)> {
    None
}

#[cfg(not(unix))]
fn private_dir(_dir: &Path) -> Result<(), String> {
    Err("the QA harness needs a Unix permission check".into())
}

/// Appends a timestamped line to `<qa dir>/events.log` while the QA dir exists.
pub fn log(line: &str) {
    let Some(dir) = qa_dir() else {
        return;
    };
    let millis = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or_default();
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("events.log"))
    {
        use std::io::Write;
        let _ = writeln!(file, "{millis} {line}");
    }
}

pub fn start(app: &AppHandle) {
    let Some(dir) = qa_dir() else {
        return;
    };
    let Some(identity) = dir_identity(dir) else {
        return;
    };
    let app = app.clone();
    thread::spawn(move || loop {
        // A folder that was removed and recreated (for example by another
        // user under a shared /tmp) is not the one that was checked.
        if dir_identity(dir) != Some(identity) {
            log::warn!("QA harness off: {} was removed or replaced", dir.display());
            return;
        }
        if let Ok(entries) = std::fs::read_dir(dir) {
            let mut requests: Vec<PathBuf> = entries
                .filter_map(|e| e.ok().map(|e| e.path()))
                .filter(|p| p.extension().is_some_and(|x| x == "json"))
                .filter(|p| !p.to_string_lossy().ends_with(".out.json"))
                .collect();
            requests.sort();
            for request in requests {
                handle_request(&app, &request);
            }
        }
        thread::sleep(Duration::from_millis(150));
    });
}

fn handle_request(app: &AppHandle, request: &Path) {
    let Ok(raw) = std::fs::read_to_string(request) else {
        return;
    };
    // A request that cannot be removed would run again on every poll.
    if std::fs::remove_file(request).is_err() {
        return;
    }
    let result = match serde_json::from_str::<Value>(&raw) {
        Ok(action) => run(app, &action).unwrap_or_else(|e| json!({ "error": e })),
        Err(e) => json!({ "error": format!("bad request: {e}") }),
    };
    // Written beside the answer, then renamed, so a reader never sees half.
    let out = request.with_extension("out.json");
    let partial = request.with_extension("out.json.partial");
    let body = serde_json::to_string_pretty(&result).unwrap_or_default();
    if std::fs::write(&partial, body).is_ok() {
        let _ = std::fs::rename(&partial, out);
    }
}

fn label(action: &Value) -> Result<String, String> {
    action
        .get("label")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| "missing label".to_string())
}

fn run(app: &AppHandle, action: &Value) -> Result<Value, String> {
    let op = action.get("op").and_then(Value::as_str).unwrap_or_default();
    match op {
        "windows" => Ok(window_list(app)),
        "focus" => {
            let window = app
                .get_webview_window(&label(action)?)
                .ok_or("no such window")?;
            window.unminimize().map_err(|e| e.to_string())?;
            window.show().map_err(|e| e.to_string())?;
            window.set_focus().map_err(|e| e.to_string())?;
            Ok(json!({ "ok": true }))
        }
        "bounds" => {
            let window = app
                .get_webview_window(&label(action)?)
                .ok_or("no such window")?;
            let num = |k: &str| action.get(k).and_then(Value::as_f64);
            if let (Some(x), Some(y)) = (num("x"), num("y")) {
                window
                    .set_position(tauri::LogicalPosition::new(x, y))
                    .map_err(|e| e.to_string())?;
            }
            if let (Some(w), Some(h)) = (num("w"), num("h")) {
                window
                    .set_size(tauri::LogicalSize::new(w, h))
                    .map_err(|e| e.to_string())?;
            }
            Ok(json!({ "ok": true }))
        }
        "eval" => eval(
            app,
            &label(action)?,
            action.get("js").and_then(Value::as_str).unwrap_or("null"),
        ),
        "key" => {
            let key = action
                .get("key")
                .and_then(Value::as_str)
                .ok_or("missing key")?;
            let mods: Vec<String> = action
                .get("mods")
                .and_then(Value::as_array)
                .map(|m| {
                    m.iter()
                        .filter_map(|v| v.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default();
            let with_up = action.get("up").and_then(Value::as_bool).unwrap_or(true);
            native::post_key(app, key, &mods, with_up)?;
            Ok(json!({ "ok": true }))
        }
        "type" => {
            let text = action
                .get("text")
                .and_then(Value::as_str)
                .ok_or("missing text")?;
            native::type_text(app, text)?;
            Ok(json!({ "ok": true }))
        }
        "drag" | "click" | "dblclick" => {
            let label = label(action)?;
            let point = |key: &str| -> Result<(f64, f64), String> {
                let p = action
                    .get(key)
                    .and_then(Value::as_array)
                    .ok_or(format!("missing {key}"))?;
                Ok((
                    p.first().and_then(Value::as_f64).unwrap_or(0.0),
                    p.get(1).and_then(Value::as_f64).unwrap_or(0.0),
                ))
            };
            app.get_webview_window(&label).ok_or("no such window")?;
            match op {
                "drag" => native::post_drag(app, &label, point("from")?, point("to")?),
                "click" => native::post_click(app, &label, point("at")?, 1),
                _ => native::post_click(app, &label, point("at")?, 2),
            }?;
            Ok(json!({ "ok": true }))
        }
        "menu" => {
            let id = action
                .get("id")
                .and_then(Value::as_str)
                .ok_or("missing id")?;
            menu::handle(app, id);
            Ok(json!({ "ok": true }))
        }
        "pasteboard" => {
            let field = |k: &str| action.get(k).and_then(Value::as_str).map(str::to_string);
            let content = match (field("file"), field("image"), field("text")) {
                (Some(path), _, _) => Some(native::Clip::File(path)),
                (_, Some(path), _) => Some(native::Clip::Image(path)),
                (_, _, Some(text)) => Some(native::Clip::Text(text)),
                _ => None,
            };
            native::pasteboard(app, content)
        }
        "toggle_launcher" => {
            windows::toggle_launcher(app);
            Ok(json!({ "ok": true }))
        }
        "shortcut" => {
            let hotkey = app.state::<AppState>().config.get().hotkey();
            Ok(json!({ "hotkey": hotkey, "registered": shortcut::is_registered(app, &hotkey) }))
        }
        "state" => {
            let state = app.state::<AppState>();
            let config = state.config.get();
            let signed_in = config
                .server_url
                .as_deref()
                .is_some_and(|s| state.token(s).is_some());
            Ok(json!({
                "server": config.server_url,
                "hotkey": config.hotkey(),
                "signedIn": signed_in,
                "version": app.package_info().version.to_string(),
                "exe": std::env::current_exe().map(|p| p.display().to_string()).unwrap_or_default(),
            }))
        }
        _ => Err(format!("unknown op {op}")),
    }
}

fn window_list(app: &AppHandle) -> Value {
    let mut out = Vec::new();
    for (label, w) in app.webview_windows() {
        let scale = w.scale_factor().unwrap_or(1.0);
        let pos = w.outer_position().map(|p| p.to_logical::<f64>(scale)).ok();
        let size = w.outer_size().map(|s| s.to_logical::<f64>(scale)).ok();
        out.push(json!({
            "label": label,
            "visible": w.is_visible().unwrap_or(false),
            "focused": w.is_focused().unwrap_or(false),
            "minimized": w.is_minimized().unwrap_or(false),
            "maximized": w.is_maximized().unwrap_or(false),
            "fullscreen": w.is_fullscreen().unwrap_or(false),
            "x": pos.map(|p| p.x), "y": pos.map(|p| p.y),
            "w": size.map(|s| s.width), "h": size.map(|s| s.height),
            "scale": scale,
            "url": w.url().map(|u| u.to_string()).unwrap_or_default(),
        }));
    }
    json!(out)
}

fn eval(app: &AppHandle, label: &str, js: &str) -> Result<Value, String> {
    let window = app.get_webview_window(label).ok_or("no such window")?;
    let (tx, rx) = mpsc::channel::<String>();
    let wrapped = format!("(() => {{ try {{ return JSON.stringify((() => {{ {js} }})()); }} catch (e) {{ return JSON.stringify({{ error: String(e) }}); }} }})()");
    window
        .eval_with_callback(wrapped, move |result| {
            let _ = tx.send(result);
        })
        .map_err(|e| e.to_string())?;
    let raw = rx
        .recv_timeout(Duration::from_secs(10))
        .map_err(|_| "eval timed out")?;
    // The callback gets the JSON encoding of the returned string.
    let inner: String = serde_json::from_str(&raw).unwrap_or(raw);
    Ok(serde_json::from_str(&inner).unwrap_or(Value::String(inner)))
}

#[cfg(target_os = "macos")]
mod native {
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;

    use objc2::msg_send;
    use objc2::rc::autoreleasepool;
    use objc2::runtime::{AnyClass, AnyObject, Bool};
    use objc2_foundation::{NSPoint, NSString};
    use tauri::{AppHandle, Manager};

    const KEY_DOWN: usize = 10;
    const KEY_UP: usize = 11;
    const MOUSE_DOWN: usize = 1;
    const MOUSE_UP: usize = 2;
    const MOUSE_DRAGGED: usize = 6;

    fn key_code(key: &str) -> Option<u16> {
        let code = match key.to_lowercase().as_str() {
            "a" => 0,
            "s" => 1,
            "d" => 2,
            "f" => 3,
            "h" => 4,
            "g" => 5,
            "z" => 6,
            "x" => 7,
            "c" => 8,
            "v" => 9,
            "b" => 11,
            "q" => 12,
            "w" => 13,
            "e" => 14,
            "r" => 15,
            "y" => 16,
            "t" => 17,
            "1" => 18,
            "2" => 19,
            "3" => 20,
            "4" => 21,
            "6" => 22,
            "5" => 23,
            "=" => 24,
            "9" => 25,
            "7" => 26,
            "-" => 27,
            "8" => 28,
            "0" => 29,
            "]" => 30,
            "o" => 31,
            "u" => 32,
            "[" => 33,
            "i" => 34,
            "p" => 35,
            "return" | "enter" => 36,
            "l" => 37,
            "j" => 38,
            "'" => 39,
            "k" => 40,
            ";" => 41,
            "\\" => 42,
            "," => 43,
            "/" => 44,
            "`" => 50,
            "n" => 45,
            "m" => 46,
            "." => 47,
            "tab" => 48,
            " " | "space" => 49,
            "backspace" => 51,
            "escape" | "esc" => 53,
            "left" => 123,
            "right" => 124,
            "down" => 125,
            "up" => 126,
            // Shifted symbols use their base key; post_key adds Shift.
            "!" => 18,
            "@" => 19,
            "#" => 20,
            "$" => 21,
            "^" => 22,
            "%" => 23,
            "+" => 24,
            "(" => 25,
            "&" => 26,
            "_" => 27,
            "*" => 28,
            ")" => 29,
            "}" => 30,
            "{" => 33,
            "\"" => 39,
            ":" => 41,
            "|" => 42,
            "<" => 43,
            "?" => 44,
            ">" => 47,
            "~" => 50,
            _ => return None,
        };
        Some(code)
    }

    /// The character Shift produces on a US layout.
    fn shifted(c: char) -> char {
        const PAIRS: &[(char, char)] = &[
            ('1', '!'),
            ('2', '@'),
            ('3', '#'),
            ('4', '$'),
            ('5', '%'),
            ('6', '^'),
            ('7', '&'),
            ('8', '*'),
            ('9', '('),
            ('0', ')'),
            ('-', '_'),
            ('=', '+'),
            ('[', '{'),
            (']', '}'),
            ('\\', '|'),
            (';', ':'),
            ('\'', '"'),
            (',', '<'),
            ('.', '>'),
            ('/', '?'),
            ('`', '~'),
        ];
        PAIRS
            .iter()
            .find(|(base, _)| *base == c)
            .map(|(_, up)| *up)
            .unwrap_or_else(|| c.to_ascii_uppercase())
    }

    fn characters(key: &str) -> String {
        match key.to_lowercase().as_str() {
            "return" | "enter" => "\r".into(),
            "tab" => "\t".into(),
            "escape" | "esc" => "\u{1b}".into(),
            "space" => " ".into(),
            "backspace" => "\u{7f}".into(),
            // AppKit's function-key characters (NSUpArrowFunctionKey and so on).
            "up" => "\u{f700}".into(),
            "down" => "\u{f701}".into(),
            "left" => "\u{f702}".into(),
            "right" => "\u{f703}".into(),
            _ => key.to_string(),
        }
    }

    fn flags(mods: &[String]) -> usize {
        mods.iter().fold(0, |acc, m| {
            acc | match m.as_str() {
                "shift" => 1 << 17,
                "ctrl" | "control" => 1 << 18,
                "alt" | "option" => 1 << 19,
                "cmd" | "command" => 1 << 20,
                _ => 0,
            }
        })
    }

    unsafe fn ns_app() -> *mut AnyObject {
        let class = AnyClass::get(c"NSApplication").expect("NSApplication");
        msg_send![class, sharedApplication]
    }

    unsafe fn post(event: *mut AnyObject) {
        let app = ns_app();
        let _: () = msg_send![app, postEvent: event, atStart: Bool::NO];
    }

    /// Runs `f` on the main thread, where AppKit windows and views may be read,
    /// inside an autorelease pool for the event objects it creates, and waits
    /// for the result. Delays between events stay on the QA thread.
    fn on_main<T: Send + 'static>(
        app: &AppHandle,
        f: impl FnOnce() -> T + Send + 'static,
    ) -> Result<T, String> {
        use std::sync::atomic::{AtomicU8, Ordering};
        use std::sync::Arc;
        const QUEUED: u8 = 0;
        const STARTED: u8 = 1;
        const CANCELLED: u8 = 2;
        let stage = Arc::new(AtomicU8::new(QUEUED));
        let main_stage = stage.clone();
        let (tx, rx) = mpsc::channel();
        app.run_on_main_thread(move || {
            // An action that timed out before it started must not run later.
            if main_stage
                .compare_exchange(QUEUED, STARTED, Ordering::SeqCst, Ordering::SeqCst)
                .is_ok()
            {
                let _ = tx.send(autoreleasepool(|_| f()));
            }
        })
        .map_err(|e| e.to_string())?;
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(value) => Ok(value),
            Err(_) => {
                if stage
                    .compare_exchange(QUEUED, CANCELLED, Ordering::SeqCst, Ordering::SeqCst)
                    .is_ok()
                {
                    return Err("the main thread did not answer".to_string());
                }
                // It started just in time: wait for it to finish.
                rx.recv().map_err(|e| e.to_string())
            }
        }
    }

    pub fn post_key(
        app: &AppHandle,
        key: &str,
        mods: &[String],
        with_up: bool,
    ) -> Result<(), String> {
        let code = key_code(key).ok_or_else(|| format!("unsupported key {key}"))?;
        // Shift in `mods` changes the text like a real key press ("1" -> "!").
        let chars = if mods.iter().any(|m| m == "shift") {
            characters(key).chars().map(shifted).collect()
        } else {
            characters(key)
        };
        let shifted = key.chars().count() == 1
            && key
                .chars()
                .all(|c| c.is_ascii_uppercase() || "!@#$%^&*()_+{}|:\"<>?~".contains(c));
        let flags = flags(mods) | if shifted { 1 << 17 } else { 0 };
        post_key_events(app, code, chars, flags, with_up)
    }

    /// Types text: characters with a key are pressed; newlines and tabs press
    /// Return and Tab; other characters (accents, emoji) are sent as text on
    /// a key event without a physical key.
    pub fn type_text(app: &AppHandle, text: &str) -> Result<(), String> {
        for ch in text.chars() {
            let key = match ch {
                '\n' | '\r' => "return".to_string(),
                '\t' => "tab".to_string(),
                c => c.to_string(),
            };
            if key_code(&key).is_some() {
                post_key(app, &key, &[], true)?;
            } else {
                // keyCode 0 only carries the characters; nothing is pressed.
                post_key_events(app, 0, key, 0, true)?;
            }
        }
        Ok(())
    }

    fn post_key_events(
        app: &AppHandle,
        code: u16,
        chars: String,
        flags: usize,
        with_up: bool,
    ) -> Result<(), String> {
        let kinds: &[usize] = if with_up {
            &[KEY_DOWN, KEY_UP]
        } else {
            &[KEY_DOWN]
        };
        for &kind in kinds {
            let chars = chars.clone();
            // SAFETY: runs on the main thread; every object is created and
            // posted inside the closure.
            let posted = on_main(app, move || unsafe {
                let app = ns_app();
                let key_window: *mut AnyObject = msg_send![app, keyWindow];
                let number: isize = if key_window.is_null() {
                    0
                } else {
                    msg_send![key_window, windowNumber]
                };
                let class = AnyClass::get(c"NSEvent").expect("NSEvent");
                let text = NSString::from_str(&chars);
                let event: *mut AnyObject = msg_send![class,
                    keyEventWithType: kind,
                    location: NSPoint::new(0.0, 0.0),
                    modifierFlags: flags,
                    timestamp: 0.0f64,
                    windowNumber: number,
                    context: std::ptr::null_mut::<AnyObject>(),
                    characters: &*text,
                    charactersIgnoringModifiers: &*text,
                    isARepeat: Bool::NO,
                    keyCode: code];
                if event.is_null() {
                    return false;
                }
                post(event);
                true
            })?;
            if !posted {
                return Err("could not create key event".into());
            }
            thread::sleep(Duration::from_millis(30));
        }
        Ok(())
    }

    /// Posts one mouse event; `point` is in window coordinates with a top-left
    /// origin (like the page). The window is read on the main thread.
    fn post_mouse(
        app: &AppHandle,
        label: &str,
        kind: usize,
        point: (f64, f64),
        clicks: isize,
    ) -> Result<(), String> {
        let handle = app.clone();
        let label = label.to_string();
        // The window is looked up for every event: an earlier event (the first
        // click of a double-click) can close it.
        // SAFETY: runs on the main thread with a window that is still open.
        on_main(app, move || unsafe {
            let window = handle
                .get_webview_window(&label)
                .ok_or_else(|| "the window closed".to_string())?
                .ns_window()
                .map_err(|e| e.to_string())?
                .cast::<AnyObject>();
            let content: *mut AnyObject = msg_send![window, contentView];
            let bounds: objc2_foundation::NSRect = msg_send![content, bounds];
            let number: isize = msg_send![window, windowNumber];
            let class = AnyClass::get(c"NSEvent").expect("NSEvent");
            let event: *mut AnyObject = msg_send![class,
                mouseEventWithType: kind,
                location: NSPoint::new(point.0, bounds.size.height - point.1),
                modifierFlags: 0usize,
                timestamp: 0.0f64,
                windowNumber: number,
                context: std::ptr::null_mut::<AnyObject>(),
                eventNumber: 0isize,
                clickCount: clicks,
                pressure: 1.0f32];
            if !event.is_null() {
                post(event);
            }
            Ok(())
        })?
    }

    pub fn post_click(
        app: &AppHandle,
        label: &str,
        at: (f64, f64),
        clicks: isize,
    ) -> Result<(), String> {
        for n in 1..=clicks {
            post_mouse(app, label, MOUSE_DOWN, at, n)?;
            thread::sleep(Duration::from_millis(40));
            post_mouse(app, label, MOUSE_UP, at, n)?;
            thread::sleep(Duration::from_millis(60));
        }
        Ok(())
    }

    pub enum Clip {
        /// A file reference, as Finder's Copy puts it.
        File(String),
        /// Image data read from a file, as a screenshot to the clipboard puts it.
        Image(String),
        Text(String),
    }

    /// Puts `content` on the general pasteboard (for paste tests), or reads
    /// its text without `content` (for copy tests).
    pub fn pasteboard(app: &AppHandle, content: Option<Clip>) -> Result<serde_json::Value, String> {
        // SAFETY: main thread; every object is created and used in the closure.
        on_main(app, move || unsafe {
            let class = AnyClass::get(c"NSPasteboard").expect("NSPasteboard");
            let board: *mut AnyObject = msg_send![class, generalPasteboard];
            let Some(content) = content else {
                let kind = NSString::from_str("public.utf8-plain-text");
                let text: *mut AnyObject = msg_send![board, stringForType: &*kind];
                if text.is_null() {
                    return Ok(serde_json::json!({ "text": null }));
                }
                let utf8: *const std::ffi::c_char = msg_send![text, UTF8String];
                let text = std::ffi::CStr::from_ptr(utf8)
                    .to_string_lossy()
                    .into_owned();
                return Ok(serde_json::json!({ "text": text }));
            };
            let _: isize = msg_send![board, clearContents];
            let object: *mut AnyObject = match &content {
                Clip::File(path) => {
                    let url = AnyClass::get(c"NSURL").expect("NSURL");
                    let path = NSString::from_str(path);
                    msg_send![url, fileURLWithPath: &*path]
                }
                Clip::Image(path) => {
                    let image = AnyClass::get(c"NSImage").expect("NSImage");
                    let path = NSString::from_str(path);
                    let allocated: *mut AnyObject = msg_send![image, alloc];
                    let image: *mut AnyObject =
                        msg_send![allocated, initWithContentsOfFile: &*path];
                    if !image.is_null() {
                        let _: *mut AnyObject = msg_send![image, autorelease];
                    }
                    image
                }
                Clip::Text(text) => {
                    let string = AnyClass::get(c"NSString").expect("NSString");
                    let text = NSString::from_str(text);
                    msg_send![string, stringWithString: &*text]
                }
            };
            if object.is_null() {
                return Err("could not read that file".to_string());
            }
            let array = AnyClass::get(c"NSArray").expect("NSArray");
            let objects: *mut AnyObject = msg_send![array, arrayWithObject: object];
            let written: Bool = msg_send![board, writeObjects: objects];
            Ok(serde_json::json!({ "ok": written.as_bool() }))
        })?
    }

    pub fn post_drag(
        app: &AppHandle,
        label: &str,
        from: (f64, f64),
        to: (f64, f64),
    ) -> Result<(), String> {
        post_mouse(app, label, MOUSE_DOWN, from, 1)?;
        // Give the page time to call Tauri's start_dragging.
        thread::sleep(Duration::from_millis(250));
        for step in 1..=12 {
            let t = f64::from(step) / 12.0;
            let p = (from.0 + (to.0 - from.0) * t, from.1 + (to.1 - from.1) * t);
            post_mouse(app, label, MOUSE_DRAGGED, p, 1)?;
            thread::sleep(Duration::from_millis(25));
        }
        post_mouse(app, label, MOUSE_UP, to, 1)
    }
}

#[cfg(not(target_os = "macos"))]
mod native {
    use tauri::AppHandle;

    pub fn post_key(_: &AppHandle, _: &str, _: &[String], _: bool) -> Result<(), String> {
        Err("QA input is macOS only".into())
    }
    pub fn type_text(_: &AppHandle, _: &str) -> Result<(), String> {
        Err("QA input is macOS only".into())
    }

    pub fn post_click(_: &AppHandle, _: &str, _: (f64, f64), _: isize) -> Result<(), String> {
        Err("QA input is macOS only".into())
    }
    pub fn post_drag(_: &AppHandle, _: &str, _: (f64, f64), _: (f64, f64)) -> Result<(), String> {
        Err("QA input is macOS only".into())
    }

    #[allow(dead_code)]
    pub enum Clip {
        File(String),
        Image(String),
        Text(String),
    }
    pub fn pasteboard(_: &AppHandle, _: Option<Clip>) -> Result<serde_json::Value, String> {
        Err("QA input is macOS only".into())
    }
}
