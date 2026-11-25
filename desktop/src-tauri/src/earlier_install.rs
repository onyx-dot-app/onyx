//! Retires the earlier desktop app's per-user Windows install.
//!
//! The earlier app's setup program installed for the current user only
//! (uninstall entry in HKCU). Its uninstaller ends every `onyx.exe` by name,
//! and its "Delete the application data" option deletes the data folders
//! that this app now uses (`app.onyx.desktop`). So the app never runs that
//! uninstaller, and makes sure nobody else can: at launch, as the user, it
//! deletes the uninstall entry first, then the earlier app's shortcuts and
//! program folder. Files that are in use stay, and a later launch tries
//! again (`Config::earlier_install_dir`).

#![cfg_attr(not(all(windows, not(debug_assertions))), allow(dead_code))]

use std::path::Path;

/// What one launch does, in this order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Step {
    /// Save the folder in config, for the retries.
    RecordFolder,
    /// Delete the HKCU uninstall entry: then nothing can start the earlier
    /// uninstaller from Settings or Control Panel.
    RemoveUninstallEntry,
    RemoveShortcuts,
    RemoveFolder,
}

/// The steps for a launch. `entry`: the uninstall entry names a plausible
/// earlier folder; `pending`: an earlier launch left files to delete.
pub fn plan(entry: bool, pending: bool) -> Vec<Step> {
    match (entry, pending) {
        (true, _) => vec![
            Step::RecordFolder,
            Step::RemoveUninstallEntry,
            Step::RemoveShortcuts,
            Step::RemoveFolder,
        ],
        (false, true) => vec![Step::RemoveShortcuts, Step::RemoveFolder],
        (false, false) => Vec::new(),
    }
}

/// The folder of the `uninstall.exe` that an `UninstallString` names.
/// Windows paths, as strings, so the rules are tested on every platform.
pub fn install_dir_of(uninstall_string: &str) -> Option<String> {
    let path = uninstall_string.trim().trim_matches('"');
    let (dir, name) = path.rsplit_once(['\\', '/'])?;
    name.eq_ignore_ascii_case("uninstall.exe")
        .then(|| dir.trim_end_matches(['\\', '/']).to_string())
}

fn components(path: &str) -> Vec<String> {
    path.split(['\\', '/'])
        .filter(|c| !c.is_empty())
        .map(str::to_lowercase)
        .collect()
}

/// Whether `inner` is `outer` or inside it.
fn is_within(inner: &str, outer: &str) -> bool {
    let (inner, outer) = (components(inner), components(outer));
    !outer.is_empty() && inner.len() >= outer.len() && inner[..outer.len()] == outer[..]
}

/// Whether `dir` may be deleted as the earlier app's program folder: a
/// folder on a drive (not the drive root) that is not this app's install
/// folder, not inside it, and neither holds nor is inside a `protected`
/// folder (the user profile, the AppData roots, this app's data folders).
pub fn plausible_earlier_folder(dir: &str, exe: &str, protected: &[String]) -> bool {
    let on_drive = dir.as_bytes().get(1..3) == Some(b":\\".as_slice());
    if !on_drive || components(dir).len() < 2 {
        return false;
    }
    let exe_dir = exe.rsplit_once(['\\', '/']).map_or("", |(dir, _)| dir);
    if is_within(dir, exe_dir) || is_within(exe_dir, dir) {
        return false;
    }
    !protected
        .iter()
        .any(|p| is_within(p, dir) || (p.contains("app.onyx.desktop") && is_within(dir, p)))
}

/// Whether a shortcut file names a target in `dir`. A `.lnk` file keeps the
/// target path as ANSI or UTF-16 text.
pub fn shortcut_points_into(lnk: &[u8], dir: &str) -> bool {
    let needle = format!("{}\\", dir.trim_end_matches('\\')).to_lowercase();
    let ansi = String::from_utf8_lossy(lnk).to_lowercase();
    if ansi.contains(&needle) {
        return true;
    }
    // UTF-16 text can start at an even or an odd offset.
    [0, 1].iter().any(|&start| {
        let units: Vec<u16> = lnk
            .get(start..)
            .unwrap_or_default()
            .as_chunks::<2>()
            .0
            .iter()
            .map(|pair| u16::from_le_bytes(*pair))
            .collect();
        String::from_utf16_lossy(&units)
            .to_lowercase()
            .contains(&needle)
    })
}

fn is_link(meta: &std::fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        // FILE_ATTRIBUTE_REPARSE_POINT: symbolic links and junctions.
        meta.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        meta.file_type().is_symlink()
    }
}

/// Whether a link is a directory link (removed with `remove_dir`).
fn link_is_dir(meta: &std::fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        // FILE_ATTRIBUTE_DIRECTORY: directory symbolic links and junctions.
        meta.file_attributes() & 0x10 != 0
    }
    #[cfg(not(windows))]
    {
        meta.is_dir()
    }
}

