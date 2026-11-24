//! Checks that the Windows installer files in `windows/` agree.

use base64::Engine;

/// The MSI runs `delete-user-data.ps1` as an `-EncodedCommand`: the script
/// as UTF-16LE, in base64.
#[test]
fn msi_runs_the_delete_user_data_script() {
    let script = include_str!("../windows/delete-user-data.ps1").replace('\r', "");
    let utf16: Vec<u8> = script.encode_utf16().flat_map(u16::to_le_bytes).collect();
    let encoded = base64::engine::general_purpose::STANDARD.encode(utf16);
    let wxs = include_str!("../windows/installer-guards.wxs");
    assert!(
        wxs.contains(&format!("-EncodedCommand {encoded}\"")),
        "installer-guards.wxs does not embed the current delete-user-data.ps1; encode it again"
    );
}

/// Runs `delete-user-data.ps1` in Windows PowerShell 5.1 on real junctions,
/// through `delete-user-data.test.ps1`.
#[cfg(windows)]
mod delete_user_data {
    use std::path::{Path, PathBuf};
    use std::process::Command;

    const APP: &str = "app.onyx.desktop";
    const USER_SID: &str = "S-1-5-21-1111111111-2222222222-3333333333-1001";

    fn run(name: &str, sid: &str, no_links: bool) -> PathBuf {
        let root = std::env::temp_dir().join(format!("onyx-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        let windows = Path::new(env!("CARGO_MANIFEST_DIR")).join("windows");
        let mut cmd = Command::new("powershell.exe");
        cmd.args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ])
        .arg(windows.join("delete-user-data.test.ps1"))
        .arg("-Script")
        .arg(windows.join("delete-user-data.ps1"))
        .arg("-Root")
        .arg(&root)
        .args(["-Sid", sid]);
        if no_links {
            cmd.arg("-NoLinks");
        }
        let out = cmd.output().unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        root
    }

    fn exists(path: &Path) -> bool {
        std::fs::symlink_metadata(path).is_ok()
    }

    fn is_link(path: &Path) -> bool {
        use std::os::windows::fs::MetadataExt;
        // FILE_ATTRIBUTE_REPARSE_POINT
        std::fs::symlink_metadata(path).is_ok_and(|m| m.file_attributes() & 0x400 != 0)
    }

    /// The `cmdkey.exe` arguments of each delete, from the test harness.
    fn deleted_credentials(root: &Path) -> Vec<String> {
        std::fs::read_to_string(root.join("deleted-credentials.txt"))
            .unwrap_or_default()
            .lines()
            .map(str::to_owned)
            .collect()
    }

    #[test]
    fn deletes_files_and_keeps_links_and_their_targets() {
        let root = run("dud-user", USER_SID, false);
        let roaming = root.join("Roaming").join(APP);
        assert!(!exists(&roaming.join("config.json")));
        assert!(!exists(&roaming.join("sub").join("deep")));
        assert!(is_link(&roaming.join("sub").join("link")));
        assert!(exists(&root.join("target-inner").join("keep.txt")));
        // A top-level link goes, as a link only.
        assert!(!exists(&root.join("Local").join(APP)));
        assert!(exists(&root.join("target-top").join("keep.txt")));
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn deletes_only_the_onyx_credentials() {
        let root = run("dud-creds", USER_SID, true);
        assert_eq!(
            deleted_credentials(&root),
            [
                "/delete:LegacyGeneric:target=https://onyx.example.com.app.onyx.desktop",
                "/delete:LegacyGeneric:target=http://localhost:8899.app.onyx.desktop",
            ]
        );
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn deletes_both_folders_without_links() {
        let root = run("dud-clean", USER_SID, true);
        assert!(!exists(&root.join("Roaming").join(APP)));
        assert!(!exists(&root.join("Local").join(APP)));
        assert!(exists(&root.join("Roaming")));
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn deletes_nothing_as_local_system() {
        let root = run("dud-system", "S-1-5-18", false);
        assert!(exists(&root.join("Roaming").join(APP).join("config.json")));
        assert!(exists(
            &root.join("Roaming").join(APP).join("sub").join("deep")
        ));
        assert!(is_link(&root.join("Local").join(APP)));
        assert!(deleted_credentials(&root).is_empty());
        std::fs::remove_dir_all(&root).unwrap();
    }
}
