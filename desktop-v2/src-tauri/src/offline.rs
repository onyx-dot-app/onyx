//! The offline window. It shows when the server cannot be reached at launch,
//! or when a main-window page fails to load. It checks the server again with
//! backoff and loads the server UI again when the server answers.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};
use std::time::{Duration, Instant};

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
/// While a page loads, the server is checked this often, for at most `LOAD_WATCH_LIMIT`.
const LOAD_POLL: Duration = Duration::from_secs(5);
const LOAD_WATCH_LIMIT: Duration = Duration::from_secs(60);

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

/// Main-window navigations, by id. A load belongs to the navigation that was
/// the latest when its document committed, so a late `Finished` from an
/// earlier document does not count for a newer navigation.
#[derive(Debug, Default)]
struct Loads {
    latest: u64,
    committed: u64,
    finished: u64,
}

impl Loads {
    fn navigated(&mut self) -> u64 {
        self.latest += 1;
        self.latest
    }

    fn committed(&mut self) {
        self.committed = self.latest;
    }

    fn finished(&mut self) {
        self.finished = self.finished.max(self.committed);
    }

    fn is_latest(&self, id: u64) -> bool {
        self.latest == id
    }

    fn has_finished(&self, id: u64) -> bool {
        self.finished == id
    }
}

#[derive(Default)]
pub struct Offline {
    pending: Mutex<Option<Pending>>,
    next_id: AtomicU64,
    wake: Notify,
    loads: Mutex<Loads>,
}

impl Offline {
    fn pending(&self) -> MutexGuard<'_, Option<Pending>> {
        self.pending.lock().unwrap_or_else(|p| p.into_inner())
    }

    fn loads(&self) -> MutexGuard<'_, Loads> {
        self.loads.lock().unwrap_or_else(|p| p.into_inner())
    }
}

/// Shows the offline window for `reason`; `path` loads in the main window on
/// recovery. Does nothing if the session `epoch` ended meanwhile (sign-out,
/// server change). On error the main window is shown again.
pub fn show(app: &AppHandle, path: &str, reason: Unreachable, epoch: u64) -> Result<(), String> {
    let state = app.state::<AppState>();
    let Ok(server) = state.server() else {
        return Ok(());
    };
    let server_locked = state.policy().lock_server_url;
    let offline = app.state::<Offline>();
    let started = {
        let mut pending = offline.pending();
        // Under the lock `dismiss` takes after the epoch ends.
        if state.epoch() != epoch {
            return Ok(());
        }
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
    log::warn!("server unreachable ({reason}); showing the offline window");
    // The main window only holds the failed page; it comes back on recovery.
    if let Some(main) = app.get_webview_window(main_window::LABEL) {
        let _ = main.hide();
    }
    let window = match windows::open_offline(app) {
        Ok(window) => window,
        Err(e) => {
            log::warn!("could not open the offline window: {e}");
            if let Some(id) = started {
                let mut pending = offline.pending();
                if pending.as_ref().is_some_and(|p| p.id == id) {
                    *pending = None;
                }
            }
            if let Some(main) = app.get_webview_window(main_window::LABEL) {
                windows::bring_forward(app, &main);
            }
            return Err(e);
        }
    };
    // A sign-out after the epoch check above dismissed the state.
    let current = match (offline.pending().as_ref(), started) {
        (Some(p), Some(id)) => p.id == id,
        (Some(_), None) => true,
        (None, _) => false,
    };
    if !current {
        let _ = window.destroy();
        return Ok(());
    }
    let Some(id) = started else {
        update(app, None, |_| {});
        return Ok(());
    };
    let close_app = app.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::Destroyed = event {
            closed_by_user(&close_app, id);
        }
    });
    let app = app.clone();
    tauri::async_runtime::spawn(async move { monitor(app, id).await });
    Ok(())
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

/// Checks the server now (Retry button, network back). Wakes every waiting
/// monitor: an old one from a closed window exits, the current one checks.
/// A monitor that is checking at that moment needs no wake.
pub fn retry_now(app: &AppHandle) {
    app.state::<Offline>().wake.notify_waiters();
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
        let state = app.state::<AppState>();
        let Ok(server) = state.server() else {
            dismiss(&app);
            return;
        };
        if let Err(reason) = check(&state, &server).await {
            update(&app, Some(id), |s| s.reason = reason);
            continue;
        }
        recover(&app, id);
        return;
    }
}

