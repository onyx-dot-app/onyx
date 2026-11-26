//! Local (bundled) windows: onboarding, login, preferences, offline and the launcher panel.

use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use url::Url;

use crate::main_window;
use crate::reachability::Unreachable;
use crate::state::AppState;

pub const ONBOARDING: &str = "onboarding";
pub const LOGIN: &str = "login";
pub const PREFERENCES: &str = "preferences";
pub const LAUNCHER: &str = "launcher";
pub const OFFLINE: &str = "offline";

/// Local windows may only show bundled pages; anything else opens in the browser.
pub(crate) fn local_navigation_allowed(app: &AppHandle, url: &Url) -> bool {
    let bundled = matches!(url.scheme(), "tauri" | "about")
        || (url.scheme() == "http" && url.host_str() == Some("tauri.localhost"));
    let dev_server = tauri::is_dev()
        && app
            .config()
            .build
            .dev_url
            .as_ref()
            .is_some_and(|dev| dev.origin() == url.origin());
    if bundled || dev_server {
        return true;
    }
    if matches!(url.scheme(), "http" | "https") {
        crate::main_window::open_external(app, url.as_str());
    }
    false
}

/// Local pages never open windows; links go to the browser.
pub(crate) fn local_new_window(
    app: &AppHandle,
) -> impl Fn(Url, tauri::webview::NewWindowFeatures) -> NewWindowResponse<tauri::Wry> + Send + 'static
{
    let app = app.clone();
    move |url, _features| {
        if matches!(url.scheme(), "http" | "https") {
            main_window::open_external(&app, url.as_str());
        }
        NewWindowResponse::Deny
    }
}

fn local_window(
    app: &AppHandle,
    label: &str,
    page: &str,
    title: &str,
    size: (f64, f64),
) -> Result<WebviewWindow, String> {
    if let Some(window) = app.get_webview_window(label) {
        // A window that waits to close is wanted again: it stays (its
        // pending replies still reach it), with a fresh page, because the
        // page shows the end of the command that hid it.
        if with_retire(label, Retire::reopen) {
            let _ = window.eval("location.reload()");
        }
        bring_forward(app, &window);
        return Ok(window);
    }
    let nav_app = app.clone();
    let builder = WebviewWindowBuilder::new(app, label, WebviewUrl::App(page.into()))
        .title(title)
        .inner_size(size.0, size.1)
        .resizable(false)
        .center()
        .focused(true)
        // The first click also acts on the control, not only on the window.
        .accept_first_mouse(true)
        .on_navigation(move |url| local_navigation_allowed(&nav_app, url))
        .on_new_window(local_new_window(app));
    #[cfg(target_os = "macos")]
    let builder = builder
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true);
    // Windows keeps the Maximize button of a window that cannot be resized.
    #[cfg(not(target_os = "macos"))]
    let builder = builder.maximizable(false);
    let window = builder.build().map_err(|e| e.to_string())?;
    activate_app(app);
    Ok(window)
}

/// Shows `window` in front of every app. Showing a window does not activate
/// the app: from the tray or the launcher, the window would open behind the
/// app in front.
pub fn bring_forward(app: &AppHandle, window: &WebviewWindow) {
    // Queued on the main thread ahead of the focus change below.
    crate::launcher::keep_app_shown(app);
    let _ = window.show();
    let _ = window.unminimize();
    activate_app(app);
    let _ = window.set_focus();
}

#[cfg(target_os = "macos")]
fn activate_app(app: &AppHandle) {
    let _ = app.run_on_main_thread(|| {
        if let Some(mtm) = objc2::MainThreadMarker::new() {
            let ns_app = objc2_app_kit::NSApplication::sharedApplication(mtm);
            #[allow(deprecated)] // `activate` needs macOS 14.
            ns_app.activateIgnoringOtherApps(true);
        }
    });
}

#[cfg(not(target_os = "macos"))]
fn activate_app(_app: &AppHandle) {}

/// The size a local window opens at, in logical pixels.
fn initial_size(label: &str) -> Option<(f64, f64)> {
    match label {
        ONBOARDING => Some((520.0, 400.0)),
        LOGIN => Some((460.0, 520.0)),
        PREFERENCES => Some((560.0, 600.0)),
        OFFLINE => Some((460.0, 300.0)),
        _ => None,
    }
}

