// Declaring the commands makes each one require an explicit permission, so only the
// capabilities in capabilities/ can reach them.
const COMMANDS: &[&str] = &[
    "check_server",
    "save_server",
    "login",
    "get_auth_methods",
    "sign_in_with_sso",
    "get_prefs",
    "set_hotkey",
    "set_launch_at_login",
    "set_notify_answers",
    "change_server",
    "sign_out",
    "ask",
    "search",
    "open_chat_in_main",
    "open_external",
    "hide_launcher",
    "toggle_aonyx",
    "aonyx_clicked",
    "aonyx_menu",
    "get_offline_status",
    "retry_connection",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to run tauri-build");
}
