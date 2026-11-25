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

/// The files that the earlier app's setup program installed: its binary and
/// its uninstaller (it had no resources or sidecars), in delete order. The
/// uninstaller goes last, so it marks a folder that still needs a retry.
pub const EARLIER_FILES: [&str; 2] = ["onyx.exe", "uninstall.exe"];

/// Whether a folder entry is one of the earlier app's files.
pub fn is_earlier_file(name: &str) -> bool {
    EARLIER_FILES.iter().any(|f| f.eq_ignore_ascii_case(name))
}

/// Whether a folder (its entry names) still holds the earlier install: its
/// uninstaller is there.
pub fn still_earlier<'a>(names: impl IntoIterator<Item = &'a str>) -> bool {
    names
        .into_iter()
        .any(|name| name.eq_ignore_ascii_case("uninstall.exe"))
}

/// The earlier setup program's own key (`Software\<manufacturer>\<product>`,
/// default value = its install folder) and its parent. The earlier app had
/// no publisher, so Tauri used the second part of its bundle ID, "onyx".
pub fn manufacturer_keys(product_name: &str) -> (String, String) {
    (
        format!(r"Software\onyx\{product_name}"),
        r"Software\onyx".to_string(),
    )
}

/// Whether that key belongs to the earlier install in `dir`.
pub fn manufacturer_key_is_earlier(default_value: &str, dir: &str) -> bool {
    let value = default_value
        .trim()
        .trim_matches('"')
        .trim_end_matches(['\\', '/']);
    value.eq_ignore_ascii_case(dir.trim_end_matches(['\\', '/']))
}

#[cfg(all(windows, not(debug_assertions)))]
fn remove_manufacturer_key(hkcu: &winreg::RegKey, product_name: &str, dir: &str) {
    let (product_key, manufacturer_key) = manufacturer_keys(product_name);
    let belongs = hkcu
        .open_subkey(&product_key)
        .and_then(|k| k.get_value::<String, _>(""))
        .is_ok_and(|value| manufacturer_key_is_earlier(&value, dir));
    if !belongs {
        return;
    }
    match hkcu.delete_subkey_all(&product_key) {
        Ok(()) => log::info!("deleted the earlier desktop app's install-folder key"),
        Err(e) => log::warn!("could not delete the earlier desktop app's install-folder key: {e}"),
    }
    // The parent goes only when nothing else is in it.
    let empty = hkcu
        .open_subkey(&manufacturer_key)
        .is_ok_and(|k| k.enum_keys().next().is_none() && k.enum_values().next().is_none());
    if empty {
        let _ = hkcu.delete_subkey(&manufacturer_key);
    }
}

/// The identity of the earlier app's `uninstall.exe`: its size and last
/// write time.
pub fn file_identity(len: u64, modified_nanos: u128) -> String {
    format!("{len}:{modified_nanos}")
}

/// Whether a retry still targets the install that was recorded. A record
/// without an identity (from an earlier build) is not trusted.
pub fn same_install(recorded: Option<&str>, now: Option<&str>) -> bool {
    matches!((recorded, now), (Some(recorded), Some(now)) if recorded == now)
}

/// The identity of `dir`'s `uninstall.exe`, if it is a plain file.
fn uninstaller_identity(dir: &str) -> Option<String> {
    let meta = std::fs::symlink_metadata(Path::new(dir).join("uninstall.exe")).ok()?;
    if is_link(&meta) || !meta.is_file() {
        return None;
    }
    let modified = meta
        .modified()
        .ok()?
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_nanos();
    Some(file_identity(meta.len(), modified))
}

#[derive(Debug, PartialEq, Eq)]
pub enum Removal {
    /// The earlier app's files are gone (the folder too, if it was empty).
    Done,
    /// A file is in use: the next launch tries again.
    Retry,
    /// The folder is a link, or no longer holds the earlier install.
    NotEarlier,
}

