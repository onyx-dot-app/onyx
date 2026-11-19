//! Native notifications. Answers can take a minute, so when one finishes while
//! the launcher is hidden, a notification tells the user; clicking it shows the
//! launcher again, which still holds the answer. The notification never shows
//! the question or the answer: lock screens and notification history keep it.

use tauri::plugin::{PermissionState, Plugin, TauriPlugin};
use tauri::{AppHandle, Manager, Runtime};
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

pub fn init(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.notification().on_action(move |performed| {
        let Some(answer) = tapped(performed) else {
            return;
        };
        // A stale notification is ignored: the launcher no longer holds its
        // answer, and showing another chat would be wrong.
        crate::launcher::show(
            &handle,
            move |app| answer.is_current(&app.state::<AppState>()),
            crate::windows::route,
        );
    });
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
    if !should_notify(enabled(&state), answer.is_current(&state), || {
        crate::launcher::is_visible(app)
    }) || !permitted(app)
    {
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
    // Checked again: a sign-out or new chat during the checks above suppresses it.
    let shown = state.while_current(answer.epoch, || {
        if !crate::aonyx::is_latest_answer(answer.id) {
            return Ok(());
        }
        app.notification()
            .builder()
            .id((answer.id % i32::MAX as u64) as i32)
            .title(title)
            .body(body)
            .extra(ANSWER_KEY, answer.id)
            .extra(EPOCH_KEY, answer.epoch)
            .show()
    });
    if let Some(Err(e)) = shown {
        log::warn!("could not show the answer notification: {e}");
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