fn open_local(
    app: &AppHandle,
    label: &str,
    page: &str,
    title: &str,
) -> Result<WebviewWindow, String> {
    let size = initial_size(label).ok_or("not a local window")?;
    let window = local_window(app, label, page, title, size);
    if let Err(e) = &window {
        let server_set = app
            .try_state::<AppState>()
            .is_some_and(|state| state.server().is_ok());
        if let Some(failed) = failed_window_for(label, server_set) {
            window_failed(app, failed, e);
        }
    }
    window
}

/// The window that did not open.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum FailedWindow {
    Onboarding,
    /// Onboarding opened by Change server, with a server already set.
    ChangeServer,
    Login,
    Preferences,
    /// The launcher the user asked for (shortcut, menu, tray).
    Launcher,
    /// The hidden launcher created at startup: the user did not ask for it.
    LauncherPreload,
}

/// The window a failed local window stands for. Onboarding with a server
/// set is Change server: routing would open chat or sign-in, not it. Sign-in
/// opens only when the user is signed out, where routing opens it again.
#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn failed_window_for(label: &str, server_set: bool) -> Option<FailedWindow> {
    match label {
        ONBOARDING if server_set => Some(FailedWindow::ChangeServer),
        ONBOARDING => Some(FailedWindow::Onboarding),
        LOGIN => Some(FailedWindow::Login),
        PREFERENCES => Some(FailedWindow::Preferences),
        // The offline window has its own fallback dialog (`show_offline`).
        _ => None,
    }
}

/// What Try Again does: open the same window again.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Retry {
    /// Onboarding and sign-in: routing is what opens them.
    Route,
    /// The Change server command again, with its checks and window cleanup.
    ChangeServer,
    Preferences,
    Launcher,
}

/// What the user sees when a local window or the launcher cannot open.
#[derive(Debug, PartialEq, Eq)]
pub(crate) enum WindowFailure {
    /// "Close the older version of Onyx" (see `webview_failed`).
    OlderVersion,
    /// The "Could not open Onyx" dialog with Try Again and Quit.
    CouldNotOpen(Retry),
    /// Logged only: a startup window the user did not ask for, or such a
    /// dialog is open already.
    LogOnly,
}

#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn window_failure(
    window: FailedWindow,
    webview_error: bool,
    earlier_app_evidence: bool,
    dialog_open: bool,
) -> WindowFailure {
    // The hidden launcher at startup: the user did not ask for it, and the
    // other windows may open fine, so no dialog (not even the one that quits).
    if window == FailedWindow::LauncherPreload {
        return WindowFailure::LogOnly;
    }
    if shows_close_older(webview_error, earlier_app_evidence) {
        return WindowFailure::OlderVersion;
    }
    let retry = match window {
        FailedWindow::Onboarding | FailedWindow::Login => Retry::Route,
        FailedWindow::ChangeServer => Retry::ChangeServer,
        FailedWindow::Preferences => Retry::Preferences,
        FailedWindow::Launcher => Retry::Launcher,
        FailedWindow::LauncherPreload => return WindowFailure::LogOnly,
    };
    if dialog_open {
        WindowFailure::LogOnly
    } else {
        WindowFailure::CouldNotOpen(retry)
    }
}

