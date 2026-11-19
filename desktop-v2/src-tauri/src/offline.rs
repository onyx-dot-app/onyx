//! The offline window. It shows when the server cannot be reached at launch,
//! or when a main-window page fails to load. It checks the server again with
//! backoff and loads the server UI again when the server answers.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};
use tokio::sync::Notify;
use url::Url;

use crate::main_window;
use crate::reachability::{display_host, Unreachable};
use crate::state::AppState;
use crate::windows;

pub const STATUS_EVENT: &str = "offline-status";
/// Seconds between automatic checks; the last step repeats.
const BACKOFF_SECS: [u64; 6] = [2, 4, 8, 15, 30, 60];
/// A failed check is tried once more after this, so a short blip is ignored.
const RECHECK_DELAY: Duration = Duration::from_secs(2);

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OfflineStatus {
    host: String,
    reason: Unreachable,
    checking: bool,
    /// Milliseconds until the next automatic check.
    next_retry_ms: Option<u64>,
    /// Managed policy locks the server, so Change server is hidden.
    server_locked: bool,
}

struct Pending {
    id: u64,
    /// The main-window path to load when the server is back.
    path: String,
    status: OfflineStatus,
}

#[derive(Default)]
pub struct Offline {
    pending: Mutex<Option<Pending>>,
    next_id: AtomicU64,
    wake: Notify,
    // Main-window loads: the count started and the count finished.
    loads_started: AtomicU64,
    loads_finished: AtomicU64,
}

impl Offline {
    fn pending(&self) -> MutexGuard<'_, Option<Pending>> {
        self.pending.lock().unwrap_or_else(|p| p.into_inner())
    }
}

/// Shows the offline window for `reason`; `path` loads in the main window on recovery.
pub fn show(app: &AppHandle, path: &str, reason: Unreachable) {
    let state = app.state::<AppState>();
    let Ok(server) = state.server() else {
        return;
    };
    let server_locked = state.policy().lock_server_url;
    log::warn!("server unreachable ({reason}); showing the offline window");
    let offline = app.state::<Offline>();
    let started = {
        let mut pending = offline.pending();
        match pending.as_mut() {
            Some(p) => {
                p.path = path.to_string();
                p.status.reason = reason;
                None
            }
            None => {
                let id = offline.next_id.fetch_add(1, Ordering::SeqCst) + 1;
                *pending = Some(Pending {
                    id,
                    path: path.to_string(),
                    status: OfflineStatus {
                        host: display_host(&server),
                        reason,
                        checking: false,
                        next_retry_ms: None,
                        server_locked,
                    },
                });
                Some(id)
            }
        }
    };
    // The main window only holds the failed page; it comes back on recovery.
    if let Some(main) = app.get_webview_window(main_window::LABEL) {
        let _ = main.hide();
    }
    let window = match windows::open_offline(app) {
        Ok(window) => window,
        Err(e) => {
            log::warn!("could not open the offline window: {e}");
            return;
        }
    };
    let Some(id) = started else {
        update(app, None, |_| {});
        return;
    };
    let close_app = app.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::Destroyed = event {
            closed_by_user(&close_app, id);
        }
    });
    let app = app.clone();
    tauri::async_runtime::spawn(async move { monitor(app, id).await });
}

/// While the offline window shows, an Onyx page request (launcher, menu) is
/// kept for recovery and checks the server now. Returns whether it was kept.
pub fn defer_open(app: &AppHandle, path: &str) -> bool {
    {
        let offline = app.state::<Offline>();
        let mut pending = offline.pending();
        let Some(p) = pending.as_mut() else {
            return false;
        };
        p.path = path.to_string();
    }
    if let Some(window) = app.get_webview_window(windows::OFFLINE) {
        windows::bring_forward(app, &window);
    }
    retry_now(app);
    true
}

/// Checks the server now (Retry button, network back).
pub fn retry_now(app: &AppHandle) {
    app.state::<Offline>().wake.notify_one();
}

pub fn status(app: &AppHandle) -> Option<OfflineStatus> {
    app.state::<Offline>()
        .pending()
        .as_ref()
        .map(|p| p.status.clone())
}

/// Closes the offline window without loading Onyx (sign-out, server change).
pub fn dismiss(app: &AppHandle) {
    if app.state::<Offline>().pending().take().is_some() {
        windows::close(app, windows::OFFLINE);
    }
}

