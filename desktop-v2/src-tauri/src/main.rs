#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod aonyx;
mod api;
mod ask;
mod commands;
mod config;
mod dialog;
mod launcher;
mod login_item;
#[cfg(target_os = "macos")]
mod macos_cookies;
#[cfg(target_os = "macos")]
mod macos_dialogs;
mod main_window;
mod menu;
mod notify;
mod offline;
mod policy;
mod qa;
mod reachability;
mod revocation;
mod session_store;
mod shortcut;
mod sso;
mod state;
mod updater;
mod windows;

use std::sync::atomic::{AtomicI32, Ordering};

use tauri::{Manager, RunEvent};

use crate::config::ConfigStore;
use crate::state::AppState;

/// The code the last allowed exit request asked for.
static EXIT_CODE: AtomicI32 = AtomicI32::new(0);

/// Ends the process before Tauri's teardown. The teardown destroys every
/// window, and destroying an NSPanel (the launcher, Aonyx) raises an AppKit
/// exception that aborts the app. Plugins have already seen `Exit` and saved
/// their state (window positions); app settings are saved when they change.
#[cfg(target_os = "macos")]
fn exit_now(app: &tauri::AppHandle) -> ! {
    aonyx::save_pending_position(app);
    // Removes the tray icon and releases resources such as the single-instance socket.
    app.cleanup_before_exit();
    let code = EXIT_CODE.load(Ordering::SeqCst);
    if code == tauri::RESTART_EXIT_CODE {
        tauri::process::restart(&app.env());
    }
    std::process::exit(code)
}

fn main() {
    let builder = tauri::Builder::default()
        // Must come first: a second launch (or an onyx:// link that starts
        // the app) hands its URL to the running instance and exits.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            windows::show_primary(app);
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_opener::init())
        .plugin(notify::plugin())
        // Remember the main window's size and position; small windows stay centred.
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_denylist(&["onboarding", "login", "preferences", "launcher", "offline"])
                .build(),
        );
    // Launcher as a non-activating NSPanel (see launcher.rs); macOS only.
    #[cfg(target_os = "macos")]
    let builder = builder.plugin(tauri_nspanel::init());
    // Launch at login on macOS (login_item.rs).
    #[cfg(target_os = "macos")]
    let builder = builder.plugin(tauri_plugin_autostart::Builder::new().build());
    let app = builder
        .setup(|app| {
            let config_path = app.path().app_config_dir()?.join("config.json");
            app.manage(offline::Offline::default());
            let handle = app.handle();
            let policy = policy::read(handle);
            policy::apply_launch_at_login(handle, &policy);
            app.manage(AppState::new(ConfigStore::load(config_path), policy));

            // Windows and Linux: the main window gets its own menu (main_window.rs).
            #[cfg(target_os = "macos")]
            app.set_menu(menu::build(handle)?)?;
            app.on_menu_event(|app, event| menu::handle(app, event.id().as_ref()));
            menu::build_tray(handle)?;

            policy::sync_hotkey(handle);
            if app.state::<AppState>().hotkey().is_some() {
                launcher::preload(handle);
            }
            policy::spawn_refresh(handle);
            notify::init(handle);

            {
                use tauri_plugin_deep_link::DeepLinkExt;
                // The NSIS and MSI installers register onyx:// for all users;
                // a per-user entry would override it. AppImage and dev builds
                // need it at runtime.
                #[cfg(any(target_os = "linux", all(target_os = "windows", debug_assertions)))]
                if let Err(e) = app.deep_link().register_all() {
                    log::warn!("could not register onyx:// links: {e}");
                }
                let link_app = handle.clone();
                app.deep_link().on_open_url(move |event| {
                    for url in event.urls() {
                        sso::handle_callback(&link_app, &url);
                    }
                });
            }

            main_window::spawn_session_renewal(handle);
            if updater::SUPPORTED {
                updater::spawn_background_checks(handle);
            }
            qa::start(handle);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::check_server,
            commands::save_server,
            commands::login,
            commands::get_auth_methods,
            commands::sign_in_with_sso,
            commands::get_prefs,
            commands::set_hotkey,
            commands::set_launch_at_login,
            commands::set_notify_answers,
            commands::discard_answer,
            commands::change_server,
            commands::sign_out,
            commands::ask,
            commands::search,
            commands::list_agents,
            commands::set_launcher_agent,
            commands::upload_file,
            commands::get_upload_limit,
            commands::cancel_upload,
            commands::delete_user_file,
            commands::open_chat_in_main,
            commands::open_external,
            commands::hide_launcher,
            commands::toggle_aonyx,
            commands::aonyx_clicked,
            commands::aonyx_menu,
            commands::get_offline_status,
            commands::retry_connection,
        ])
        .build(tauri::generate_context!())
        .expect("error while building the Onyx desktop app");

    app.run(|app, event| match event {
        // After setup, so a fast server cannot race window creation ahead of
        // the event loop.
        RunEvent::Ready => {
            windows::route(app);
            // Showing a panel during setup, before AppKit has finished
            // launching, raises an exception.
            aonyx::restore(app);
        }
        // Closing the last window keeps the app in the tray; Quit passes an exit code.
        RunEvent::ExitRequested {
            api, code: None, ..
        } => api.prevent_exit(),
        RunEvent::ExitRequested {
            code: Some(code), ..
        } => EXIT_CODE.store(code, Ordering::SeqCst),
        // Every quit ends here: the Quit menu item, a Dock or Apple Event
        // quit, `app.exit` and a restart from another thread.
        #[cfg(target_os = "macos")]
        RunEvent::Exit => exit_now(app),
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => windows::show_primary(app),
        _ => {}
    });
}
