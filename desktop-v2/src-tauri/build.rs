// Declaring the commands makes each one require an explicit permission, so only the
// capabilities in capabilities/ can reach them.
const COMMANDS: &[&str] = &[
    "check_server",
    "save_server",
    "login",
    "get_prefs",
    "change_server",
    "sign_out",
    "open_external",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to run tauri-build");
}
