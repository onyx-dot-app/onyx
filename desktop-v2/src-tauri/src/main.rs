#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod api;
mod ask;
mod commands;
mod config;
mod launcher;
#[cfg(target_os = "macos")]
mod macos_cookies;
#[cfg(target_os = "macos")]
mod macos_dialogs;
mod main_window;
mod menu;
mod session_store;
mod shortcut;
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
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_opener::init())
        // Remember the main window's size and position; small windows stay centred.
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_denylist(&["onboarding", "login", "preferences", "launcher"])
                .build(),
        );
    // Launcher as a non-activating NSPanel (see launcher.rs); macOS only.
    #[cfg(target_os = "macos")]
    let builder = builder.plugin(tauri_nspanel::init());
    let app = builder
        .setup(|app| {
            let config_path = app.path().app_config_dir()?.join("config.json");
            app.manage(AppState::new(ConfigStore::load(config_path)));

            let handle = app.handle();

            app.set_menu(menu::build(handle)?)?;
            app.on_menu_event(|app, event| menu::handle(app, event.id().as_ref()));
            menu::build_tray(handle)?;

            let hotkey = app.state::<AppState>().config.get().hotkey();
            if let Err(e) = shortcut::register(handle, &hotkey) {
                log::warn!("{e}");
            }
            launcher::preload(handle);

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::check_server,
            commands::save_server,
            commands::login,
            commands::get_prefs,
            commands::set_hotkey,
            commands::change_server,
            commands::sign_out,
            commands::ask,
            commands::search,
            commands::open_chat_in_main,
            commands::open_external,
            commands::hide_launcher,
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
