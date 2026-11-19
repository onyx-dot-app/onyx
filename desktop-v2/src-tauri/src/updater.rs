//! Auto-update: check quietly after launch and every few
//! hours, download in the background, then offer "Restart to Update" in the app
//! and tray menus instead of restarting on its own. "Check for Updates…" runs
//! the same check on demand and reports the result.
//!
//! The update feed and the public key come from `plugins.updater` in
//! tauri.conf.json. Every download is verified against that key before it is
//! installed; a build signed with any other key is rejected.

use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::MenuItem;
use tauri::{AppHandle, Wry};
use tauri_plugin_updater::{Update, UpdaterExt};

/// The feed has macOS builds only. Until it has signed Windows and Linux
/// builds, those platforms do not check for updates and show no update item.
pub const SUPPORTED: bool = cfg!(target_os = "macos");
pub const CHECK_ID: &str = "check_updates";
const FIRST_CHECK_DELAY: Duration = Duration::from_secs(15);
const CHECK_INTERVAL: Duration = Duration::from_secs(6 * 60 * 60);

struct ReadyUpdate {
    update: Update,
    bytes: Vec<u8>,
}

static READY: Mutex<Option<ReadyUpdate>> = Mutex::new(None);
static CHECKING: Mutex<bool> = Mutex::new(false);
static INSTALLING: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
/// "Check for Updates…" items in the app menu and the tray menu.
static MENU_ITEMS: Mutex<Vec<MenuItem<Wry>>> = Mutex::new(Vec::new());

pub enum Outcome {
    UpToDate,
    Ready(String),
    Busy,
}

pub fn register_menu_item(item: MenuItem<Wry>) {
    MENU_ITEMS
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .push(item);
}

fn set_menu_label(label: &str) {
    for item in MENU_ITEMS.lock().unwrap_or_else(|p| p.into_inner()).iter() {
        let _ = item.set_text(label);
    }
}

fn ready_version() -> Option<String> {
    READY
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .as_ref()
        .map(|r| r.update.version.clone())
}

/// Longest time for the feed request or the download.
const REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(10 * 60);

/// Checks the feed and downloads a newer version if there is one.
pub async fn check_and_download(app: &AppHandle) -> Result<Outcome, String> {
    if let Some(version) = ready_version() {
        return Ok(Outcome::Ready(version));
    }
    {
        let mut checking = CHECKING.lock().unwrap_or_else(|p| p.into_inner());
        if *checking {
            return Ok(Outcome::Busy);
        }
        *checking = true;
    }
    let result = async {
        // A feed or download that stops responding fails instead of leaving
        // the check running (the plugin has no default timeout).
        let updater = app
            .updater_builder()
            .timeout(REQUEST_TIMEOUT)
            .build()
            .map_err(|e| e.to_string())?;
        let Some(update) = updater.check().await.map_err(|e| e.to_string())? else {
            return Ok(Outcome::UpToDate);
        };
        let mut update = update;
        // The builder's timeout covers the feed request only.
        update.timeout = Some(REQUEST_TIMEOUT);
        set_menu_label(&format!("Downloading Update ({})…", update.version));
        // Verifies the signature against the configured public key.
        let bytes = update
            .download(|_, _| {}, || {})
            .await
            .map_err(|e| e.to_string())?;
        let version = update.version.clone();
        *READY.lock().unwrap_or_else(|p| p.into_inner()) = Some(ReadyUpdate { update, bytes });
        set_menu_label(&format!("Restart to Update ({version})"));
        Ok(Outcome::Ready(version))
    }
    .await;
    *CHECKING.lock().unwrap_or_else(|p| p.into_inner()) = false;
    if result.is_err() && ready_version().is_none() {
        set_menu_label("Check for Updates…");
    }
    result
}

/// Installs the downloaded update and relaunches into it.
/// A failed install keeps the download, so "Restart to Update" retries the
/// install instead of downloading again.
pub fn install_and_restart(app: &AppHandle) -> Result<(), String> {
    {
        let ready = READY.lock().unwrap_or_else(|p| p.into_inner());
        let Some(ready) = ready.as_ref() else {
            return Err("No update has been downloaded.".into());
        };
        ready
            .update
            .install(&ready.bytes)
            .map_err(|e| e.to_string())?;
    }
    app.restart();
}

/// Quiet background checks: shortly after launch, then every few hours.
pub fn spawn_background_checks(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(FIRST_CHECK_DELAY).await;
        loop {
            if let Err(e) = check_and_download(&app).await {
                log::warn!("update check failed: {e}");
            }
            tokio::time::sleep(CHECK_INTERVAL).await;
        }
    });
}

/// Installs the downloaded update off the main thread (it unpacks and
/// replaces the whole app, so the UI would freeze). Repeat requests while it
/// runs are ignored; a failure is shown and can be retried.
fn start_install(app: &AppHandle) {
    use std::sync::atomic::Ordering;
    if INSTALLING.swap(true, Ordering::SeqCst) {
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        if let Err(e) = install_and_restart(&app) {
            INSTALLING.store(false, Ordering::SeqCst);
            log::warn!("update install failed: {e}");
            show_message(&app, "Could not install the update", &e);
        }
    });
}

/// The menu item: installs a downloaded update, or checks and reports.
pub fn on_menu(app: &AppHandle) {
    // Checked first: the install holds the downloaded update, and waiting for
    // it here would block the main thread.
    if INSTALLING.load(std::sync::atomic::Ordering::SeqCst) {
        return;
    }
    if ready_version().is_some() {
        start_install(app);
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        match check_and_download(&app).await {
            Ok(Outcome::UpToDate) => show_message(
                &app,
                "You're up to date",
                &format!("Onyx {} is the latest version.", app.package_info().version),
            ),
            Ok(Outcome::Ready(version)) => offer_restart(&app, &version),
            Ok(Outcome::Busy) => {}
            Err(e) => {
                log::warn!("update check failed: {e}");
                show_message(
                    &app,
                    "Could not check for updates",
                    "The update service is unavailable right now. Try again later.",
                );
            }
        }
    });
}

fn show_message(app: &AppHandle, title: &str, detail: &str) {
    let (title, detail) = (title.to_string(), detail.to_string());
    let _ = app.run_on_main_thread(move || {
        rfd::MessageDialog::new()
            .set_title(&title)
            .set_description(&detail)
            .set_buttons(rfd::MessageButtons::Ok)
            .show();
    });
}

fn offer_restart(app: &AppHandle, version: &str) {
    let handle = app.clone();
    let version = version.to_string();
    let _ = app.run_on_main_thread(move || {
        let choice = rfd::MessageDialog::new()
            .set_title("An update is ready")
            .set_description(format!(
                "Onyx {version} has been downloaded. Restart now to finish updating?"
            ))
            .set_buttons(rfd::MessageButtons::OkCancelCustom(
                "Restart Now".into(),
                "Later".into(),
            ))
            .show();
        if choice == rfd::MessageDialogResult::Custom("Restart Now".into()) {
            start_install(&handle);
        }
    });
}
