#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod api;
mod commands;
mod config;
#[cfg(target_os = "macos")]
mod macos_cookies;
#[cfg(target_os = "macos")]
mod macos_dialogs;
mod main_window;
mod menu;
mod session_store;
mod state;
mod windows;

use tauri::{Manager, RunEvent};

use crate::config::ConfigStore;
use crate::state::AppState;

fn main() {
    let builder = tauri::Builder::default()
        // Must come first: a second launch hands over to the running instance.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            windows::show_primary(app);
        }))
        .plugin(tauri_plugin_opener::init())
        // Remember the main window's size and position; small windows stay centred.
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_denylist(&["onboarding", "login", "preferences"])
                .build(),
        );
    let app = builder
        .setup(|app| {
            let config_path = app.path().app_config_dir()?.join("config.json");
            app.manage(AppState::new(ConfigStore::load(config_path)));

            let handle = app.handle();

            app.set_menu(menu::build(handle)?)?;
            app.on_menu_event(|app, event| menu::handle(app, event.id().as_ref()));
            menu::build_tray(handle)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::check_server,
            commands::save_server,
            commands::login,
            commands::get_prefs,
            commands::change_server,
            commands::sign_out,
            commands::open_external,
        ])
        .build(tauri::generate_context!())
        .expect("error while building the Onyx desktop app");

    app.run(|app, event| match event {
        // After setup, so a fast server cannot race window creation ahead of
        // the event loop.
        RunEvent::Ready => windows::route(app),
        // Closing the last window keeps the app in the tray; Quit passes an exit code.
        RunEvent::ExitRequested {
            api, code: None, ..
        } => api.prevent_exit(),
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => windows::show_primary(app),
        _ => {}
    });
}