/// Deletes `path` and its contents without following links: a link inside
/// it is removed as a link, and a `path` that is a link is removed as a
/// link only. Returns whether `path` is gone; files in use stay.
pub fn remove_tree(path: &Path) -> bool {
    let Ok(meta) = std::fs::symlink_metadata(path) else {
        return !path.exists();
    };
    if is_link(&meta) {
        let removed = if link_is_dir(&meta) {
            std::fs::remove_dir(path)
        } else {
            std::fs::remove_file(path)
        };
        return removed.is_ok();
    }
    if !meta.is_dir() {
        return std::fs::remove_file(path).is_ok();
    }
    if let Ok(entries) = std::fs::read_dir(path) {
        for entry in entries.flatten() {
            remove_tree(&entry.path());
        }
    }
    std::fs::remove_dir(path).is_ok()
}

/// Whether this process runs with an elevated (administrator) token. Then
/// the user's folders are left alone: the user can replace them with links.
#[cfg(all(windows, not(debug_assertions)))]
fn elevated() -> bool {
    // SAFETY: no arguments; it only reads the process token.
    unsafe { windows::Win32::UI::Shell::IsUserAnAdmin().as_bool() }
}

#[cfg(all(windows, not(debug_assertions)))]
fn remove_shortcuts(dir: &str) {
    let mut candidates = Vec::new();
    if let Some(roaming) = std::env::var_os("APPDATA") {
        let programs = Path::new(&roaming).join(r"Microsoft\Windows\Start Menu\Programs");
        candidates.push(programs.join("Onyx.lnk"));
        candidates.push(programs.join(r"Onyx\Onyx.lnk"));
    }
    if let Some(profile) = std::env::var_os("USERPROFILE") {
        candidates.push(Path::new(&profile).join(r"Desktop\Onyx.lnk"));
    }
    for lnk in candidates {
        let Ok(bytes) = std::fs::read(&lnk) else {
            continue;
        };
        if !shortcut_points_into(&bytes, dir) {
            continue;
        }
        match std::fs::remove_file(&lnk) {
            Ok(()) => log::info!("deleted a shortcut of the earlier desktop app"),
            Err(e) => log::warn!("could not delete a shortcut of the earlier desktop app: {e}"),
        }
        if let Some(parent) = lnk.parent().filter(|p| p.ends_with("Onyx")) {
            let _ = std::fs::remove_dir(parent);
        }
    }
}

