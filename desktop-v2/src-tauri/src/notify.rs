//! Native notifications. Answers can take a minute, so when one finishes while
//! the launcher is hidden, a notification tells the user; clicking it shows the
//! launcher again, which still holds the answer. The notification never shows
//! the question or the answer: lock screens and notification history keep it.

use tauri::plugin::{PermissionState, Plugin, TauriPlugin};
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_notification::{ActionPerformed, NotificationExt};

use crate::state::AppState;

const BODY: &str = "Your answer is ready in the launcher.";
const ANSWER_KEY: &str = "answer";
const EPOCH_KEY: &str = "epoch";

/// The notification plugin without its JavaScript. The plugin's script would
/// replace `window.Notification` in every webview, the remote main window too;
/// only Rust shows notifications here.
pub fn plugin<R: Runtime>() -> impl Plugin<R> {
    WithoutScript(tauri_plugin_notification::init())
}

struct WithoutScript<R: Runtime>(TauriPlugin<R>);

impl<R: Runtime> Plugin<R> for WithoutScript<R> {
    fn name(&self) -> &'static str {
        self.0.name()
    }

    fn initialize(
        &mut self,
        app: &AppHandle<R>,
        config: serde_json::Value,
    ) -> Result<(), Box<dyn std::error::Error>> {
        self.0.initialize(app, config)
    }

    // Not delegated, and `initialization_script_2` defaults to this, so no
    // webview gets the plugin's script.
    fn initialization_script(&self) -> Option<String> {
        None
    }

    fn window_created(&mut self, window: tauri::Window<R>) {
        self.0.window_created(window)
    }

    fn webview_created(&mut self, webview: tauri::Webview<R>) {
        self.0.webview_created(webview)
    }

    fn on_navigation(&mut self, webview: &tauri::Webview<R>, url: &tauri::Url) -> bool {
        self.0.on_navigation(webview, url)
    }

    fn on_page_load(
        &mut self,
        webview: &tauri::Webview<R>,
        payload: &tauri::webview::PageLoadPayload<'_>,
    ) {
        self.0.on_page_load(webview, payload)
    }

    fn on_event(&mut self, app: &AppHandle<R>, event: &tauri::RunEvent) {
        self.0.on_event(app, event)
    }

    fn extend_api(&mut self, invoke: tauri::ipc::Invoke<R>) -> bool {
        self.0.extend_api(invoke)
    }
}

/// A launcher answer, and the session it was asked in.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Answer {
    pub id: u64,
    pub epoch: u64,
}

impl Answer {
    /// Whether the launcher still holds this answer, in the same session.
    fn is_current(self, state: &AppState) -> bool {
        state.epoch() == self.epoch && crate::aonyx::is_latest_answer(self.id)
    }
}

/// Tells the launcher page to show its answer (Ask mode).
const SHOW_ANSWER_EVENT: &str = "launcher-show-answer";

pub fn init(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.notification().on_action(move |performed| {
        if let Some(answer) = tapped(performed) {
            open_answer(&handle, answer);
        }
    });
}

/// Shows the launcher with the answer of a clicked notification.
fn open_answer(app: &AppHandle, answer: Answer) {
    // A stale notification is ignored: the launcher no longer holds its
    // answer, and showing another chat would be wrong.
    crate::launcher::show(
        app,
        move |app| {
            let current = answer.is_current(&app.state::<AppState>());
            if current {
                // The launcher may be in Search mode; the click is for the answer.
                let _ = app.emit_to(crate::windows::LAUNCHER, SHOW_ANSWER_EVENT, ());
            }
            current
        },
        crate::windows::route,
    );
}

/// Windows delivers a click on a toast in Action Center only through an
/// activation that starts the app. A toast that opens this `onyx://` link
/// reaches the running app (single instance) also from Action Center.
#[cfg(any(windows, test))]
const ANSWER_LINK: &str = "onyx://launcher/answer";

#[cfg(any(windows, test))]
const RUN_KEY: &str = "run";

/// Answer and session counters start again in each run, and Action Center
/// keeps a toast after the app quits; a toast opens only the run that showed it.
#[cfg(windows)]
fn this_run() -> u64 {
    static RUN: std::sync::OnceLock<u64> = std::sync::OnceLock::new();
    *RUN.get_or_init(rand::random)
}