/// The API and the web UI answer, and the stored session is valid, rejected
/// (sign-in follows) or absent. A failed check keeps the offline window and
/// its backoff.
async fn check(state: &AppState, server: &str) -> Result<(), Unreachable> {
    state.api.health(server).await?;
    match state.token(server) {
        Some(token) => state.api.session_valid(server, &token).await.map(|_| ()),
        None => Ok(()),
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

/// The path, query and fragment of `url`, as a path that
/// `main_window::server_url_join` resolves to the same URL. A path that starts
/// with `//` gets a `/.` prefix, so it is not read as another host.
pub fn path_of(url: &Url) -> String {
    let path = &url[url::Position::BeforePath..];
    if path.starts_with("//") {
        format!("/.{path}")
    } else {
        path.to_string()
    }
}

/// Called for each main-window navigation to the server. While the page has
/// not finished loading, the server (API and web UI) is checked; if it then
/// fails two checks, the offline window shows. A finished page stays, unless
/// the server returns 5xx errors (a proxy error page also finishes loading).
pub fn watch_load(app: &AppHandle, url: &Url) {
    let load = app.state::<Offline>().loads().navigated();
    let epoch = app.state::<AppState>().epoch();
    let path = path_of(url);
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let state = app.state::<AppState>();
        let offline = app.state::<Offline>();
        let deadline = Instant::now() + LOAD_WATCH_LIMIT;
        // A newer load has its own check; a new session has its own windows.
        // A closed main window has no page to recover.
        let current = || {
            offline.loads().is_latest(load)
                && state.epoch() == epoch
                && app.get_webview_window(main_window::LABEL).is_some()
        };
        loop {
            let Ok(server) = state.server() else {
                return;
            };
            if !current() {
                return;
            }
            if state.api.health(&server).await.is_ok() {
                if offline.loads().has_finished(load) || Instant::now() >= deadline {
                    return;
                }
                tokio::time::sleep(LOAD_POLL).await;
                continue;
            }
            tokio::time::sleep(RECHECK_DELAY).await;
            let Err(reason) = state.api.health(&server).await else {
                if offline.loads().has_finished(load) || Instant::now() >= deadline {
                    return;
                }
                continue;
            };
            if !current() {
                return;
            }
            let finished = offline.loads().has_finished(load);
            if finished && !matches!(reason, Unreachable::ServerError { .. }) {
                return;
            }
            // wry reports iframe navigations here too, so recovery reopens
            // the window's own document, not the URL this check started for.
            let path = top_level_path(&app, &server).unwrap_or(path);
            if let Err(e) = show(&app, &path, reason, epoch) {
                log::warn!("the main window keeps the failed page: {e}");
            }
            return;
        }
    });
}

/// The path of the main window's document, if it is on `server`.
fn top_level_path(app: &AppHandle, server: &str) -> Option<String> {
    let url = app.get_webview_window(main_window::LABEL)?.url().ok()?;
    let server = Url::parse(server).ok()?;
    (url.origin() == server.origin()).then(|| path_of(&url))
}

/// The main window committed a new document (`PageLoadEvent::Started`).
pub fn load_committed(app: &AppHandle) {
    app.state::<Offline>().loads().committed();
}

pub fn load_finished(app: &AppHandle) {
    app.state::<Offline>().loads().finished();
}

#[cfg(test)]
mod tests {
    use super::{path_of, Loads};
    use crate::main_window::server_url_join;
    use url::Url;

    #[test]
    fn keeps_query_and_fragment() {
        let url = Url::parse("http://localhost:3000/app?chatId=1#end").unwrap();
        assert_eq!(path_of(&url), "/app?chatId=1#end");
    }

    #[test]
    fn leading_slashes_reopen_the_same_page() {
        let server = Url::parse("https://onyx.example").unwrap();
        for raw in [
            "https://onyx.example//reports/7?a=1#b",
            "https://onyx.example//evil.example/login",
            "https://onyx.example/\\evil.example/",
        ] {
            let url = Url::parse(raw).unwrap();
            let joined = server_url_join(&server, &path_of(&url)).unwrap();
            assert_eq!(joined, url);
        }
    }

    #[test]
    fn a_load_finishes_its_own_navigation() {
        let mut loads = Loads::default();
        let first = loads.navigated();
        loads.committed();
        assert!(!loads.has_finished(first));
        loads.finished();
        assert!(loads.has_finished(first));
    }

    #[test]
    fn an_earlier_finish_does_not_count_for_a_newer_navigation() {
        let mut loads = Loads::default();
        let first = loads.navigated();
        loads.committed();
        let second = loads.navigated();
        // The first document finishes after the second navigation started.
        loads.finished();
        assert!(!loads.is_latest(first));
        assert!(!loads.has_finished(second));
        loads.committed();
        loads.finished();
        assert!(loads.has_finished(second));
    }

    #[test]
    fn a_redirect_finishes_the_latest_navigation() {
        let mut loads = Loads::default();
        loads.navigated();
        let redirect = loads.navigated();
        loads.committed();
        loads.finished();
        assert!(loads.has_finished(redirect));
    }
}
