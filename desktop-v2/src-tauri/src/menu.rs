use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, Wry};

use crate::main_window;
use crate::state::AppState;
use crate::updater;
use crate::windows;

pub const PREFERENCES: &str = "preferences";
const NEW_CHAT: &str = "new_chat";
pub const LAUNCHER: &str = "launcher";
const RELOAD: &str = "reload";
const ZOOM_RESET: &str = "zoom_reset";
const ZOOM_IN: &str = "zoom_in";
const ZOOM_OUT: &str = "zoom_out";
const BACK: &str = "back";
const FORWARD: &str = "forward";
const ZOOM_STEPS: [f64; 9] = [0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75];
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
            &updates_item(app)?,
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
            &MenuItem::with_id(app, LAUNCHER, "Open Launcher", true, None::<&str>)?,
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
            &MenuItem::with_id(app, BACK, "Back", true, Some("CmdOrCtrl+["))?,
            &MenuItem::with_id(app, FORWARD, "Forward", true, Some("CmdOrCtrl+]"))?,
            &separator()?,
            &MenuItem::with_id(app, ZOOM_RESET, "Actual Size", true, Some("CmdOrCtrl+0"))?,
            &MenuItem::with_id(app, ZOOM_IN, "Zoom In", true, Some("CmdOrCtrl+="))?,
            &MenuItem::with_id(app, ZOOM_OUT, "Zoom Out", true, Some("CmdOrCtrl+-"))?,
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

fn updates_item(app: &AppHandle) -> tauri::Result<MenuItem<Wry>> {
    let item = MenuItem::with_id(
        app,
        updater::CHECK_ID,
        "Check for Updates…",
        true,
        None::<&str>,
    )?;
    updater::register_menu_item(item.clone());
    Ok(item)
}

pub fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let menu = Menu::with_items(
        app,
        &[
            &MenuItem::with_id(app, OPEN, "Open Onyx", true, None::<&str>)?,
            &MenuItem::with_id(app, LAUNCHER, "Open Launcher", true, None::<&str>)?,
            &MenuItem::with_id(app, PREFERENCES, "Preferences…", true, None::<&str>)?,
            &updates_item(app)?,
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
        LAUNCHER => windows::toggle_launcher(app),
        crate::aonyx::HIDE => crate::aonyx::hide(app),
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
                if let Err(e) = window.reload() {
                    log::warn!("could not reload: {e}");
                }
            }
        }
        BACK | FORWARD => {
            if let Some(window) = app.get_webview_window(main_window::LABEL) {
                let script = if id == BACK {
                    "history.back()"
                } else {
                    "history.forward()"
                };
                if let Err(e) = window.eval(script) {
                    log::warn!("could not go back or forward: {e}");
                }
            }
        }
        ZOOM_RESET | ZOOM_IN | ZOOM_OUT => set_zoom(app, id),
        updater::CHECK_ID => updater::on_menu(app),
        _ => {}
    }
}

/// Steps the main window's zoom like a browser and remembers it.
fn set_zoom(app: &AppHandle, id: &str) {
    let state = app.state::<AppState>();
    let current = state.config.get().zoom();
    let index = ZOOM_STEPS
        .iter()
        .position(|z| (z - current).abs() < 0.01)
        .unwrap_or(4);
    let next = match id {
        ZOOM_IN => ZOOM_STEPS[(index + 1).min(ZOOM_STEPS.len() - 1)],
        ZOOM_OUT => ZOOM_STEPS[index.saturating_sub(1)],
        _ => 1.0,
    };
    // The page's chrome and the next step both read the saved zoom, so an
    // unsaved zoom is not applied.
    if let Err(e) = state.config.update(|c| c.zoom = Some(next)) {
        log::warn!("could not save the zoom level: {e}");
        return;
    }
    if let Some(window) = app.get_webview_window(main_window::LABEL) {
        if let Err(e) = window.set_zoom(next) {
            log::warn!("could not apply the zoom level: {e}");
        }
    }
    main_window::sync_chrome(app);
}
