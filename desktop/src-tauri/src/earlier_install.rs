//! The earlier desktop app's per-user Windows install.
//!
//! The earlier app's setup program installed for the current user only
//! (uninstall entry in HKCU). The new installers do not remove it, and the
//! app never runs its uninstaller: the user can change that entry and its
//! files. The app takes `onyx://` over at launch (`main.rs`), and shows a
//! one-time notice that points to Settings > Apps.

#![cfg_attr(not(all(windows, not(debug_assertions))), allow(dead_code))]

pub const SETTINGS_APPS_URL: &str = "ms-settings:appsfeatures";
const OPEN_SETTINGS: &str = "Open Settings";

/// Whether an `UninstallString` belongs to another install than the one that
/// runs (`exe`): an `uninstall.exe` in another absolute folder. Windows
/// paths, as strings, so the rule is tested on every platform.
pub fn is_other_install(uninstall_string: &str, exe: &str) -> bool {
    let path = uninstall_string.trim().trim_matches('"');
    let Some((dir, name)) = path.rsplit_once(['\\', '/']) else {
        return false;
    };
    let absolute = dir.as_bytes().get(1..3) == Some(b":\\".as_slice()) || dir.starts_with(r"\\");
    let exe_dir = exe.rsplit_once(['\\', '/']).map(|(dir, _)| dir);
    let same_install = exe_dir.is_some_and(|exe_dir| exe_dir.eq_ignore_ascii_case(dir));
    name.eq_ignore_ascii_case("uninstall.exe") && absolute && !same_install
}

/// Whether to show the notice: the earlier install is there, and the notice
/// was not shown before.
pub fn shows_notice(earlier_present: bool, already_shown: bool) -> bool {
    earlier_present && !already_shown
}

#[cfg(all(windows, not(debug_assertions)))]
fn earlier_install_present(product_name: &str) -> bool {
    use winreg::enums::HKEY_CURRENT_USER;
    use winreg::RegKey;
    let key = format!(r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{product_name}");
    let Ok(uninstall) = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey(key)
        .and_then(|key| key.get_value::<String, _>("UninstallString"))
    else {
        return false;
    };
    std::env::current_exe().is_ok_and(|exe| is_other_install(&uninstall, &exe.to_string_lossy()))
}

/// Shows the notice once per user, without blocking the launch.
#[cfg(all(windows, not(debug_assertions)))]
pub fn notify_if_present(app: &tauri::AppHandle) {
    use tauri::Manager;
    use tauri_plugin_opener::OpenerExt;

    let state = app.state::<crate::state::AppState>();
    let shown = state
        .config
        .get()
        .earlier_install_notice_shown
        .unwrap_or(false);
    if !shows_notice(earlier_install_present(&app.package_info().name), shown) {
        return;
    }
    // Saved first, so a crash or a quit during the notice does not repeat it.
    if let Err(e) = state
        .config
        .update(|c| c.earlier_install_notice_shown = Some(true))
    {
        log::warn!("could not save the earlier-install notice: {e}");
    }
    log::info!("the earlier desktop app's per-user install is still present");
    let dialog = rfd::MessageDialog::new()
        .set_title("Remove the older Onyx")
        .set_description(crate::dialog::text(
            "An older version of Onyx is still installed. Remove it in Windows Settings > Apps.",
        ))
        .set_buttons(rfd::MessageButtons::OkCancelCustom(
            OPEN_SETTINGS.into(),
            "Not now".into(),
        ));
    crate::dialog::show(app, dialog, |app, choice| {
        if choice == rfd::MessageDialogResult::Custom(OPEN_SETTINGS.into()) {
            if let Err(e) = app.opener().open_url(SETTINGS_APPS_URL, None::<&str>) {
                log::warn!("could not open Settings > Apps: {e}");
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_notice_shows_once_for_an_earlier_install() {
        assert!(shows_notice(true, false));
        assert!(!shows_notice(true, true));
        assert!(!shows_notice(false, false));
        assert!(!shows_notice(false, true));
    }

    #[test]
    fn only_another_install_counts() {
        let exe = r"C:\Program Files\Onyx\onyx.exe";
        let earlier = r"C:\Users\a\AppData\Local\Onyx\uninstall.exe";
        assert!(is_other_install(&format!("\"{earlier}\""), exe));
        assert!(is_other_install(earlier, exe));
        assert!(!is_other_install(
            r#""C:\Program Files\Onyx\uninstall.exe""#,
            exe
        ));
        assert!(!is_other_install(
            r#""c:\program files\onyx\Uninstall.exe""#,
            exe
        ));
        assert!(!is_other_install(r#""C:\Users\a\evil.exe" /S"#, exe));
        assert!(!is_other_install(r"Onyx\uninstall.exe", exe));
        assert!(!is_other_install("uninstall.exe", exe));
        assert!(!is_other_install("", exe));
    }
}
