//! Native notifications. Answers can take a minute, so when one finishes while
//! the launcher is hidden, a notification tells the user; clicking it shows the
//! launcher again, which still holds the answer.

use tauri::plugin::PermissionState;
use tauri::{AppHandle, Manager};
use tauri_plugin_notification::NotificationExt;

use crate::state::AppState;

/// Longest notification body, in characters.
const BODY_CHARS: usize = 120;

pub fn init(app: &AppHandle) {
    let handle = app.clone();
    // Desktop reports a click on the notification itself as "tap".
    let _ = app.notification().on_action(move |performed| {
        if performed.action_id() == "tap" {
            crate::launcher::show(&handle, crate::windows::route);
        }
    });
}

/// How a launcher answer ended.
pub enum Outcome {
    Answered,
    NeedsApproval,
    Failed,
}

/// Called when launcher answer `id` for `question` has ended.
pub fn answer_finished(app: &AppHandle, id: u64, question: &str, outcome: Outcome) {
    let enabled = app.state::<AppState>().config.get().notify_answers();
    let latest = crate::aonyx::is_latest_answer(id);
    if !should_notify(enabled, latest, || crate::launcher::is_visible(app)) || !permitted(app) {
        return;
    }
    let title = match outcome {
        Outcome::Answered => "Onyx answered",
        Outcome::NeedsApproval => "Onyx needs your approval",
        Outcome::Failed => "Onyx couldn't answer",
    };
    let result = app
        .notification()
        .builder()
        .id((id % i32::MAX as u64) as i32)
        .title(title)
        .body(summary(question, BODY_CHARS))
        .show();
    if let Err(e) = result {
        log::warn!("could not show the answer notification: {e}");
    }
}

/// Only the latest answer notifies, and only while the launcher is hidden.
fn should_notify(enabled: bool, latest: bool, launcher_visible: impl FnOnce() -> bool) -> bool {
    enabled && latest && !launcher_visible()
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

/// `text` on one line, cut to at most `max` characters.
fn summary(text: &str, max: usize) -> String {
    let line = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if line.chars().count() <= max {
        return line;
    }
    let cut: String = line.chars().take(max.saturating_sub(1)).collect();
    format!("{}…", cut.trim_end())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summary_keeps_a_short_question() {
        assert_eq!(
            summary("What is our PTO policy?", 120),
            "What is our PTO policy?"
        );
    }

    #[test]
    fn summary_puts_the_question_on_one_line() {
        assert_eq!(
            summary("  first\n\nsecond\tthird ", 120),
            "first second third"
        );
    }

    #[test]
    fn summary_cuts_a_long_question() {
        assert_eq!(summary("abcde fghij", 8), "abcde f…");
        // No space before the ellipsis.
        assert_eq!(summary("abcde fghij", 7), "abcde…");
        assert_eq!(summary("ééééé", 3), "éé…");
    }

    #[test]
    fn only_the_latest_answer_notifies_while_the_launcher_is_hidden() {
        assert!(should_notify(true, true, || false));
        assert!(!should_notify(true, true, || true));
        assert!(!should_notify(true, false, || false));
        assert!(!should_notify(false, true, || false));
    }
}