/// A local window or the launcher did not open. On Windows (where a web view
/// can fail to start) the user is told, one dialog at a time; macOS and
/// Linux only log it, as before.
pub(crate) fn window_failed(app: &AppHandle, window: FailedWindow, error: &str) {
    log::warn!("could not open a window: {error}");
    #[cfg(windows)]
    {
        use std::sync::atomic::{AtomicBool, Ordering};
        static DIALOG_OPEN: AtomicBool = AtomicBool::new(false);
        let evidence = crate::earlier_install::evidence(app);
        let response = window_failure(
            window,
            is_webview_start_error(error),
            evidence,
            DIALOG_OPEN.load(Ordering::SeqCst),
        );
        match response {
            WindowFailure::OlderVersion => {
                let _ = webview_failed(app, error);
            }
            WindowFailure::LogOnly => {}
            WindowFailure::CouldNotOpen(retry) => {
                if DIALOG_OPEN.swap(true, Ordering::SeqCst) {
                    return;
                }
                let dialog = rfd::MessageDialog::new()
                    .set_title("Could not open Onyx")
                    .set_description(crate::dialog::text(error))
                    .set_buttons(rfd::MessageButtons::OkCancelCustom(
                        "Try Again".into(),
                        "Quit".into(),
                    ));
                crate::dialog::show(app, dialog, move |app, choice| {
                    DIALOG_OPEN.store(false, Ordering::SeqCst);
                    if choice != rfd::MessageDialogResult::Custom("Try Again".into()) {
                        app.exit(0);
                        return;
                    }
                    match retry {
                        Retry::Route => route(app),
                        Retry::ChangeServer => {
                            // A policy read can lock the server while the
                            // dialog is open: say so. A window error has
                            // its own dialog from `open_local`.
                            if let Some(reason) = crate::commands::server_lock_now(app) {
                                notify(app, "Server locked", reason);
                            } else if let Err(e) = crate::commands::open_change_server(app, None) {
                                log::warn!("could not open Change server: {e}");
                            }
                        }
                        Retry::Preferences => {
                            let _ = open_preferences(app);
                        }
                        Retry::Launcher => crate::launcher::show(app),
                    }
                });
            }
        }
    }
    #[cfg(not(windows))]
    let _ = (app, window);
}

/// Whether a window error is the web view failing to start.
#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn is_webview_start_error(error: &str) -> bool {
    let error = error.to_ascii_lowercase();
    error.contains("failed to create webview") || error.contains("webview2")
}

/// On Windows, a web view does not start while the earlier desktop app still
/// runs as another user token: both use the same WebView2 data folder. Says
/// so once per run, and only when the earlier app is (or was just) on this
/// computer; the error is logged by the caller. Returns whether it said so.
pub(crate) fn webview_failed(app: &AppHandle, error: &str) -> bool {
    #[cfg(windows)]
    {
        use std::sync::atomic::{AtomicBool, Ordering};
        static SHOWN: AtomicBool = AtomicBool::new(false);
        let evidence = crate::earlier_install::evidence(app);
        if !shows_close_older(is_webview_start_error(error), evidence) {
            return false;
        }
        if !SHOWN.swap(true, Ordering::SeqCst) {
            log::warn!("a window could not start its web view: {error}");
            // The app has no window it can show: OK quits, so the next
            // launch is a new process, not this hidden one.
            let dialog = rfd::MessageDialog::new()
                .set_title("Onyx could not open")
                .set_description(crate::dialog::text(
                    "Close the older version of Onyx, then open Onyx again.",
                ))
                .set_buttons(rfd::MessageButtons::Ok);
            crate::dialog::show(app, dialog, |app, _| app.exit(0));
        }
        true
    }
    #[cfg(not(windows))]
    {
        let _ = (app, error);
        false
    }
}

/// Whether a window error is answered with "Close the older version of
/// Onyx": a web view that did not start while the earlier app is around.
/// Without that evidence, the usual error dialog and its retry stay.
#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn shows_close_older(webview_error: bool, earlier_app_evidence: bool) -> bool {
    webview_error && earlier_app_evidence
}

pub fn open_onboarding(app: &AppHandle) -> Result<WebviewWindow, String> {
    open_local(app, ONBOARDING, "onboarding.html", "Welcome to Onyx")
}

pub fn open_login(app: &AppHandle) -> Result<WebviewWindow, String> {
    open_local(app, LOGIN, "login.html", "Sign in to Onyx")
}

pub fn open_preferences(app: &AppHandle) -> Result<WebviewWindow, String> {
    open_local(app, PREFERENCES, "preferences.html", "Preferences")
}

pub fn open_offline(app: &AppHandle) -> Result<WebviewWindow, String> {
    open_local(app, OFFLINE, "offline.html", "Onyx")
}

/// Logical pixels kept free above and below a local window: the title bar
/// and panels.
const SCREEN_MARGIN: f64 = 80.0;
/// The title bar height a local window is placed with, in logical pixels.
const TITLE_BAR: f64 = 40.0;

/// A local window's height and, if it must move to stay on screen, its new
/// outer position.
#[derive(Debug, PartialEq)]
pub(crate) struct Fit {
    pub height: f64,
    pub position: Option<(i32, i32)>,
}

