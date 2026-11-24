#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod aonyx;
mod api;
mod ask;
mod commands;
mod config;
mod dialog;
mod earlier_install;
#[cfg(test)]
mod installer_files;
mod launcher;
#[cfg(any(target_os = "linux", test))]
mod linux_cookies;
mod login_item;
#[cfg(target_os = "macos")]
mod macos_cookies;
#[cfg(target_os = "macos")]
mod macos_dialogs;
mod main_window;
mod menu;
mod migration;
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

/// The app cannot talk to any server without its HTTP client, so it tells
/// the user why and quits.
fn startup_failed(error: &str) -> ! {
    let text = format!(
        "Onyx could not start secure connections: {error}\n\nCheck this computer's TLS \
         settings (for example, OPENSSL_CONF), or contact your IT team."
    );
    eprintln!("{text}");
    rfd::MessageDialog::new()
        .set_level(rfd::MessageLevel::Error)
        .set_title("Onyx could not start")
        .set_description(dialog::text(text))
        .show();
    std::process::exit(1)
}

/// Writes `log` records to `onyx.log` in the app's log directory. The file
/// rotates at 1 MB and four older files are kept. The app runs without a log
/// file if the directory cannot be used.
fn init_logging(app: &tauri::AppHandle) {
    use tauri_plugin_log::{RotationStrategy, Target, TargetKind};
    let builder = tauri_plugin_log::Builder::new()
        .clear_targets()
        .target(Target::new(TargetKind::LogDir {
            file_name: Some("onyx".into()),
        }))
        .level(log::LevelFilter::Info)
        .max_file_size(1_000_000)
        .rotation_strategy(RotationStrategy::KeepSome(4));
    #[cfg(debug_assertions)]
    let builder = builder.target(Target::new(TargetKind::Stderr));
    // Only the logger: the plugin's commands stay unregistered.
    match builder.split(app) {
        Ok((_plugin, level, logger)) => {
            if let Err(e) = tauri_plugin_log::attach_logger(level, logger) {
                eprintln!("could not start logging: {e}");
            }
        }
        Err(e) => eprintln!("could not open the log file: {e}"),
    }
}

/// Whether onyx:// needs a per-user handler at runtime. A .deb or .rpm
/// install (in /usr/bin) declares the scheme in its system desktop file, and
/// a per-user handler would outlive the package.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn registers_links_at_runtime(appimage: bool, exe: &std::path::Path) -> bool {
    appimage || exe.parent() != Some(std::path::Path::new("/usr/bin"))
}

/// The package's desktop file: the bundler names it after the product name.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn packaged_desktop_file(product_name: &str) -> String {
    format!("{product_name}.desktop")
}

/// The per-user handler that tauri-plugin-deep-link writes for this binary.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn legacy_link_handler(
    data_dir: &std::path::Path,
    exe: &std::path::Path,
) -> Option<std::path::PathBuf> {
    let name = exe.file_name()?.to_str()?;
    Some(
        data_dir
            .join("applications")
            .join(format!("{name}-handler.desktop")),
    )
}

/// Whether a desktop file's `Exec` value runs an Onyx program (`onyx`,
/// `Onyx_amd64.AppImage`, ...), quoted or not.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn runs_onyx(exec: &str) -> bool {
    let exec = exec.trim_start();
    let program = match exec.strip_prefix('"') {
        Some(rest) => rest.split('"').next().unwrap_or_default(),
        None => exec.split_whitespace().next().unwrap_or_default(),
    };
    std::path::Path::new(program)
        .file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.to_ascii_lowercase().starts_with("onyx"))
}

/// Whether a handler file is the plugin's onyx:// entry: a hidden entry that
/// runs an Onyx program with a link and handles no MIME type other than
/// onyx://.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn is_onyx_link_handler(contents: &str) -> bool {
    let mut in_entry = false;
    let (mut hidden, mut exec, mut other_types) = (false, false, false);
    for line in contents.lines().map(str::trim) {
        if line.starts_with('[') {
            in_entry = line == "[Desktop Entry]";
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        if !in_entry {
            continue;
        }
        match key.trim() {
            "NoDisplay" => hidden = value.trim() == "true",
            "Exec" => exec = value.trim_end().ends_with(" %u") && runs_onyx(value),
            "MimeType" => {
                other_types = value
                    .split(';')
                    .map(str::trim)
                    .any(|t| !t.is_empty() && t != "x-scheme-handler/onyx")
            }
            _ => {}
        }
    }
    hidden && exec && !other_types
}

/// Whether a per-user `onyx://` command starts a program other than `exe`.
/// The earlier desktop app wrote such an entry at each launch, and a
/// per-user entry wins over the one the installers write for all users.
#[cfg_attr(not(all(windows, not(debug_assertions))), allow(dead_code))]
fn link_command_is_other_program(command: &str, exe: &std::path::Path) -> bool {
    let command = command.trim_start();
    let program = match command.strip_prefix('"') {
        Some(rest) => rest.split('"').next().unwrap_or_default(),
        None => command.split_whitespace().next().unwrap_or_default(),
    };
    !program.eq_ignore_ascii_case(&exe.to_string_lossy())
}