/// Runs at launch, after the config is loaded.
#[cfg(all(windows, not(debug_assertions)))]
pub fn retire(app: &tauri::AppHandle) {
    use tauri::Manager;
    use winreg::enums::HKEY_CURRENT_USER;
    use winreg::RegKey;

    if elevated() {
        return;
    }
    let state = app.state::<crate::state::AppState>();
    let key = format!(
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{}",
        app.package_info().name
    );
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    let exe = exe.to_string_lossy().into_owned();
    let protected: Vec<String> = ["USERPROFILE", "APPDATA", "LOCALAPPDATA"]
        .iter()
        .filter_map(std::env::var_os)
        .map(|p| p.to_string_lossy().into_owned())
        .chain(
            app.path()
                .app_config_dir()
                .ok()
                .map(|p| p.to_string_lossy().into_owned()),
        )
        .chain(
            app.path()
                .app_local_data_dir()
                .ok()
                .map(|p| p.to_string_lossy().into_owned()),
        )
        .collect();
    let from_entry = hkcu
        .open_subkey(&key)
        .and_then(|k| k.get_value::<String, _>("UninstallString"))
        .ok()
        .and_then(|s| install_dir_of(&s))
        .filter(|dir| {
            let ok = plausible_earlier_folder(dir, &exe, &protected);
            if !ok {
                log::warn!("the earlier desktop app's uninstall entry names an unexpected folder; left alone");
            }
            ok
        });
    let pending = state
        .config
        .get()
        .earlier_install_dir
        .filter(|dir| plausible_earlier_folder(dir, &exe, &protected));
    let Some(dir) = from_entry.clone().or(pending.clone()) else {
        return;
    };
    for step in plan(from_entry.is_some(), pending.is_some()) {
        match step {
            Step::RecordFolder => {
                if let Err(e) = state
                    .config
                    .update(|c| c.earlier_install_dir = Some(dir.clone()))
                {
                    log::warn!("could not record the earlier desktop app's folder: {e}");
                }
            }
            Step::RemoveUninstallEntry => match hkcu.delete_subkey_all(&key) {
                Ok(()) => log::info!("deleted the earlier desktop app's uninstall entry"),
                Err(e) => {
                    log::warn!("could not delete the earlier desktop app's uninstall entry: {e}");
                    return;
                }
            },
            Step::RemoveShortcuts => remove_shortcuts(&dir),
            Step::RemoveFolder => {
                if remove_tree(Path::new(&dir)) {
                    log::info!("deleted the earlier desktop app's program folder");
                    if let Err(e) = state.config.update(|c| c.earlier_install_dir = None) {
                        log::warn!("could not update the earlier desktop app's record: {e}");
                    }
                } else {
                    log::warn!(
                        "some files of the earlier desktop app are in use; the next launch tries again"
                    );
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const EXE: &str = r"C:\Program Files\Onyx\onyx.exe";

    fn protected() -> Vec<String> {
        [
            r"C:\Users\Ann O'Neil",
            r"C:\Users\Ann O'Neil\AppData\Roaming",
            r"C:\Users\Ann O'Neil\AppData\Local",
            r"C:\Users\Ann O'Neil\AppData\Roaming\app.onyx.desktop",
            r"C:\Users\Ann O'Neil\AppData\Local\app.onyx.desktop",
        ]
        .map(String::from)
        .to_vec()
    }

    #[test]
    fn the_uninstall_entry_comes_off_before_any_file() {
        assert_eq!(
            plan(true, false),
            [
                Step::RecordFolder,
                Step::RemoveUninstallEntry,
                Step::RemoveShortcuts,
                Step::RemoveFolder
            ]
        );
        assert_eq!(
            plan(false, true),
            [Step::RemoveShortcuts, Step::RemoveFolder]
        );
        assert!(plan(false, false).is_empty());
    }

    #[test]
    fn the_folder_comes_from_the_uninstall_string() {
        assert_eq!(
            install_dir_of(r#""C:\Users\Ann O'Neil\AppData\Local\Onyx\uninstall.exe""#).as_deref(),
            Some(r"C:\Users\Ann O'Neil\AppData\Local\Onyx")
        );
        assert_eq!(install_dir_of(r#""C:\a\evil.exe" /S"#), None);
        assert_eq!(install_dir_of("uninstall.exe"), None);
    }

    #[test]
    fn only_a_plausible_earlier_folder_is_deleted() {
        let p = protected();
        for ok in [
            r"C:\Users\Ann O'Neil\AppData\Local\Onyx",
            "C:\\Users\\Ann O\u{2019}Neil\\AppData\\Local\\Onyx",
            r"D:\Apps\Onyx",
        ] {
            assert!(plausible_earlier_folder(ok, EXE, &p), "{ok}");
        }
        for bad in [
            r"C:\Program Files\Onyx",
            r"C:\Program Files",
            r"C:\Program Files\Onyx\resources",
            r"C:\Users\Ann O'Neil",
            r"C:\Users\Ann O'Neil\AppData\Local",
            r"c:\users\ann o'neil\appdata\local\APP.ONYX.DESKTOP",
            r"C:\Users\Ann O'Neil\AppData\Local\app.onyx.desktop\EBWebView",
            r"C:\Users",
            r"C:\",
            r"\\server\share\Onyx",
            "Onyx",
        ] {
            assert!(!plausible_earlier_folder(bad, EXE, &p), "{bad}");
        }
    }

    #[test]
    fn a_shortcut_is_matched_by_its_target_folder() {
        let dir = r"C:\Users\Ann O'Neil\AppData\Local\Onyx";
        let utf16: Vec<u8> = r"C:\Users\Ann O'Neil\AppData\Local\Onyx\onyx.exe"
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect();
        assert!(shortcut_points_into(&utf16, dir));
        let mut odd = vec![0u8];
        odd.extend(&utf16);
        assert!(shortcut_points_into(&odd, dir));
        assert!(shortcut_points_into(
            b"x\0C:\\USERS\\ANN O'NEIL\\APPDATA\\LOCAL\\ONYX\\onyx.exe\0",
            dir
        ));
        assert!(!shortcut_points_into(
            b"C:\\Program Files\\Onyx\\onyx.exe",
            dir
        ));
        // A folder whose name only starts the same does not match.
        assert!(!shortcut_points_into(
            b"C:\\Users\\Ann O'Neil\\AppData\\Local\\Onyx2\\onyx.exe",
            dir
        ));
    }

    #[cfg(unix)]
    #[test]
    fn the_tree_delete_never_follows_links() {
        let root = std::env::temp_dir().join(format!("onyx-retire-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let program = root.join("Onyx");
        let outside = root.join("outside");
        std::fs::create_dir_all(program.join("resources")).unwrap();
        std::fs::create_dir_all(&outside).unwrap();
        std::fs::write(program.join("onyx.exe"), "").unwrap();
        std::fs::write(program.join("resources/a"), "").unwrap();
        std::fs::write(outside.join("keep"), "").unwrap();
        std::os::unix::fs::symlink(&outside, program.join("link")).unwrap();
        assert!(remove_tree(&program));
        assert!(!program.exists());
        assert!(outside.join("keep").exists());
        // A top-level link is removed as a link only.
        let top = root.join("top");
        std::os::unix::fs::symlink(&outside, &top).unwrap();
        assert!(remove_tree(&top));
        assert!(outside.join("keep").exists());
        std::fs::remove_dir_all(&root).unwrap();
    }
}