/// Fits a window `width` logical pixels wide to `content` logical pixels of
/// height inside `work_area` (physical x, y, width, height). A window that
/// would leave the work area is centered in it.
pub(crate) fn fit_in_work_area(
    work_area: (i32, i32, u32, u32),
    scale: f64,
    position: (i32, i32),
    width: f64,
    content: f64,
) -> Fit {
    let (area_x, area_y, area_w, area_h) = work_area;
    let (area_w, area_h) = (f64::from(area_w), f64::from(area_h));
    let max_height = (area_h / scale - SCREEN_MARGIN).max(TITLE_BAR);
    let height = content.clamp(1.0, max_height);
    let outer_w = (width * scale).round();
    let outer_h = ((height + TITLE_BAR) * scale).round();
    let place = |start: i32, extent: f64, area_start: i32, area_extent: f64| -> i32 {
        let end = f64::from(start) + extent;
        if start >= area_start && end <= f64::from(area_start) + area_extent {
            start
        } else {
            area_start + ((area_extent - extent) / 2.0).max(0.0) as i32
        }
    };
    let x = place(position.0, outer_w, area_x, area_w);
    let y = place(position.1, outer_h, area_y, area_h);
    Fit {
        height,
        position: ((x, y) != position).then_some((x, y)),
    }
}

/// Logical pixels the window frame adds left and right of the content.
#[cfg(any(windows, test))]
const FRAME_WIDTH: f64 = 16.0;

/// The inner size, at most `wanted` and at least `min` (logical pixels), of
/// a window with a title bar and menu bar that fits `work_area` (physical
/// width, height) at `scale`.
#[cfg(any(windows, test))]
pub(crate) fn fit_size(
    work_area: (u32, u32),
    scale: f64,
    wanted: (f64, f64),
    min: (f64, f64),
) -> (f64, f64) {
    let width = f64::from(work_area.0) / scale - FRAME_WIDTH;
    let height = f64::from(work_area.1) / scale - SCREEN_MARGIN;
    (
        wanted.0.min(width).max(min.0).floor(),
        wanted.1.min(height).max(min.1).floor(),
    )
}

