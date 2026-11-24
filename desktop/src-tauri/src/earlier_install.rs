//! Removes the earlier desktop app's per-user Windows install.
//!
//! The earlier app's setup program installed for the current user only
//! (uninstall entry in HKCU). Left in place, it is a second "Onyx" in Apps
//! and claims onyx:// for the user. Its silent uninstall keeps its data, but
//! it ends every `onyx.exe` of the user by name, so it cannot run while this
//! app runs. The elevated installer never runs it: the user can change that
//! entry and its files.
//!
//! At the first launch, the app copies its own binary to
//! `%TEMP%\onyx-upgrade-helper-<random>.exe` (not named `onyx.exe`) and starts
//! it in helper mode (`--remove-earlier-install`). The helper writes a ready
//! file; the app exits only after it sees that file, else it stops the helper
//! and runs as normal. The helper waits for the app to exit, takes the
//! one-attempt marker, runs the uninstaller (bounded), then starts the app
//! again in every case.

#![cfg_attr(not(all(windows, not(debug_assertions))), allow(dead_code))]

use std::path::Path;
#[cfg(all(windows, not(debug_assertions)))]
use std::path::PathBuf;
use std::time::Duration;

pub const HELPER_FLAG: &str = "--remove-earlier-install";
const HELPER_PREFIX: &str = "onyx-upgrade-helper-";
/// The helper's file is kept this long, then a later launch deletes it.
const HELPER_MAX_AGE: Duration = Duration::from_secs(24 * 60 * 60);

/// What the helper needs, passed as separate command-line arguments.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HelperArgs {
    pub wait_pid: u32,
    pub uninstaller: String,
    pub install_dir: String,
    pub relaunch: String,
    pub ready: String,
    pub marker: String,
}

impl HelperArgs {
    pub fn to_args(&self) -> Vec<String> {
        vec![
            HELPER_FLAG.to_string(),
            "--wait-pid".to_string(),
            self.wait_pid.to_string(),
            "--uninstaller".to_string(),
            self.uninstaller.clone(),
            "--install-dir".to_string(),
            self.install_dir.clone(),
            "--relaunch".to_string(),
            self.relaunch.clone(),
            "--ready".to_string(),
            self.ready.clone(),
            "--marker".to_string(),
            self.marker.clone(),
        ]
    }

    /// The helper's arguments, from the process arguments without the
    /// program name. `None` when this is not a helper run.
    pub fn parse(args: &[String]) -> Option<Self> {
        let (flag, rest) = args.split_first()?;
        if flag != HELPER_FLAG || rest.len() % 2 != 0 {
            return None;
        }
        let mut pid = None;
        let (mut uninstaller, mut install_dir, mut relaunch, mut ready, mut marker) =
            (None, None, None, None, None);
        for pair in rest.chunks(2) {
            let value = pair[1].clone();
            match pair[0].as_str() {
                "--wait-pid" => pid = value.parse().ok(),
                "--uninstaller" => uninstaller = Some(value),
                "--install-dir" => install_dir = Some(value),
                "--relaunch" => relaunch = Some(value),
                "--ready" => ready = Some(value),
                "--marker" => marker = Some(value),
                _ => return None,
            }
        }
        Some(Self {
            wait_pid: pid?,
            uninstaller: uninstaller?,
            install_dir: install_dir?,
            relaunch: relaunch?,
            ready: ready?,
            marker: marker?,
        })
    }
}

/// The uninstaller of the earlier desktop app's per-user install, from its
/// `UninstallString`, if that install is not the one that runs (`exe`).
/// Windows paths, as strings, so the rule is tested on every platform.
pub fn earlier_user_uninstaller(uninstall_string: &str, exe: &str) -> Option<String> {
    let path = uninstall_string.trim().trim_matches('"');
    let (dir, name) = path.rsplit_once(['\\', '/'])?;
    let absolute = dir.as_bytes().get(1..3) == Some(b":\\".as_slice()) || dir.starts_with(r"\\");
    let exe_dir = exe.rsplit_once(['\\', '/']).map(|(dir, _)| dir);
    let same_install = exe_dir.is_some_and(|exe_dir| exe_dir.eq_ignore_ascii_case(dir));
    (name.eq_ignore_ascii_case("uninstall.exe") && absolute && !same_install)
        .then(|| path.to_string())
}