/// Takes onyx:// back from another program (`when`: for the log). Runs at
/// launch and before each browser sign-in: the earlier desktop app, while it
/// is still installed, writes its own entry each time it starts.
#[cfg(all(windows, not(debug_assertions)))]
fn remove_other_user_link_handler(when: &str) {
    use winreg::enums::HKEY_CURRENT_USER;
    use winreg::RegKey;
    const KEY: &str = r"Software\Classes\onyx";
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    let Ok(command) = hkcu
        .open_subkey(format!(r"{KEY}\shell\open\command"))
        .and_then(|key| key.get_value::<String, _>(""))
    else {
        return;
    };
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    if !link_command_is_other_program(&command, &exe) {
        return;
    }
    match hkcu.delete_subkey_all(KEY) {
        Ok(()) => log::info!("deleted a per-user onyx:// entry for another program ({when})"),
        Err(e) => log::warn!("could not delete the per-user onyx:// entry: {e}"),
    }
}

#[cfg(target_os = "linux")]
fn register_links(app: &tauri::AppHandle) {
    use tauri_plugin_deep_link::DeepLinkExt;
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    if registers_links_at_runtime(app.env().appimage.is_some(), &exe) {
        if let Err(e) = app.deep_link().register_all() {
            log::warn!("could not register onyx:// links: {e}");
        }
        return;
    }
    // Removes a handler that earlier versions wrote for this install. The
    // plugin only takes onyx:// out of the file; an unused file is deleted.
    let handler = app
        .path()
        .data_dir()
        .ok()
        .and_then(|dir| legacy_link_handler(&dir, &exe));
    if let Some(path) = handler {
        match std::fs::read_to_string(&path) {
            Ok(contents) if is_onyx_link_handler(&contents) => match std::fs::remove_file(&path) {
                Ok(()) => log::info!("deleted the old onyx:// link handler"),
                Err(e) => log::warn!("could not delete the old onyx:// link handler: {e}"),
            },
            Ok(_) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => log::warn!("could not read the old onyx:// link handler: {e}"),
        }
    }
    // Also drops the handler's default and refreshes the MIME cache.
    if let Err(e) = app.deep_link().unregister("onyx") {
        log::warn!("could not remove the old onyx:// link handler: {e}");
    }
    // The package's desktop file only offers onyx://; another app (the
    // earlier desktop app) can still be the default, and it rejects these
    // sign-in links.
    let Some(product_name) = app.config().product_name.as_deref() else {
        return;
    };
    let desktop_file = packaged_desktop_file(product_name);
    match std::process::Command::new("xdg-mime")
        .args(["default", desktop_file.as_str(), "x-scheme-handler/onyx"])
        .status()
    {
        Ok(status) if status.success() => {}
        Ok(status) => log::warn!("could not make {desktop_file} open onyx:// links: {status}"),
        Err(e) => log::warn!("could not make {desktop_file} open onyx:// links: {e}"),
    }
}

