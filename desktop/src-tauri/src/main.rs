// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod alt_menu;
mod commands;
mod config;
mod debug_log;
mod menu;
mod window;

use config::ConfigState;
use serde::Deserialize;
use tauri::{webview::PageLoadPayload, Manager, Webview, Wry};
#[cfg(target_os = "macos")]
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};

// ============================================================================
// Version
// ============================================================================

#[derive(Deserialize)]
struct VersionResponse {
    backend_version: String,
}

/// Whether the process was launched with `--version` / `-v`.
fn wants_version() -> bool {
    std::env::args().any(|arg| arg == "--version" || arg == "-v")
}

/// Fetch the backend version from the configured server's public `/api/version`
/// endpoint. `Ok(None)` means the server answered but reported no version.
fn fetch_server_version(server_url: &str) -> Result<Option<String>, String> {
    let url = format!("{}/api/version", server_url.trim_end_matches('/'));

    tauri::async_runtime::block_on(async move {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .map_err(|e| e.to_string())?;
        let resp = client
            .get(&url)
            .send()
            .await
            .map_err(|e| e.to_string())?
            .error_for_status()
            .map_err(|e| e.to_string())?;
        let text = resp.text().await.map_err(|e| e.to_string())?;
        let body: VersionResponse = serde_json::from_str(&text).map_err(|e| e.to_string())?;
        if body.backend_version.trim().is_empty() {
            Ok(None)
        } else {
            Ok(Some(body.backend_version))
        }
    })
}

/// Print client and (if reachable) server version, mirroring the CLI's
/// `--version` output.
fn print_version_info() {
    println!("Client version: {}", env!("CARGO_PKG_VERSION"));

    let (config, _) = config::load_config();
    let server_url = config.server_url;

    match fetch_server_version(&server_url) {
        Ok(Some(version)) => println!("Server version: {}", version),
        Ok(None) => println!(
            "Server version: unknown (empty response from {})",
            server_url
        ),
        Err(_) => println!(
            "Server version: unknown (could not fetch from {})",
            server_url
        ),
    }
}

// ============================================================================
// Main
// ============================================================================

fn main() {
    if wants_version() {
        print_version_info();
        return;
    }

    let (app_config, config_initialized) = config::load_config();
    let debug_mode = debug_log::is_debug_mode();

    let debug_log_file = if debug_mode {
        eprintln!("[ONYX DEBUG] Debug mode enabled");
        if let Some(path) = debug_log::get_debug_log_path() {
            eprintln!("[ONYX DEBUG] Frontend logs: {}", path.display());
        }
        eprintln!("[ONYX DEBUG] DevTools will open automatically");
        eprintln!("[ONYX DEBUG] Capturing console.log/warn/error/info/debug from webview");
        debug_log::init_debug_log_file()
    } else {
        None
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri::plugin::Builder::<Wry>::new("chat-external-navigation-handler")
                .on_navigation(|webview, destination_url| {
                    let Ok(current_url) = webview.url() else {
                        return true;
                    };

                    if window::should_open_in_external_browser(&current_url, destination_url) {
                        if !window::open_in_default_browser(destination_url.as_str()) {
                            eprintln!(
                                "Failed to open external URL in default browser: {}",
                                destination_url
                            );
                        }
                        return false;
                    }

                    true
                })
                .build(),
        )
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .manage(ConfigState::new(
            app_config,
            config_initialized,
            debug_mode,
            debug_log_file,
        ))
        .invoke_handler(tauri::generate_handler![
            commands::get_server_url,
            commands::get_bootstrap_state,
            commands::set_server_url,
            commands::get_config_path_cmd,
            commands::check_server_reachable,
            commands::open_in_browser,
            commands::open_config_file,
            commands::open_config_directory,
            commands::navigate_to,
            commands::reload_page,
            commands::go_back,
            commands::go_forward,
            commands::new_window,
            commands::reset_config,
            commands::start_drag_window,
            commands::toggle_menu_bar,
            debug_log::log_from_frontend
        ])
        .on_menu_event(|app, event| match event.id().as_ref() {
            menu::MENU_OPEN_DOCS_ID => window::open_docs(app),
            menu::MENU_NEW_CHAT_ID => window::trigger_new_chat(app),
            menu::MENU_NEW_WINDOW_ID => window::trigger_new_window(app),
            menu::MENU_OPEN_SETTINGS_ID => window::open_settings(app),
            menu::MENU_SHOW_MENU_BAR_ID => menu::handle_menu_bar_toggle(app),
            #[cfg(target_os = "linux")]
            menu::MENU_HIDE_DECORATIONS_ID => menu::handle_decorations_toggle(app),
            debug_log::MENU_TOGGLE_DEVTOOLS_ID => debug_log::handle_toggle_devtools(app),
            debug_log::MENU_OPEN_DEBUG_LOG_ID => debug_log::handle_open_debug_log(),
            _ => {}
        })
        .setup(move |app| {
            let app_handle = app.handle().clone();

            if let Err(e) = menu::setup_app_menu(&app_handle) {
                debug_log::log_backend_error(&app_handle, &format!("Failed to setup menu: {e}"));
            }

            if let Err(e) = menu::setup_tray_icon(&app_handle) {
                debug_log::log_backend_error(
                    &app_handle,
                    &format!("Failed to setup tray icon: {e}"),
                );
            }

            if let Some(window) = app.get_webview_window("main") {
                #[cfg(target_os = "macos")]
                if let Err(e) = apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None)
                {
                    debug_log::log_backend_error(
                        &app_handle,
                        &format!("Failed to apply vibrancy effect: {e}"),
                    );
                }

                if let Ok(url) = window.url() {
                    let mut base_url = url;
                    base_url.set_query(None);
                    base_url.set_fragment(None);
                    base_url.set_path("/");
                    app.state::<ConfigState>().set_app_base_url(Some(base_url));
                }

                #[cfg(target_os = "macos")]
                window::inject_titlebar(window.clone());

                window::apply_settings_to_window(&app_handle, &window);

                #[cfg(target_os = "linux")]
                alt_menu::setup_alt_menu_toggle(&app_handle, &window);

                debug_log::maybe_open_devtools(&app_handle, &window);

                if let Err(e) = window.set_focus() {
                    debug_log::log_backend_error(
                        &app_handle,
                        &format!("Failed to focus main window: {e}"),
                    );
                }
            }

            Ok(())
        })
        .on_page_load(|webview: &Webview, _payload: &PageLoadPayload| {
            window::inject_chat_link_intercept(webview);

            if webview.app_handle().state::<ConfigState>().debug_mode {
                debug_log::inject_console_capture(webview);
            }

            #[cfg(target_os = "macos")]
            window::eval_titlebar_script(webview);

            #[cfg(target_os = "windows")]
            alt_menu::inject_alt_menu_script(webview);
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