#[cfg(any(windows, test))]
fn answer_link(answer: Answer, run: u64) -> String {
    format!(
        "{ANSWER_LINK}?{ANSWER_KEY}={}&{EPOCH_KEY}={}&{RUN_KEY}={run}",
        answer.id, answer.epoch
    )
}

/// Whether `url` is an `onyx://launcher/answer` link, from this run or not.
#[cfg(any(windows, test))]
fn is_answer_route(url: &url::Url) -> bool {
    url.scheme() == "onyx" && url.host_str() == Some("launcher") && url.path() == "/answer"
}

/// The answer of an `onyx://launcher/answer` link from run `run`.
#[cfg(any(windows, test))]
fn linked_answer(url: &url::Url, run: u64) -> Option<Answer> {
    if !is_answer_route(url) {
        return None;
    }
    let param = |key: &str| {
        url.query_pairs()
            .find(|(k, _)| k == key)
            .and_then(|(_, v)| v.parse::<u64>().ok())
    };
    if param(RUN_KEY)? != run {
        return None;
    }
    Some(Answer {
        id: param(ANSWER_KEY)?,
        epoch: param(EPOCH_KEY)?,
    })
}

/// Whether a launch argument is a notification click (see `ANSWER_LINK`).
/// A toast from an earlier run counts too: it must not open the main window.
#[cfg(any(windows, test))]
pub fn is_answer_link(arg: &str) -> bool {
    url::Url::parse(arg).is_ok_and(|url| is_answer_route(&url))
}

/// Whether the process arguments (without the program) hold a toast click.
#[cfg(any(windows, test))]
fn started_by_toast<S: AsRef<std::ffi::OsStr>>(args: impl IntoIterator<Item = S>) -> bool {
    args.into_iter()
        .any(|arg| arg.as_ref().to_str().is_some_and(is_answer_link))
}

/// A toast click starts a second process that hands the link to the running
/// one. Only the process the click started may take the foreground, so it
/// passes that right on at once, before startup work can use it up.
#[cfg(windows)]
pub fn pass_on_foreground() {
    use windows::Win32::UI::WindowsAndMessaging::{AllowSetForegroundWindow, ASFW_ANY};

    if started_by_toast(std::env::args_os().skip(1)) {
        // SAFETY: no pointers; a failure only means Windows refused the right.
        let _ = unsafe { AllowSetForegroundWindow(ASFW_ANY) };
    }
}

/// Handles `onyx://launcher/answer?..` from a clicked toast.
#[cfg(windows)]
pub fn handle_link(app: &AppHandle, url: &url::Url) {
    if let Some(answer) = linked_answer(url, this_run()) {
        open_answer(app, answer);
    }
}

/// A toast that opens `link` when clicked. Text is XML-escaped.
#[cfg(any(windows, test))]
fn toast_xml(title: &str, body: &str, link: &str) -> String {
    let escape = |s: &str| {
        s.replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
            .replace('\'', "&apos;")
    };
    format!(
        "<toast activationType=\"protocol\" launch=\"{}\"><visual><binding template=\"ToastGeneric\"><text>{}</text><text>{}</text></binding></visual></toast>",
        escape(link),
        escape(title),
        escape(body)
    )
}

/// Shows a toast that opens the answer's link when clicked.
#[cfg(windows)]
fn show_toast(app: &AppHandle, title: &str, body: &str, answer: Answer) -> Result<(), String> {
    use windows::core::HSTRING;
    use windows::Data::Xml::Dom::XmlDocument;
    use windows::UI::Notifications::{ToastNotification, ToastNotificationManager};

    // Windows shows toasts only for an app ID with a Start menu shortcut. The
    // installers add one for the identifier; a build run from `target` uses
    // PowerShell's, as tauri-plugin-notification does.
    let exe = tauri::utils::platform::current_exe().map_err(|e| e.to_string())?;
    let in_target = exe
        .parent()
        .is_some_and(|dir| dir.ends_with("target/debug") || dir.ends_with("target/release"));
    let app_id = if in_target {
        r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe".to_string()
    } else {
        app.config().identifier.clone()
    };
    let show = || -> windows::core::Result<()> {
        let xml = XmlDocument::new()?;
        xml.LoadXml(&HSTRING::from(toast_xml(
            title,
            body,
            &answer_link(answer, this_run()),
        )))?;
        let toast = ToastNotification::CreateToastNotification(&xml)?;
        ToastNotificationManager::CreateToastNotifierWithId(&HSTRING::from(app_id))?.Show(&toast)
    };
    show().map_err(|e| e.to_string())
}

