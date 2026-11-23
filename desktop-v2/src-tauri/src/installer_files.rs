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
        wxs.contains(&format!("-EncodedCommand {encoded}'")),
        "installer-guards.wxs does not embed the current delete-user-data.ps1; encode it again"
    );
}
