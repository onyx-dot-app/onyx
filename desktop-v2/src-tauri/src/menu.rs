use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, Wry};

use crate::main_window;
use crate::state::AppState;
use crate::windows;

pub const PREFERENCES: &str = "preferences";
const NEW_CHAT: &str = "new_chat";
const RELOAD: &str = "reload";
const OPEN: &str = "open";
const QUIT: &str = "quit";

pub fn build(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let separator = || PredefinedMenuItem::separator(app);

    let app_menu = Submenu::with_items(
        app,
        "Onyx v2",
        true,
        &[
            &PredefinedMenuItem::about(app, Some("About Onyx"), None)?,
            &separator()?,
            &MenuItem::with_id(app, PREFERENCES, "Preferences…", true, Some("CmdOrCtrl+,"))?,
            &separator()?,
            &PredefinedMenuItem::services(app, None)?,
            &separator()?,
            &PredefinedMenuItem::hide(app, None)?,
            &PredefinedMenuItem::hide_others(app, None)?,
            &PredefinedMenuItem::show_all(app, None)?,
            &separator()?,
            &PredefinedMenuItem::quit(app, None)?,
        ],
    )?;
    let file = Submenu::with_items(
        app,
        "File",
        true,
        &[
            &MenuItem::with_id(app, NEW_CHAT, "New Chat", true, Some("CmdOrCtrl+N"))?,
            &separator()?,
            &PredefinedMenuItem::close_window(app, None)?,
        ],
    )?;
    let edit = Submenu::with_items(
        app,
        "Edit",
        true,
        &[
            &PredefinedMenuItem::undo(app, None)?,
            &PredefinedMenuItem::redo(app, None)?,
            &separator()?,
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;
    let view = Submenu::with_items(
        app,
        "View",
        true,
        &[
            &MenuItem::with_id(app, RELOAD, "Reload", true, Some("CmdOrCtrl+R"))?,
            &separator()?,
            &PredefinedMenuItem::fullscreen(app, None)?,
        ],
    )?;
    let window = Submenu::with_items(
        app,
        "Window",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::maximize(app, None)?,
        ],
    )?;
    Menu::with_items(app, &[&app_menu, &file, &edit, &view, &window])
}

pub fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let menu = Menu::with_items(
        app,
        &[
            &MenuItem::with_id(app, OPEN, "Open Onyx", true, None::<&str>)?,
            &MenuItem::with_id(app, PREFERENCES, "Preferences…", true, None::<&str>)?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, QUIT, "Quit Onyx", true, None::<&str>)?,
        ],
    )?;
    TrayIconBuilder::with_id("onyx-tray")
        .icon(Image::from_bytes(include_bytes!("../icons/tray-icon.png"))?)
        .icon_as_template(true)
        .tooltip("Onyx")
        .menu(&menu)
        .show_menu_on_left_click(true)
        // No tray `on_menu_event`: Tauri delivers every menu event, tray items
        // included, to the app-level handler in main.rs. A second listener here
        // ran each menu action twice.
        .build(app)?;
    Ok(())
}

pub fn handle(app: &AppHandle, id: &str) {
    match id {
        PREFERENCES => {
            let _ = windows::open_preferences(app);
        }
        OPEN => windows::show_primary(app),
        QUIT => app.exit(0),
        NEW_CHAT => {
            let state = app.state::<AppState>();
            let epoch = state.epoch();
            let Ok((server, token)) = state.session() else {
                windows::route(app);
                return;
            };
            let app = app.clone();
            tauri::async_runtime::spawn(async move {
                // A sign-out between the menu click and this task wins.
                if app.state::<AppState>().epoch() != epoch {
                    return;
                }
                if let Err(e) = main_window::open(&app, &server, &token, "/app").await {
                    log::warn!("could not open a new chat: {e}");
                }
            });
        }
        RELOAD => {
            if let Some(window) = app.get_webview_window(main_window::LABEL) {
                let _ = window.reload();
            }
        }
        _ => {}
    }
}