/// Deletes the earlier app's files in `dir`, never anything else, and never
/// through a link: a listed name that is a link is removed as a link. The
/// folder goes only if it is empty then.
pub fn remove_earlier_files(dir: &Path) -> Removal {
    let meta = match std::fs::symlink_metadata(dir) {
        Ok(meta) => meta,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Removal::Done,
        Err(_) => return Removal::Retry,
    };
    if is_link(&meta) || !meta.is_dir() {
        return Removal::NotEarlier;
    }
    let names: Vec<String> = match std::fs::read_dir(dir) {
        Ok(entries) => entries
            .flatten()
            .filter_map(|e| e.file_name().to_str().map(str::to_string))
            .collect(),
        Err(_) => return Removal::Retry,
    };
    if !still_earlier(names.iter().map(String::as_str)) {
        return Removal::NotEarlier;
    }
    // The uninstaller last, so a folder that needs a retry still has it.
    let mut listed: Vec<&String> = names.iter().filter(|n| is_earlier_file(n)).collect();
    listed.sort_by_key(|n| n.eq_ignore_ascii_case("uninstall.exe"));
    for name in listed {
        let path = dir.join(name);
        let meta = match std::fs::symlink_metadata(&path) {
            Ok(meta) => meta,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
            // Not readable now: keep the record and try again later.
            Err(_) => return Removal::Retry,
        };
        let removed = if is_link(&meta) && link_is_dir(&meta) {
            std::fs::remove_dir(&path)
        } else if is_link(&meta) || meta.is_file() {
            std::fs::remove_file(&path)
        } else {
            // A folder with a listed name is not the earlier app's file.
            continue;
        };
        if removed.is_err() {
            return Removal::Retry;
        }
    }
    // Only an empty folder: anything else in it is not the earlier app's.
    let _ = std::fs::remove_dir(dir);
    Removal::Done
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
    let holds_uninstaller = |dir: &String| {
        std::fs::read_dir(dir).is_ok_and(|entries| {
            let names: Vec<String> = entries
                .flatten()
                .filter_map(|e| e.file_name().to_str().map(str::to_string))
                .collect();
            still_earlier(names.iter().map(String::as_str))
        })
    };
    let from_entry = hkcu
        .open_subkey(&key)
        .and_then(|k| k.get_value::<String, _>("UninstallString"))
        .ok()
        .and_then(|s| install_dir_of(&s))
        .filter(|dir| {
            let ok = plausible_earlier_folder(dir, &exe, &protected) && holds_uninstaller(dir);
            if !ok {
                log::warn!("the earlier desktop app's uninstall entry names an unexpected folder; left alone");
            }
            ok
        });
    let config = state.config.get();
    let pending = config
        .earlier_install_dir
        .filter(|dir| plausible_earlier_folder(dir, &exe, &protected));
    // A retry runs only for the same uninstall.exe that was recorded.
    if from_entry.is_none() {
        if let Some(dir) = &pending {
            let now = uninstaller_identity(dir);
            if !same_install(config.earlier_install_id.as_deref(), now.as_deref()) {
                log::warn!(
                    "the earlier desktop app's folder changed since it was recorded; left alone"
                );
                if let Err(e) = state.config.update(|c| {
                    c.earlier_install_dir = None;
                    c.earlier_install_id = None;
                }) {
                    log::warn!("could not update the earlier desktop app's record: {e}");
                }
                return;
            }
        }
    }
    let Some(dir) = from_entry.clone().or(pending.clone()) else {
        return;
    };
    for step in plan(from_entry.is_some(), pending.is_some()) {
        match step {
            Step::RecordFolder => {
                let Some(id) = uninstaller_identity(&dir) else {
                    log::warn!(
                        "the earlier desktop app's uninstaller is not a plain file; left alone"
                    );
                    return;
                };
                if let Err(e) = state.config.update(|c| {
                    c.earlier_install_dir = Some(dir.clone());
                    c.earlier_install_id = Some(id);
                }) {
                    // Without the record a failed delete has no retry, so
                    // the entry stays for the next launch to start from.
                    log::warn!("could not record the earlier desktop app's folder: {e}");
                    return;
                }
            }
            Step::RemoveUninstallEntry => match hkcu.delete_subkey_all(&key) {
                Ok(()) => {
                    log::info!("deleted the earlier desktop app's uninstall entry");
                    remove_manufacturer_key(&hkcu, &app.package_info().name, &dir);
                }
                Err(e) => {
                    log::warn!("could not delete the earlier desktop app's uninstall entry: {e}");
                    return;
                }
            },
            Step::RemoveShortcuts => remove_shortcuts(&dir),
            Step::RemoveFolder => match remove_earlier_files(Path::new(&dir)) {
                Removal::Retry => log::warn!(
                    "some files of the earlier desktop app are in use; the next launch tries again"
                ),
                outcome => {
                    if outcome == Removal::Done {
                        log::info!("deleted the earlier desktop app's files");
                    } else {
                        log::warn!(
                            "the earlier desktop app's folder no longer holds its install; left alone"
                        );
                    }
                    if let Err(e) = state.config.update(|c| {
                        c.earlier_install_dir = None;
                        c.earlier_install_id = None;
                    }) {
                        log::warn!("could not update the earlier desktop app's record: {e}");
                    }
                }
            },
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

    #[test]
    fn the_earlier_setup_key_is_matched_by_its_folder() {
        assert_eq!(
            manufacturer_keys("Onyx"),
            (
                r"Software\onyx\Onyx".to_string(),
                r"Software\onyx".to_string()
            )
        );
        let dir = r"C:\Users\Ann O'Neil\AppData\Local\Onyx";
        assert!(manufacturer_key_is_earlier(dir, dir));
        assert!(manufacturer_key_is_earlier(
            r"c:\users\ann o'neil\appdata\local\onyx\",
            dir
        ));
        assert!(manufacturer_key_is_earlier(&format!("\"{dir}\""), dir));
        assert!(!manufacturer_key_is_earlier(r"C:\Program Files\Onyx", dir));
        assert!(!manufacturer_key_is_earlier("", dir));
    }

    #[test]
    fn a_retry_needs_the_same_uninstaller() {
        let id = file_identity(1234, 1_700_000_000_000_000_000);
        assert!(same_install(Some(&id), Some(&id)));
        assert!(!same_install(
            Some(&id),
            Some(&file_identity(1235, 1_700_000_000_000_000_000))
        ));
        assert!(!same_install(Some(&id), Some(&file_identity(1234, 1))));
        // Missing file, or a record from a build without the identity.
        assert!(!same_install(Some(&id), None));
        assert!(!same_install(None, Some(&id)));
        assert!(!same_install(None, None));
    }

    #[test]
    fn only_the_earlier_apps_files_are_listed() {
        for name in ["onyx.exe", "ONYX.EXE", "uninstall.exe", "Uninstall.exe"] {
            assert!(is_earlier_file(name), "{name}");
        }
        for name in [
            "onyx.dll",
            "config.json",
            "EBWebView",
            "uninstall.exe.bak",
            "notes.txt",
        ] {
            assert!(!is_earlier_file(name), "{name}");
        }
        assert_eq!(EARLIER_FILES.last(), Some(&"uninstall.exe"));
    }

    #[test]
    fn a_folder_is_still_the_earlier_install_while_its_uninstaller_is_there() {
        assert!(still_earlier(["onyx.exe", "uninstall.exe"]));
        assert!(still_earlier(["Uninstall.exe"]));
        assert!(!still_earlier(["onyx.exe"]));
        assert!(!still_earlier(["other.exe", "data"]));
        assert!(!still_earlier([]));
    }

    #[cfg(unix)]
    #[test]
    fn only_listed_files_go_and_links_are_not_followed() {
        let root = std::env::temp_dir().join(format!("onyx-retire-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let program = root.join("Onyx");
        let outside = root.join("outside");
        std::fs::create_dir_all(program.join("resources")).unwrap();
        std::fs::create_dir_all(&outside).unwrap();
        std::fs::write(outside.join("onyx.exe"), "keep").unwrap();
        std::fs::write(program.join("uninstall.exe"), "").unwrap();
        std::fs::write(program.join("notes.txt"), "keep").unwrap();
        std::os::unix::fs::symlink(outside.join("onyx.exe"), program.join("onyx.exe")).unwrap();
        assert_eq!(remove_earlier_files(&program), Removal::Done);
        assert!(!program.join("uninstall.exe").exists());
        assert!(std::fs::symlink_metadata(program.join("onyx.exe")).is_err());
        assert!(outside.join("onyx.exe").exists());
        // Other files keep the folder.
        assert!(program.join("notes.txt").exists());
        assert!(program.join("resources").exists());
        // Without its uninstaller the folder is no longer the earlier install.
        assert_eq!(remove_earlier_files(&program), Removal::NotEarlier);
        // An empty earlier folder goes; a folder that is a link is left alone.
        let clean = root.join("Clean");
        std::fs::create_dir_all(&clean).unwrap();
        std::fs::write(clean.join("onyx.exe"), "").unwrap();
        std::fs::write(clean.join("uninstall.exe"), "").unwrap();
        assert_eq!(remove_earlier_files(&clean), Removal::Done);
        assert!(!clean.exists());
        let linked = root.join("Linked");
        std::fs::write(outside.join("uninstall.exe"), "keep").unwrap();
        std::os::unix::fs::symlink(&outside, &linked).unwrap();
        assert_eq!(remove_earlier_files(&linked), Removal::NotEarlier);
        assert!(outside.join("uninstall.exe").exists());
        assert_eq!(remove_earlier_files(&root.join("Gone")), Removal::Done);
        std::fs::remove_dir_all(&root).unwrap();
    }
}
