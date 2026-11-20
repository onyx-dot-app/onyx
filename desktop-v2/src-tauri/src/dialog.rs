//! Native message dialogs that never block the event loop.

use rfd::{MessageDialog, MessageDialogResult};
use tauri::AppHandle;

/// Dialog text that may hold server or user text. On Linux, rfd passes the
/// text to GTK as a printf format, so `%` must be escaped.
pub fn text(s: impl Into<String>) -> String {
    let s = s.into();
    if cfg!(target_os = "linux") {
        s.replace('%', "%%")
    } else {
        s
    }
}

/// Shows `dialog`, then calls `then` with the choice on the main thread.
///
/// AppKit dialogs must run on the main thread, so macOS shows it there. On
/// Linux, rfd runs the dialog on its own GTK thread and waits for it, which
/// deadlocks the event loop if the wait is on the main thread. Linux and
/// Windows wait on a worker thread instead.
pub fn show<F>(app: &AppHandle, dialog: MessageDialog, then: F)
where
    F: FnOnce(&AppHandle, MessageDialogResult) + Send + 'static,
{
    let app = app.clone();
    #[cfg(target_os = "macos")]
    {
        let handle = app.clone();
        let _ = handle.run_on_main_thread(move || {
            let choice = dialog.show();
            then(&app, choice);
        });
    }
    #[cfg(not(target_os = "macos"))]
    std::thread::spawn(move || {
        let choice = dialog.show();
        let handle = app.clone();
        let _ = handle.run_on_main_thread(move || then(&app, choice));
    });
}

#[cfg(test)]
mod tests {
    #[test]
    fn escapes_percent_only_on_linux() {
        let escaped = super::text("100% of %s");
        if cfg!(target_os = "linux") {
            assert_eq!(escaped, "100%% of %%s");
        } else {
            assert_eq!(escaped, "100% of %s");
        }
    }
}