/// The end of the uninstaller's command line, after `/S`. NSIS wants
/// `_?=<dir>` last and unquoted, also with spaces: it then runs the
/// uninstaller in place, so waiting for the process covers the uninstall.
pub fn uninstaller_tail(install_dir: &str) -> String {
    format!("_?={install_dir}")
}

/// What the app does after it tried to start the helper.
#[derive(Debug, PartialEq, Eq)]
pub enum Handoff {
    /// The helper runs and wrote its ready file: exit so it can uninstall.
    Exit,
    /// No confirmed helper: stop it if it started, and run as normal. The
    /// marker stays free, so a later launch tries again.
    KeepRunning,
}

pub fn handoff(started: bool, ready: bool) -> Handoff {
    if started && ready {
        Handoff::Exit
    } else {
        Handoff::KeepRunning
    }
}

/// Takes the one-attempt marker. False when an attempt already started.
pub fn reserve_marker(marker: &Path) -> bool {
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(marker)
        .is_ok()
}

/// Whether a file in the temp folder is an old helper copy to delete.
pub fn is_stale_helper(file_name: &str, age: Duration) -> bool {
    file_name.starts_with(HELPER_PREFIX)
        && file_name.to_ascii_lowercase().ends_with(".exe")
        && age > HELPER_MAX_AGE
}

/// Deletes helper copies from earlier launches.
#[cfg(all(windows, not(debug_assertions)))]
fn remove_stale_helpers(temp: &Path) {
    let Ok(entries) = std::fs::read_dir(temp) else {
        return;
    };
    for entry in entries.flatten() {
        let age = entry
            .metadata()
            .and_then(|m| m.modified())
            .ok()
            .and_then(|modified| modified.elapsed().ok());
        let name = entry.file_name();
        if let (Some(age), Some(name)) = (age, name.to_str()) {
            if is_stale_helper(name, age) {
                let _ = std::fs::remove_file(entry.path());
            }
        }
    }
}

/// Starts the helper if the earlier per-user install is present. Returns
/// true only when the helper confirmed that it runs: this process must then
/// exit before it opens any window.
#[cfg(all(windows, not(debug_assertions)))]
pub fn hand_off(product_name: &str, identifier: &str) -> bool {
    use std::os::windows::process::CommandExt;
    use std::time::Instant;
    use winreg::enums::HKEY_CURRENT_USER;
    use winreg::RegKey;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    const DETACHED_PROCESS: u32 = 0x0000_0008;

    let temp = std::env::temp_dir();
    remove_stale_helpers(&temp);
    let key = format!(r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{product_name}");
    let Ok(uninstall) = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey(key)
        .and_then(|key| key.get_value::<String, _>("UninstallString"))
    else {
        return false;
    };
    let Ok(exe) = std::env::current_exe() else {
        return false;
    };
    let exe_str = exe.to_string_lossy().into_owned();
    let Some(uninstaller) = earlier_user_uninstaller(&uninstall, &exe_str) else {
        return false;
    };
    let Some((install_dir, _)) = uninstaller.rsplit_once(['\\', '/']) else {
        return false;
    };
    let Some(local) = std::env::var_os("LOCALAPPDATA") else {
        return false;
    };
    let marker_dir = PathBuf::from(local).join(identifier);
    let marker = marker_dir.join("earlier-uninstall-tried");
    if marker.exists() || std::fs::create_dir_all(&marker_dir).is_err() {
        return false;
    }
    let tag: u64 = rand::random();
    let helper = temp.join(format!("{HELPER_PREFIX}{tag:016x}.exe"));
    let ready = marker_dir.join(format!("earlier-uninstall-ready-{tag:016x}"));
    if std::fs::copy(&exe, &helper).is_err() {
        return false;
    }
    let args = HelperArgs {
        wait_pid: std::process::id(),
        uninstaller: uninstaller.clone(),
        install_dir: install_dir.to_string(),
        relaunch: exe_str,
        ready: ready.to_string_lossy().into_owned(),
        marker: marker.to_string_lossy().into_owned(),
    };
    let child = std::process::Command::new(&helper)
        .args(args.to_args())
        .creation_flags(CREATE_NO_WINDOW | DETACHED_PROCESS)
        .spawn();
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut seen = false;
    if child.is_ok() {
        while !seen && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(100));
            seen = ready.exists();
        }
    }
    let _ = std::fs::remove_file(&ready);
    match handoff(child.is_ok(), seen) {
        Handoff::Exit => true,
        Handoff::KeepRunning => {
            if let Ok(mut child) = child {
                let _ = child.kill();
                let _ = child.wait();
            }
            let _ = std::fs::remove_file(&helper);
            false
        }
    }
}