/// The answer of a clicked notification. Desktop reports a click on the
/// notification itself as "tap".
fn tapped(performed: &ActionPerformed) -> Option<Answer> {
    if performed.action_id() != "tap" {
        return None;
    }
    let extra = performed.notification()?.extra();
    Some(Answer {
        id: extra.get(ANSWER_KEY)?.as_u64()?,
        epoch: extra.get(EPOCH_KEY)?.as_u64()?,
    })
}

/// Whether the user, and managed policy, allow answer notifications.
pub fn enabled(state: &AppState) -> bool {
    !state.policy().disable_notifications && state.config.get().notify_answers()
}

/// How a launcher answer ended.
pub enum Outcome {
    Answered,
    NeedsApproval,
    Failed,
}

/// Called when a launcher answer has ended.
pub fn answer_finished(app: &AppHandle, answer: Answer, outcome: Outcome) {
    let state = app.state::<AppState>();
    let allowed = || {
        should_notify(enabled(&state), answer.is_current(&state), || {
            crate::launcher::is_visible(app)
        })
    };
    // Checked again after the permission prompt, which can wait for the user
    // while policy, the setting or the launcher changes.
    if !allowed() || !permitted(app) || !allowed() {
        return;
    }
    let (title, body) = match outcome {
        Outcome::Answered => ("Onyx answered", BODY),
        Outcome::NeedsApproval => (
            "Onyx needs your approval",
            "Approve the tool call in the Onyx window.",
        ),
        Outcome::Failed => ("Onyx couldn't answer", "See the launcher for details."),
    };
    #[cfg(target_os = "linux")]
    warn_if_no_session_bus();
    // Checked again: a sign-out or new chat during the checks above suppresses it.
    let shown = state.while_current(answer.epoch, || {
        crate::aonyx::while_latest(answer.id, || {
            #[cfg(windows)]
            {
                show_toast(app, title, body, answer)
            }
            #[cfg(not(windows))]
            {
                app.notification()
                    .builder()
                    .id((answer.id % i32::MAX as u64) as i32)
                    .title(title)
                    .body(body)
                    .extra(ANSWER_KEY, answer.id)
                    .extra(EPOCH_KEY, answer.epoch)
                    .show()
            }
        })
    });
    if let Some(Some(Err(e))) = shown {
        log::warn!("could not show the answer notification: {e}");
    }
}

/// The plugin sends notifications on a background task and drops its
/// errors. Its D-Bus client (zbus) finds the session bus only through
/// DBUS_SESSION_BUS_ADDRESS or the runtime directory's `bus` socket, not
/// through X11 autolaunch, so say when neither is there.
#[cfg(target_os = "linux")]
fn warn_if_no_session_bus() {
    let address = std::env::var_os("DBUS_SESSION_BUS_ADDRESS");
    let runtime_dir = std::env::var_os("XDG_RUNTIME_DIR")
        .map(std::path::PathBuf::from)
        // SAFETY: geteuid has no preconditions.
        .unwrap_or_else(|| format!("/run/user/{}", unsafe { libc::geteuid() }).into());
    if !session_bus_findable(address.as_deref(), runtime_dir.join("bus").exists()) {
        log::warn!(
            "no D-Bus session bus address (DBUS_SESSION_BUS_ADDRESS is not set and {} does not \
             exist): the answer notification cannot be shown",
            runtime_dir.join("bus").display()
        );
    }
}

#[cfg(any(test, target_os = "linux"))]
fn session_bus_findable(address: Option<&std::ffi::OsStr>, runtime_socket: bool) -> bool {
    // zbus uses the socket only when the variable is unset; a set but
    // empty address fails to parse.
    match address {
        Some(address) => !address.is_empty(),
        None => runtime_socket,
    }
}

/// Only the current answer notifies, and only while the launcher is hidden.
fn should_notify(enabled: bool, current: bool, launcher_visible: impl FnOnce() -> bool) -> bool {
    enabled && current && !launcher_visible()
}