/// Sizes a local window to its content: `content_height` logical pixels
/// high, as wide as it opened, and inside its monitor's work area.
pub fn fit_to_content(window: &WebviewWindow, content_height: f64) -> Result<(), String> {
    let (width, _) = initial_size(window.label()).ok_or("not a local window")?;
    let monitor = match window.current_monitor().map_err(|e| e.to_string())? {
        Some(monitor) => Some(monitor),
        None => window.primary_monitor().map_err(|e| e.to_string())?,
    };
    let Some(monitor) = monitor else {
        return window
            .set_size(tauri::LogicalSize::new(width, content_height))
            .map_err(|e| e.to_string());
    };
    let area = monitor.work_area();
    let position = window.outer_position().map_err(|e| e.to_string())?;
    let fit = fit_in_work_area(
        (
            area.position.x,
            area.position.y,
            area.size.width,
            area.size.height,
        ),
        monitor.scale_factor(),
        (position.x, position.y),
        width,
        content_height,
    );
    window
        .set_size(tauri::LogicalSize::new(width, fit.height))
        .map_err(|e| e.to_string())?;
    if let Some((x, y)) = fit.position {
        window
            .set_position(tauri::PhysicalPosition::new(x, y))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// The pending command calls of one local window, and whether a command
/// hid it to be destroyed once they all have their reply.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Retire {
    pending: u32,
    retiring: bool,
}

impl Retire {
    /// A call that may hide its caller started.
    pub(crate) fn begin(&mut self) {
        self.pending += 1;
    }

    /// The window should go. True when it can be destroyed now: no reply is
    /// on its way to it.
    pub(crate) fn close(&mut self) -> bool {
        self.retiring = true;
        self.pending == 0
    }

    /// A reply arrived (`release_window`). True when the window can be
    /// destroyed now.
    pub(crate) fn release(&mut self) -> bool {
        self.pending = self.pending.saturating_sub(1);
        self.retiring && self.pending == 0
    }

    /// The window is wanted again while it waits to close: it stays, and its
    /// pending replies still reach it. True if it was waiting to close.
    pub(crate) fn reopen(&mut self) -> bool {
        std::mem::replace(&mut self.retiring, false)
    }

    fn idle(self) -> bool {
        self.pending == 0 && !self.retiring
    }
}

static RETIRE: std::sync::Mutex<std::collections::BTreeMap<String, Retire>> =
    std::sync::Mutex::new(std::collections::BTreeMap::new());

/// Runs `f` on the record of `label`, and drops a record with nothing left.
fn with_retire<T>(label: &str, f: impl FnOnce(&mut Retire) -> T) -> T {
    let mut all = RETIRE.lock().unwrap_or_else(|p| p.into_inner());
    let entry = all.entry(label.to_string()).or_default();
    let result = f(entry);
    if entry.idle() {
        all.remove(label);
    }
    result
}

fn is_retiring(label: &str) -> bool {
    RETIRE
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .get(label)
        .is_some_and(|r| r.retiring)
}

/// A command that may close the window it came from started. The page's
/// `release_window` after the reply ends it. The IPC reply goes to the web
/// view after the command returns, on another thread; destroying the web
/// view first can crash the app on macOS (the reply touches a freed
/// WKURLSchemeTask, tauri-apps/tauri#5519).
pub fn begin_call(label: &str) {
    with_retire(label, Retire::begin);
}

/// Whether a command must not destroy `label` now: the command was called
/// from that window.
pub(crate) fn defers_close(label: &str, caller: Option<&str>) -> bool {
    caller == Some(label)
}

/// Closes `label` from a command called by the window `caller`. A window
/// with pending calls is only hidden; it is destroyed when the last reply
/// has arrived (`release`).
pub fn close_from(app: &AppHandle, label: &str, caller: Option<&str>) {
    if defers_close(label, caller) {
        // The caller's own call is pending, also if it did not register.
        with_retire(label, |r| {
            if r.pending == 0 {
                r.begin();
            }
        });
    }
    close(app, label);
}

/// The page of `label` has a reply. When it was the last one and the
/// window waits to close, the destroy is queued from another thread, so it
/// runs on a later turn of the main loop, after this call's own reply.
pub fn release(app: &AppHandle, label: &str) {
    if !with_retire(label, Retire::release) {
        return;
    }
    let app = app.clone();
    let label = label.to_string();
    tauri::async_runtime::spawn(async move {
        let handle = app.clone();
        let _ = app.run_on_main_thread(move || {
            // Reopened, or a new call started meanwhile: keep it.
            let ready = RETIRE
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .get(&label)
                .is_some_and(|r| r.retiring && r.pending == 0);
            if ready {
                destroy(&handle, &label);
            }
        });
    });
}

/// Closes a local window: at once, or, while a reply is on its way to it,
/// hidden now and destroyed after the last reply.
pub fn close(app: &AppHandle, label: &str) {
    if with_retire(label, Retire::close) {
        destroy(app, label);
    } else if let Some(window) = app.get_webview_window(label) {
        let _ = window.hide();
    }
}

fn destroy(app: &AppHandle, label: &str) {
    RETIRE
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .remove(label);
    if let Some(window) = app.get_webview_window(label) {
        // Closes the WebView2 page first: a destroyed window can leave it
        // running.
        #[cfg(windows)]
        let _ = window.with_webview(|webview| {
            // SAFETY: runs on the UI thread with the live controller.
            let _ = unsafe { webview.controller().Close() };
        });
        let _ = window.destroy();
    }
}

pub fn hide_launcher(app: &AppHandle) {
    crate::launcher::hide(app);
}

/// Hides the launcher and drops what it shows, so the next account never sees
/// the previous one's answers or search results.
pub fn reset_launcher(app: &AppHandle) {
    crate::launcher::reset(app);
}

/// Bound to the global shortcut: shows the launcher over any app, or hides it.
pub fn toggle_launcher(app: &AppHandle) {
    if app.state::<AppState>().policy().disable_launcher {
        return;
    }
    crate::launcher::toggle(app, route);
}

/// Opens whichever window the current state needs: onboarding, login or the main window.
/// Onyx could not open although the session may be valid (the server could
/// not be reached, or its sign-in settings did not load): keep the session,
/// explain, and let the user try again or sign in.
fn open_failed(app: &AppHandle, title: &str, error: &str) {
    let dialog = rfd::MessageDialog::new()
        .set_title(title)
        .set_description(crate::dialog::text(error))
        .set_buttons(rfd::MessageButtons::OkCancelCustom(
            "Try Again".into(),
            "Sign In".into(),
        ));
    crate::dialog::show(app, dialog, |app, choice| {
        if choice == rfd::MessageDialogResult::Custom("Try Again".into()) {
            app.state::<AppState>().forget_read_failure();
            route(app);
        } else {
            let _ = open_login(app);
        }
    });
}

/// A message with an OK button, over the app's windows.
pub fn notify(app: &AppHandle, title: &str, text: &str) {
    let dialog = rfd::MessageDialog::new()
        .set_title(title)
        .set_description(crate::dialog::text(text))
        .set_buttons(rfd::MessageButtons::Ok);
    crate::dialog::show(app, dialog, |_, _| {});
}

/// How long opening Onyx waits for the session renewal.
const RENEWAL_WAIT: std::time::Duration = std::time::Duration::from_secs(5);

pub fn route(app: &AppHandle) {
    route_to(app, "/app");
}

/// Like `route`, but a signed-in session opens `path` on the server.
pub fn route_to(app: &AppHandle, path: &str) {
    let state = app.state::<AppState>();
    let epoch = state.epoch();
    let choice = crate::offline::next_choice(app);
    let Ok(server) = state.server() else {
        let _ = open_onboarding(app);
        return;
    };
    let Some(token) = state.token(&server) else {
        // A keyring that could not be read (locked, cancelled unlock) is
        // not signed out: say so, and let the user try again.
        match state.read_failure(&server) {
            Some(error) => open_failed(app, "Could not read your session", &error),
            None => show_sign_in(app),
        }
        return;
    };
    let app = app.clone();
    let path = path.to_string();
    tauri::async_runtime::spawn(async move {
        let state = app.state::<AppState>();
        match state.api.session_valid(&server, &token).await {
            Ok(true) => {
                // Renewed before the window opens: the web UI reads the
                // session's expiry when it loads, and a page that sees the
                // old expiry pass signs the session out on the server.
                let renewal = tokio::time::timeout(
                    RENEWAL_WAIT,
                    main_window::renew_session(&app, &server, &token),
                )
                .await;
                // `None` is also a renewal that lost to another one, which
                // stored a newer token: the session is still on.
                let renewed = renewal.is_ok();
                // A sign-out or server change during the wait wins.
                if state.epoch() != epoch || state.server().ok().as_deref() != Some(&server) {
                    return;
                }
                // The stored token, read now: another renewal may have
                // replaced it, or a rejection cleared it.
                let Some(token) = state.token(&server) else {
                    return;
                };
                if let Err(e) = main_window::open(&app, &server, &token, &path).await {
                    log::warn!("could not open main window: {e}");
                    if webview_failed(&app, &e) {
                        return;
                    }
                    match state.api.health(&server).await {
                        Err(reason) => show_offline(&app, &server, &path, choice, reason, epoch),
                        Ok(()) => open_failed(&app, "Could not open Onyx", &e),
                    }
                }
                // A slow renewal does not delay the window; it finishes
                // here, and the renewed token reaches the window.
                if !renewed {
                    main_window::renew_session(&app, &server, &token).await;
                }
            }
            Ok(false) => end_rejected_session(&app, &server, &token),
            // Unreachable is not signed out: the session is kept, and
            // Sign in is only for a rejected session or the user's choice.
            Err(reason) => show_offline(&app, &server, &path, choice, reason, epoch),
        }
    });
}

/// Ends a session the server no longer accepts and shows the sign-in window,
/// unless a sign-in that finished meanwhile replaced `token`.
pub fn end_rejected_session(app: &AppHandle, server: &str, token: &str) {
    let state = app.state::<AppState>();
    let cleared = state.clear_rejected_token(server, token);
    if matches!(cleared, Ok(false)) {
        return;
    }
    // The rejected account's answers and pages (a main window kept hidden
    // during an outage) must not reach the next one.
    reset_launcher(app);
    main_window::close(app, server);
    let _ = open_login(app);
    if let Err(e) = cleared {
        log::warn!("signed out, but the stored session token was not deleted: {e}");
        notify(app, "Signed out", crate::commands::NOT_CLEARED);
    }
}

/// The offline window, or the "Try Again / Sign In" dialog if it cannot open.
pub(crate) fn show_offline(
    app: &AppHandle,
    server: &str,
    path: &str,
    choice: u64,
    reason: Unreachable,
    epoch: u64,
) {
    if let Err(e) = crate::offline::show(app, path, choice, reason, epoch) {
        log::warn!("showing the dialog instead of the offline window: {e}");
        open_failed(app, "Could not open Onyx", &reason.message(server));
    }
}

/// Dock click, tray "Open Onyx" and second launches.
/// The windows that `show_primary` brings forward, first match wins. The main
/// window is hidden while the offline window shows. Off macOS, the web sign-in
/// window stands in for the login window, which it hides.
#[cfg(target_os = "macos")]
const PRIMARY: [&str; 4] = [OFFLINE, main_window::LABEL, ONBOARDING, LOGIN];
#[cfg(not(target_os = "macos"))]
const PRIMARY: [&str; 5] = [
    OFFLINE,
    main_window::LABEL,
    ONBOARDING,
    crate::sso::LABEL,
    LOGIN,
];

/// Brings the login window forward, or off macOS the web sign-in window that
/// hides it.
fn show_sign_in(app: &AppHandle) {
    #[cfg(not(target_os = "macos"))]
    if let Some(window) = app.get_webview_window(crate::sso::LABEL) {
        bring_forward(app, &window);
        return;
    }
    let _ = open_login(app);
}

pub fn show_primary(app: &AppHandle) {
    show_primary_except(app, "");
}

/// Like `show_primary`, but never brings `closing` forward: a window that is
/// being closed can still be found for a moment.
pub fn show_primary_except(app: &AppHandle, closing: &str) {
    // A window that waits to close is skipped; `route` reopens it if needed.
    for label in PRIMARY
        .into_iter()
        .filter(|label| *label != closing && !is_retiring(label))
    {
        if let Some(window) = app.get_webview_window(label) {
            bring_forward(app, &window);
            return;
        }
    }
    route(app);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_window_closes_only_after_its_last_reply() {
        use super::Retire;
        let mut r = Retire::default();
        // Sign out, then Change server, from the same window.
        r.begin();
        r.begin();
        assert!(!r.close(), "two replies are on their way");
        assert!(!r.release(), "one reply is still on its way");
        assert!(r.release(), "the last reply arrived");

        // No call pending: it closes at once.
        assert!(Retire::default().close());

        // Reopened while it waits: it stays, also after the reply.
        let mut r = Retire::default();
        r.begin();
        assert!(!r.close());
        assert!(r.reopen());
        assert!(!r.release());
        assert!(!Retire::default().reopen());
    }

    #[test]
    fn a_command_hides_its_own_window_and_closes_others() {
        assert!(super::defers_close(LOGIN, Some(LOGIN)));
        assert!(super::defers_close(PREFERENCES, Some(PREFERENCES)));
        assert!(!super::defers_close(LOGIN, Some(PREFERENCES)));
        assert!(!super::defers_close(LOGIN, None));
    }

    #[test]
    fn a_window_failure_retries_that_window() {
        use super::{window_failure, FailedWindow as W, Retry, WindowFailure as F};
        assert_eq!(
            window_failure(W::Preferences, true, true, false),
            F::OlderVersion
        );
        // A fresh install: the usual dialog, and Try Again opens the same window.
        assert_eq!(
            window_failure(W::Onboarding, true, false, false),
            F::CouldNotOpen(Retry::Route)
        );
        assert_eq!(
            window_failure(W::Login, false, false, false),
            F::CouldNotOpen(Retry::Route)
        );
        assert_eq!(
            window_failure(W::Preferences, false, false, false),
            F::CouldNotOpen(Retry::Preferences)
        );
        assert_eq!(
            window_failure(W::Launcher, true, false, false),
            F::CouldNotOpen(Retry::Launcher)
        );
        assert_eq!(
            window_failure(W::ChangeServer, true, false, false),
            F::CouldNotOpen(Retry::ChangeServer)
        );
        // Only while a dialog is open are other failures logged only.
        assert_eq!(window_failure(W::Onboarding, true, false, true), F::LogOnly);
        // The hidden launcher at startup is never a dialog, also with
        // evidence of the earlier app.
        assert_eq!(
            window_failure(W::LauncherPreload, true, true, false),
            F::LogOnly
        );
        assert_eq!(
            window_failure(W::LauncherPreload, true, false, false),
            F::LogOnly
        );
    }

    #[test]
    fn a_signed_in_users_onboarding_is_change_server() {
        use super::{
            failed_window_for, FailedWindow as W, LOGIN, OFFLINE, ONBOARDING, PREFERENCES,
        };
        assert_eq!(failed_window_for(ONBOARDING, true), Some(W::ChangeServer));
        assert_eq!(failed_window_for(ONBOARDING, false), Some(W::Onboarding));
        assert_eq!(failed_window_for(LOGIN, true), Some(W::Login));
        assert_eq!(failed_window_for(PREFERENCES, true), Some(W::Preferences));
        assert_eq!(failed_window_for(OFFLINE, true), None);
    }

    #[test]
    fn the_older_version_message_needs_evidence_of_it() {
        assert!(super::shows_close_older(true, true));
        assert!(!super::shows_close_older(true, false));
        assert!(!super::shows_close_older(false, true));
    }

    #[test]
    fn a_web_view_start_failure_is_recognized() {
        assert!(super::is_webview_start_error(
            "runtime error: failed to create webview: WebView2 error: WindowsError(HRESULT(0x80010108))"
        ));
        assert!(!super::is_webview_start_error("not a local window"));
    }

    #[test]
    fn a_large_window_shrinks_to_the_work_area() {
        // 1600x1200 at 150% with a 48px taskbar.
        assert_eq!(
            fit_size((1600, 1128), 1.5, (1280.0, 840.0), (800.0, 600.0)),
            (1050.0, 672.0)
        );
        // It fits: no change.
        assert_eq!(
            fit_size((1920, 1032), 1.0, (1280.0, 840.0), (800.0, 600.0)),
            (1280.0, 840.0)
        );
        // Never below the minimum size.
        assert_eq!(
            fit_size((1024, 728), 1.5, (1280.0, 840.0), (800.0, 600.0)),
            (800.0, 600.0)
        );
    }

    #[test]
    fn content_that_fits_keeps_the_window_where_it_is() {
        let fit = fit_in_work_area((0, 0, 2560, 1920), 2.0, (1040, 400), 520.0, 400.0);
        assert_eq!(
            fit,
            Fit {
                height: 400.0,
                position: None
            }
        );
    }

    #[test]
    fn tall_content_on_a_small_screen_is_clamped_and_moved_on_screen() {
        // Preferences on a 1024x768 screen, centered at its first size.
        let fit = fit_in_work_area((0, 0, 1024, 768), 1.0, (232, 84), 560.0, 900.0);
        assert_eq!(fit.height, 768.0 - SCREEN_MARGIN);
        // The window and its title bar fit between the top and bottom edges.
        let (x, y) = fit.position.expect("moved");
        assert_eq!(x, 232);
        assert!(y >= 0 && f64::from(y) + fit.height + TITLE_BAR <= 768.0);
    }

    #[test]
    fn no_content_height_makes_a_window_larger_than_its_monitor() {
        for scale in [1.0, 1.25, 2.0] {
            let fit = fit_in_work_area((0, 0, 2560, 1440), scale, (0, 0), 920.0, 58_880.0);
            assert!((fit.height + TITLE_BAR) * scale <= 1440.0, "scale {scale}");
        }
    }

    #[test]
    fn a_window_past_the_bottom_edge_is_centered_vertically() {
        // A second monitor to the right, below a top panel.
        let fit = fit_in_work_area((1920, 32, 1920, 1048), 1.0, (2650, 900), 460.0, 300.0);
        assert_eq!(fit.position, Some((2650, 32 + 354)));
        // Off the left edge too: centered on both axes.
        let fit = fit_in_work_area((1920, 32, 1920, 1048), 1.0, (100, 900), 460.0, 300.0);
        assert_eq!(fit.position, Some((1920 + 730, 32 + 354)));
    }

    #[test]
    fn local_windows_keep_the_width_they_open_with() {
        for label in [ONBOARDING, LOGIN, PREFERENCES, OFFLINE] {
            assert!(initial_size(label).is_some(), "{label}");
        }
        assert_eq!(initial_size(LAUNCHER), None);
    }

    #[cfg(not(target_os = "macos"))]
    #[test]
    fn reopening_shows_the_web_sign_in_window_before_login() {
        let position = |label: &str| PRIMARY.iter().position(|l| *l == label);
        let web = position(crate::sso::LABEL).expect("the web sign-in window is primary");
        let login = position(LOGIN).expect("login is primary");
        assert!(web < login);
    }
}