/// The user closed the window: stop checking, and drop the hidden main
/// window with its failed page. Opening Onyx again starts over.
fn closed_by_user(app: &AppHandle, id: u64) {
    let offline = app.state::<Offline>();
    let mut pending = offline.pending();
    if pending.as_ref().is_some_and(|p| p.id == id) {
        *pending = None;
        drop(pending);
        windows::close(app, main_window::LABEL);
    }
}

/// Changes the status of offline window `id` (any, for `None`) and sends it
/// to the page. Returns false once that window is gone.
fn update(app: &AppHandle, id: Option<u64>, change: impl FnOnce(&mut OfflineStatus)) -> bool {
    let status = {
        let offline = app.state::<Offline>();
        let mut pending = offline.pending();
        match pending.as_mut() {
            Some(p) if id.is_none_or(|id| id == p.id) => {
                change(&mut p.status);
                p.status.clone()
            }
            _ => return false,
        }
    };
    let _ = app.emit_to(windows::OFFLINE, STATUS_EVENT, status);
    true
}

async fn monitor(app: AppHandle, id: u64) {
    let mut step = 0;
    loop {
        let delay = Duration::from_secs(BACKOFF_SECS[step.min(BACKOFF_SECS.len() - 1)]);
        let delay_ms = u64::try_from(delay.as_millis()).unwrap_or(u64::MAX);
        if !update(&app, Some(id), |s| {
            s.checking = false;
            s.next_retry_ms = Some(delay_ms);
        }) {
            return;
        }
        let woken = tokio::time::timeout(delay, app.state::<Offline>().wake.notified())
            .await
            .is_ok();
        // A manual retry starts the backoff over.
        step = if woken { 0 } else { step + 1 };
        if !update(&app, Some(id), |s| {
            s.checking = true;
            s.next_retry_ms = None;
        }) {
            return;
        }
        let Ok(server) = app.state::<AppState>().server() else {
            dismiss(&app);
            return;
        };
        match app.state::<AppState>().api.health(&server).await {
            Ok(()) => {
                recover(&app, id);
                return;
            }
            Err(reason) => {
                update(&app, Some(id), |s| s.reason = reason);
            }
        }
    }
}

fn recover(app: &AppHandle, id: u64) {
    let path = {
        let offline = app.state::<Offline>();
        let mut pending = offline.pending();
        match pending.take() {
            Some(p) if p.id == id => p.path,
            other => {
                *pending = other;
                return;
            }
        }
    };
    log::info!("server reachable again; loading {path}");
    windows::close(app, windows::OFFLINE);
    windows::route_to(app, &path);
}

fn path_of(url: &Url) -> String {
    let mut path = url.path().to_string();
    if let Some(query) = url.query() {
        path = format!("{path}?{query}");
    }
    if let Some(fragment) = url.fragment() {
        path = format!("{path}#{fragment}");
    }
    path
}

/// Called for each main-window navigation to the server. If the server then
/// fails two health checks, a load that has not finished shows the offline
/// window. A finished page stays, unless the server returns 5xx errors.
pub fn watch_load(app: &AppHandle, url: &Url) {
    let load = app
        .state::<Offline>()
        .loads_started
        .fetch_add(1, Ordering::SeqCst)
        + 1;
    let path = path_of(url);
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let state = app.state::<AppState>();
        let Ok(server) = state.server() else {
            return;
        };
        if state.api.health(&server).await.is_ok() {
            return;
        }
        tokio::time::sleep(RECHECK_DELAY).await;
        let Err(reason) = state.api.health(&server).await else {
            return;
        };
        let offline = app.state::<Offline>();
        // A newer load has its own check.
        if offline.loads_started.load(Ordering::SeqCst) != load {
            return;
        }
        let finished = offline.loads_finished.load(Ordering::SeqCst) >= load;
        if finished && !matches!(reason, Unreachable::ServerError { .. }) {
            return;
        }
        show(&app, &path, reason);
    });
}

pub fn load_finished(app: &AppHandle) {
    let offline = app.state::<Offline>();
    let started = offline.loads_started.load(Ordering::SeqCst);
    offline.loads_finished.fetch_max(started, Ordering::SeqCst);
}

#[cfg(test)]
mod tests {
    use super::path_of;
    use url::Url;

    #[test]
    fn keeps_query_and_fragment() {
        let url = Url::parse("http://localhost:3000/app?chatId=1#end").unwrap();
        assert_eq!(path_of(&url), "/app?chatId=1#end");
    }
}