/// Asks for permission the first time a notification is due, not at startup.
fn permitted(app: &AppHandle) -> bool {
    let notification = app.notification();
    match notification.permission_state() {
        Ok(PermissionState::Granted) => true,
        Ok(PermissionState::Denied) | Err(_) => false,
        Ok(_) => matches!(
            notification.request_permission(),
            Ok(PermissionState::Granted)
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_plugin_adds_no_script_to_webviews() {
        let original = tauri_plugin_notification::init::<tauri::Wry>();
        assert!(original.initialization_script_2().is_some());
        assert!(plugin::<tauri::Wry>().initialization_script_2().is_none());
    }

    #[test]
    fn the_session_bus_is_found_by_address_or_runtime_socket() {
        let address = std::ffi::OsStr::new("unix:path=/run/user/1000/bus");
        assert!(session_bus_findable(Some(address), false));
        assert!(session_bus_findable(None, true));
        assert!(!session_bus_findable(None, false));
        assert!(!session_bus_findable(Some(std::ffi::OsStr::new("")), false));
        assert!(!session_bus_findable(Some(std::ffi::OsStr::new("")), true));
    }

    #[test]
    fn only_the_current_answer_notifies_while_the_launcher_is_hidden() {
        assert!(should_notify(true, true, || false));
        assert!(!should_notify(true, true, || true));
        assert!(!should_notify(true, false, || false));
        assert!(!should_notify(false, true, || false));
    }

    fn performed(action: &str, extra: serde_json::Value) -> ActionPerformed {
        // The payload the plugin sends on desktop: the notification as it was built.
        serde_json::from_value(serde_json::json!({
            "actionId": action,
            "inputValue": null,
            "notification": { "id": 3, "title": "Onyx answered", "extra": extra },
        }))
        .expect("an action payload")
    }

    #[test]
    fn a_toast_link_carries_the_answer_and_its_session() {
        let answer = Answer { id: 7, epoch: 2 };
        let link = url::Url::parse(&answer_link(answer, 9)).expect("a valid link");
        assert_eq!(linked_answer(&link, 9), Some(answer));
        let parse = |s: &str| linked_answer(&url::Url::parse(s).unwrap(), 9);
        assert_eq!(parse("onyx://auth/callback?answer=7&epoch=2&run=9"), None);
        assert_eq!(parse("onyx://launcher/answer?answer=7&run=9"), None);
        assert_eq!(parse("onyx://launcher/answer?answer=x&epoch=2&run=9"), None);
        assert_eq!(
            parse("https://launcher/answer?answer=7&epoch=2&run=9"),
            None
        );
    }

    #[test]
    fn a_process_started_by_a_toast_click_is_known() {
        let link = answer_link(Answer { id: 3, epoch: 1 }, 8);
        assert!(started_by_toast([link.as_str()]));
        assert!(started_by_toast(["--flag", "onyx://launcher/answer"]));
        assert!(!started_by_toast(["onyx://auth/callback?code=1"]));
        assert!(!started_by_toast(Vec::<&str>::new()));
    }

    #[test]
    fn a_toast_from_an_earlier_run_opens_nothing() {
        let answer = Answer { id: 1, epoch: 0 };
        let old = url::Url::parse(&answer_link(answer, 4)).unwrap();
        assert_eq!(linked_answer(&old, 5), None);
        // Still an answer link, so the main window does not open for it.
        assert!(is_answer_route(&old));
        let no_run = url::Url::parse("onyx://launcher/answer?answer=1&epoch=0").unwrap();
        assert_eq!(linked_answer(&no_run, 5), None);
    }

    #[test]
    fn a_toast_opens_its_link_when_clicked() {
        let xml = toast_xml(
            "Onyx <answered>",
            BODY,
            "onyx://launcher/answer?answer=1&epoch=2",
        );
        assert!(xml.starts_with(
            "<toast activationType=\"protocol\" launch=\"onyx://launcher/answer?answer=1&amp;epoch=2\">"
        ));
        assert!(xml.contains("<text>Onyx &lt;answered&gt;</text>"));
    }

    #[test]
    fn a_tap_carries_the_answer_and_its_session() {
        let both = serde_json::json!({ "answer": 3, "epoch": 1 });
        assert_eq!(
            tapped(&performed("tap", both.clone())),
            Some(Answer { id: 3, epoch: 1 })
        );
        assert_eq!(tapped(&performed("snooze", both)), None);
        assert_eq!(
            tapped(&performed("tap", serde_json::json!({ "answer": 3 }))),
            None
        );
        assert_eq!(tapped(&performed("tap", serde_json::json!({}))), None);
    }
}