/// Whether the process `pid` ended within `timeout`.
#[cfg(all(windows, not(debug_assertions)))]
fn process_ended(pid: u32, timeout: Duration) -> bool {
    use windows::Win32::Foundation::{CloseHandle, WAIT_OBJECT_0};
    use windows::Win32::System::Threading::{
        OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE,
    };
    // SAFETY: the handle is checked, waited on and closed here only.
    unsafe {
        let Ok(handle) = OpenProcess(PROCESS_SYNCHRONIZE, false, pid) else {
            // The process is gone already.
            return true;
        };
        let millis = u32::try_from(timeout.as_millis()).unwrap_or(u32::MAX);
        let ended = WaitForSingleObject(handle, millis) == WAIT_OBJECT_0;
        let _ = CloseHandle(handle);
        ended
    }
}

/// The helper run. It shows no window and never initializes Tauri.
#[cfg(all(windows, not(debug_assertions)))]
pub fn run_helper(args: &HelperArgs) {
    use std::os::windows::process::CommandExt;
    use std::time::Instant;

    if std::fs::write(&args.ready, "").is_err() {
        return;
    }
    // The app exits once it sees the ready file. If it still runs, do nothing.
    if !process_ended(args.wait_pid, Duration::from_secs(60)) {
        return;
    }
    if reserve_marker(Path::new(&args.marker)) {
        let child = std::process::Command::new(&args.uninstaller)
            .arg("/S")
            .raw_arg(uninstaller_tail(&args.install_dir))
            .spawn();
        if let Ok(mut child) = child {
            let deadline = Instant::now() + Duration::from_secs(120);
            let status = loop {
                match child.try_wait() {
                    Ok(Some(status)) => break Some(status),
                    Ok(None) if Instant::now() < deadline => {
                        std::thread::sleep(Duration::from_millis(200));
                    }
                    _ => {
                        // Timed out: stop it, and wait until it has ended,
                        // so it cannot end the app that starts below.
                        let _ = child.kill();
                        let _ = child.wait();
                        break None;
                    }
                }
            };
            if status.is_some_and(|s| s.success()) {
                let _ = std::fs::remove_file(&args.uninstaller);
                let _ = std::fs::remove_dir(&args.install_dir);
            }
        }
    }
    let _ = std::process::Command::new(&args.relaunch).spawn();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(path: &str) -> HelperArgs {
        HelperArgs {
            wait_pid: 4242,
            uninstaller: format!(r"{path}\uninstall.exe"),
            install_dir: path.to_string(),
            relaunch: r"C:\Program Files\Onyx\onyx.exe".to_string(),
            ready: format!(r"{path}\ready"),
            marker: format!(r"{path}\marker"),
        }
    }

    #[test]
    fn helper_arguments_round_trip_with_spaces_and_apostrophes() {
        for path in [
            r"C:\Users\Ann Lee\AppData\Local\Onyx",
            r"C:\Users\Ann O'Neil\AppData\Local\Onyx",
            "C:\\Users\\Ann O\u{2019}Neil\\AppData\\Local\\Onyx",
        ] {
            let args = sample(path);
            assert_eq!(HelperArgs::parse(&args.to_args()), Some(args));
        }
    }

    #[test]
    fn other_arguments_are_not_a_helper_run() {
        assert_eq!(HelperArgs::parse(&[]), None);
        assert_eq!(
            HelperArgs::parse(&["onyx://auth/callback".to_string()]),
            None
        );
        let mut args = sample(r"C:\a").to_args();
        args.pop();
        assert_eq!(HelperArgs::parse(&args), None);
        let mut args = sample(r"C:\a").to_args();
        args[2] = "not a pid".to_string();
        assert_eq!(HelperArgs::parse(&args), None);
        let mut args = sample(r"C:\a").to_args();
        args[1] = "--unknown".to_string();
        assert_eq!(HelperArgs::parse(&args), None);
    }

    #[test]
    fn the_uninstaller_tail_is_last_and_unquoted() {
        assert_eq!(
            uninstaller_tail("C:\\Users\\Ann O\u{2019}Neil\\AppData\\Local\\Onyx"),
            "_?=C:\\Users\\Ann O\u{2019}Neil\\AppData\\Local\\Onyx"
        );
    }

    #[test]
    fn the_app_exits_only_for_a_confirmed_helper() {
        assert_eq!(handoff(true, true), Handoff::Exit);
        assert_eq!(handoff(true, false), Handoff::KeepRunning);
        assert_eq!(handoff(false, false), Handoff::KeepRunning);
    }

    #[test]
    fn the_marker_allows_one_attempt() {
        let dir = std::env::temp_dir().join(format!("onyx-marker-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let marker = dir.join("earlier-uninstall-tried");
        assert!(reserve_marker(&marker));
        assert!(!reserve_marker(&marker));
        // A launch whose hand-off failed never took it, so a later one can.
        std::fs::remove_file(&marker).unwrap();
        assert!(reserve_marker(&marker));
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn only_old_helper_copies_are_stale() {
        let day = Duration::from_secs(24 * 60 * 60);
        let old = day + Duration::from_secs(1);
        assert!(is_stale_helper("onyx-upgrade-helper-00ff.exe", old));
        assert!(is_stale_helper("onyx-upgrade-helper-00ff.EXE", old));
        assert!(!is_stale_helper(
            "onyx-upgrade-helper-00ff.exe",
            Duration::from_secs(60)
        ));
        assert!(!is_stale_helper("onyx.exe", old));
        assert!(!is_stale_helper("onyx-upgrade-helper-00ff.txt", old));
    }

    #[test]
    fn only_another_installs_uninstaller_is_run() {
        let exe = r"C:\Program Files\Onyx\onyx.exe";
        let earlier = r"C:\Users\a\AppData\Local\Onyx\uninstall.exe";
        assert_eq!(
            earlier_user_uninstaller(&format!("\"{earlier}\""), exe).as_deref(),
            Some(earlier)
        );
        assert_eq!(
            earlier_user_uninstaller(earlier, exe).as_deref(),
            Some(earlier)
        );
        assert_eq!(
            earlier_user_uninstaller(r#""C:\Program Files\Onyx\uninstall.exe""#, exe),
            None
        );
        assert_eq!(
            earlier_user_uninstaller(r#""c:\program files\onyx\Uninstall.exe""#, exe),
            None
        );
        assert_eq!(
            earlier_user_uninstaller(r#""C:\Users\a\evil.exe" /S"#, exe),
            None
        );
        assert_eq!(earlier_user_uninstaller(r"Onyx\uninstall.exe", exe), None);
        assert_eq!(earlier_user_uninstaller("uninstall.exe", exe), None);
        assert_eq!(earlier_user_uninstaller("", exe), None);
    }
}