fn main() {
    #[cfg(windows)]
    notify::pass_on_foreground();
    // The tray title (StatusNotifierItem) uses this name. WM_CLASS, and so
    // the desktop file match, uses the program name: the binary name.
    #[cfg(target_os = "linux")]
    gtk::glib::set_application_name("Onyx");
    let context = tauri::generate_context!();
    let version = context.package_info().version.to_string();
    let api = api::Api::new(&version).unwrap_or_else(|e| startup_failed(&e));
    let builder = tauri::Builder::default()
        // Must come first: a second launch (or an onyx:// link that starts
        // the app) hands its URL to the running instance and exits.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // A clicked answer toast shows the launcher (notify.rs), not the main window.
            #[cfg(windows)]
            if _args.iter().any(|arg| notify::is_answer_link(arg)) {
                return;
            }
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
    #[cfg(target_os = "linux")]
    let builder = builder.plugin(linux_cookies::plugin());
    let app = builder
        .setup(move |app| {
            init_logging(app.handle());
            log::info!(
                "Onyx {version} starting on {} {}",
                std::env::consts::OS,
                std::env::consts::ARCH
            );
            #[cfg(target_os = "linux")]
            linux_cookies::remove_old_cookies(app.handle());
            let config_path = app.path().app_config_dir()?.join("config.json");
            app.manage(offline::Offline::default());
            let handle = app.handle();
            if let Some(source) =
                migration::import_previous(&config_path, &migration::Sources::find(handle))
            {
                log::info!("imported the settings of the {source:?} app");
            }
            let config = ConfigStore::load(config_path);
            let policy = policy::with_remembered_server(policy::read(handle), &config);
            policy::log_effective(&policy);
            policy::apply_launch_at_login(handle, &policy);
            app.manage(AppState::new(config, policy, api));
            #[cfg(all(windows, not(debug_assertions)))]
            earlier_install::notify_if_present(handle);

            // Windows and Linux: the main window gets its own menu (main_window.rs).
            #[cfg(target_os = "macos")]
            app.set_menu(menu::build(handle)?)?;
            app.on_menu_event(|app, event| menu::handle(app, event.id().as_ref()));
            #[cfg(target_os = "macos")]
            menu::build_tray(handle)?;
            // The app keeps running without a tray; a second launch shows it.
            #[cfg(not(target_os = "macos"))]
            if let Err(e) = menu::build_tray(handle) {
                log::error!("could not create the tray icon: {e}");
            }

            policy::sync_hotkey(handle);
            if app.state::<AppState>().hotkey().is_some() {
                launcher::preload(handle);
            }
            policy::spawn_refresh(handle);
            #[cfg(not(target_os = "macos"))]
            offline::watch_idle(handle);
            notify::init(handle);

            {
                use tauri_plugin_deep_link::DeepLinkExt;
                // The NSIS and MSI installers register onyx:// for all users;
                // a per-user entry would override it. Dev builds need it at
                // runtime.
                #[cfg(all(target_os = "windows", debug_assertions))]
                if let Err(e) = app.deep_link().register_all() {
                    log::warn!("could not register onyx:// links: {e}");
                }
                #[cfg(all(target_os = "windows", not(debug_assertions)))]
                remove_other_user_link_handler("at launch");
                #[cfg(target_os = "linux")]
                register_links(handle);
                let link_app = handle.clone();
                app.deep_link().on_open_url(move |event| {
                    for url in event.urls() {
                        sso::handle_callback(&link_app, &url);
                        #[cfg(windows)]
                        notify::handle_link(&link_app, &url);
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
            commands::get_server_lock,
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
            commands::fit_window,
        ])
        .build(context)
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

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{
        is_onyx_link_handler, legacy_link_handler, link_command_is_other_program,
        packaged_desktop_file, registers_links_at_runtime,
    };

    #[test]
    fn a_link_command_for_another_program_is_found() {
        let exe = Path::new(r"C:\Program Files\Onyx\onyx.exe");
        assert!(!link_command_is_other_program(
            r#""C:\Program Files\Onyx\onyx.exe" "%1""#,
            exe
        ));
        assert!(!link_command_is_other_program(
            r#""c:\program files\onyx\ONYX.EXE" "%1""#,
            exe
        ));
        assert!(link_command_is_other_program(
            r#""C:\Users\a\AppData\Local\Onyx\onyx.exe" "%1""#,
            exe
        ));
        assert!(link_command_is_other_program(
            r"C:\Users\a\onyx.exe %1",
            exe
        ));
        assert!(link_command_is_other_program("", exe));
    }

    #[test]
    fn the_packaged_handler_is_the_linux_desktop_file() {
        let base: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let linux: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.linux.conf.json")).unwrap();
        let product_name = linux["productName"]
            .as_str()
            .or(base["productName"].as_str())
            .unwrap();
        assert_eq!(packaged_desktop_file(product_name), "Onyx.desktop");
    }

    #[test]
    fn only_unpackaged_builds_register_links_at_runtime() {
        assert!(!registers_links_at_runtime(
            false,
            Path::new("/usr/bin/onyx")
        ));
        assert!(registers_links_at_runtime(
            true,
            Path::new("/tmp/.mount_Onyx/usr/bin/onyx")
        ));
        assert!(registers_links_at_runtime(
            false,
            Path::new("/home/a/onyx/target/debug/onyx")
        ));
        assert!(registers_links_at_runtime(
            false,
            Path::new("/usr/local/bin/onyx")
        ));
    }

    #[test]
    fn the_legacy_link_handler_is_named_after_the_binary() {
        assert_eq!(
            legacy_link_handler(
                Path::new("/home/a/.local/share"),
                Path::new("/usr/bin/onyx")
            ),
            Some(Path::new("/home/a/.local/share/applications/onyx-handler.desktop").into())
        );
    }

    #[test]
    fn only_the_plugins_onyx_handler_is_deleted() {
        let written = "[Desktop Entry]\nType=Application\nName=onyx\nExec=\"/usr/bin/onyx\" %u\nTerminal=false\nMimeType=x-scheme-handler/onyx;\nNoDisplay=true\n";
        assert!(is_onyx_link_handler(written));
        // The plugin's unregister leaves the file without its MIME type.
        let emptied = written.replace("MimeType=x-scheme-handler/onyx;\n", "MimeType=\n");
        assert!(is_onyx_link_handler(&emptied));
        assert!(is_onyx_link_handler(
            &written.replace("\"/usr/bin/onyx\"", "\"/home/a/Onyx.AppImage\"")
        ));
        // A file someone changed to do more is kept.
        assert!(!is_onyx_link_handler(&written.replace(
            "x-scheme-handler/onyx;",
            "x-scheme-handler/onyx;text/html;"
        )));
        assert!(!is_onyx_link_handler(
            &written.replace("NoDisplay=true", "NoDisplay=false")
        ));
        assert!(!is_onyx_link_handler(&written.replace(" %u", "")));
        assert!(!is_onyx_link_handler(""));
        // A hidden onyx:// entry of another program is kept.
        assert!(!is_onyx_link_handler(
            &written.replace("\"/usr/bin/onyx\"", "/usr/bin/other-app")
        ));
    }
}
