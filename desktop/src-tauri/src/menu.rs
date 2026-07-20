use crate::config::{save_config, ConfigState};
use crate::debug_log::{log_backend_error, MENU_OPEN_DEBUG_LOG_ID, MENU_TOGGLE_DEVTOOLS_ID};
use crate::window::{focus_main_window, trigger_new_chat};
use tauri::image::Image;
use tauri::menu::{
    CheckMenuItem, Menu, MenuBuilder, MenuItem, PredefinedMenuItem, SubmenuBuilder, HELP_SUBMENU_ID,
};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, Wry};

const TRAY_ID: &str = "onyx-tray";
const TRAY_ICON_BYTES: &[u8] = include_bytes!("../icons/tray-icon.png");
const TRAY_MENU_OPEN_APP_ID: &str = "tray_open_app";
const TRAY_MENU_OPEN_CHAT_ID: &str = "tray_open_chat";
const TRAY_MENU_SHOW_IN_BAR_ID: &str = "tray_show_in_menu_bar";
const TRAY_MENU_QUIT_ID: &str = "tray_quit";
pub const MENU_SHOW_MENU_BAR_ID: &str = "show_menu_bar";
#[cfg(target_os = "linux")]
pub const MENU_HIDE_DECORATIONS_ID: &str = "hide_window_decorations";
pub const MENU_NEW_CHAT_ID: &str = "new_chat";
pub const MENU_NEW_WINDOW_ID: &str = "new_window";
pub const MENU_OPEN_SETTINGS_ID: &str = "open_settings";
pub const MENU_OPEN_DOCS_ID: &str = "open_docs";

/// Handles to the checkable menu items, populated once in `setup_app_menu`.
/// Toggling reaches for these directly instead of re-walking the whole menu
/// tree by string ID every time -- a menu-structure change could otherwise
/// desync a checkbox from the actual config value without any error.
#[cfg(not(target_os = "macos"))]
pub struct MenuHandles {
    pub show_menu_bar: CheckMenuItem<Wry>,
    #[cfg(target_os = "linux")]
    pub hide_decorations: CheckMenuItem<Wry>,
}

pub fn setup_app_menu(app: &AppHandle) -> tauri::Result<()> {
    let menu = app.menu().unwrap_or(Menu::default(app)?);

    let new_chat_item = MenuItem::with_id(
        app,
        MENU_NEW_CHAT_ID,
        "New Chat",
        true,
        Some("CmdOrCtrl+N"),
    )?;
    let new_window_item = MenuItem::with_id(
        app,
        MENU_NEW_WINDOW_ID,
        "New Window",
        true,
        Some("CmdOrCtrl+Shift+N"),
    )?;
    let settings_item = MenuItem::with_id(
        app,
        MENU_OPEN_SETTINGS_ID,
        "Settings...",
        true,
        Some("CmdOrCtrl+Comma"),
    )?;
    let docs_item = MenuItem::with_id(
        app,
        MENU_OPEN_DOCS_ID,
        "Onyx Documentation",
        true,
        None::<&str>,
    )?;

    if let Some(file_menu) = menu
        .items()?
        .into_iter()
        .filter_map(|item| item.as_submenu().cloned())
        .find(|submenu| submenu.text().ok().as_deref() == Some("File"))
    {
        file_menu.insert_items(&[&new_chat_item, &new_window_item, &settings_item], 0)?;
    } else {
        let file_menu = SubmenuBuilder::new(app, "File")
            .items(&[
                &new_chat_item,
                &new_window_item,
                &settings_item,
                &PredefinedMenuItem::close_window(app, None)?,
            ])
            .build()?;
        menu.prepend(&file_menu)?;
    }

    #[cfg(not(target_os = "macos"))]
    {
        let config = app.state::<ConfigState>().config();

        let show_menu_bar_item = CheckMenuItem::with_id(
            app,
            MENU_SHOW_MENU_BAR_ID,
            "Show Menu Bar",
            true,
            config.show_menu_bar,
            None::<&str>,
        )?;

        #[cfg(target_os = "linux")]
        let hide_decorations_item = CheckMenuItem::with_id(
            app,
            MENU_HIDE_DECORATIONS_ID,
            "Hide Window Decorations",
            true,
            config.hide_window_decorations,
            None::<&str>,
        )?;

        app.manage(MenuHandles {
            show_menu_bar: show_menu_bar_item.clone(),
            #[cfg(target_os = "linux")]
            hide_decorations: hide_decorations_item.clone(),
        });

        if let Some(window_menu) = menu
            .items()?
            .into_iter()
            .filter_map(|item| item.as_submenu().cloned())
            .find(|submenu| submenu.text().ok().as_deref() == Some("Window"))
        {
            window_menu.append(&show_menu_bar_item)?;
            #[cfg(target_os = "linux")]
            window_menu.append(&hide_decorations_item)?;
        } else {
            #[allow(unused_mut)]
            let mut window_menu_builder =
                SubmenuBuilder::new(app, "Window").item(&show_menu_bar_item);
            #[cfg(target_os = "linux")]
            {
                window_menu_builder = window_menu_builder.item(&hide_decorations_item);
            }
            let window_menu = window_menu_builder.build()?;

            let items = menu.items()?;
            let help_idx = items
                .iter()
                .position(|item| {
                    item.as_submenu().and_then(|s| s.text().ok()).as_deref() == Some("Help")
                })
                .unwrap_or(items.len());
            menu.insert(&window_menu, help_idx)?;
        }
    }

    if let Some(help_menu) = menu
        .get(HELP_SUBMENU_ID)
        .and_then(|item| item.as_submenu().cloned())
    {
        help_menu.append(&docs_item)?;
    } else {
        let help_menu = SubmenuBuilder::with_id(app, HELP_SUBMENU_ID, "Help")
            .item(&docs_item)
            .build()?;
        menu.append(&help_menu)?;
    }

    let state = app.state::<ConfigState>();
    if state.debug_mode {
        let toggle_devtools_item = MenuItem::with_id(
            app,
            MENU_TOGGLE_DEVTOOLS_ID,
            "Toggle DevTools",
            true,
            Some("F12"),
        )?;
        let open_log_item = MenuItem::with_id(
            app,
            MENU_OPEN_DEBUG_LOG_ID,
            "Open Debug Log",
            true,
            None::<&str>,
        )?;

        let debug_menu = SubmenuBuilder::new(app, "Debug")
            .item(&toggle_devtools_item)
            .item(&open_log_item)
            .build()?;
        menu.append(&debug_menu)?;
    }

    app.set_menu(menu)?;
    Ok(())
}

/// Toggle `show_menu_bar`, persist it, apply it to every open window, and
/// sync the "Show Menu Bar" checkbox -- the single entry point used by both
/// a direct menu click and the native Alt-key toggle (see `alt_menu.rs`), so
/// the checkbox can't drift out of sync with whichever path triggered it.
pub fn handle_menu_bar_toggle(app: &AppHandle) {
    if cfg!(target_os = "macos") {
        return;
    }
    let state = app.state::<ConfigState>();
    let show = {
        let config = state.update_config(|c| c.show_menu_bar = !c.show_menu_bar);
        if let Err(e) = save_config(&config) {
            log_backend_error(app, &format!("Failed to save config: {e}"));
        }
        config.show_menu_bar
    };

    for (_, window) in app.webview_windows() {
        let result = if show {
            window.show_menu()
        } else {
            window.hide_menu()
        };
        if let Err(e) = result {
            log_backend_error(app, &format!("Failed to toggle menu-bar visibility: {e}"));
        }
    }

    #[cfg(not(target_os = "macos"))]
    if let Some(handles) = app.try_state::<MenuHandles>() {
        if let Err(e) = handles.show_menu_bar.set_checked(show) {
            log_backend_error(app, &format!("Failed to sync menu-bar checkbox: {e}"));
        }
    }
}

#[cfg(target_os = "linux")]
pub fn handle_decorations_toggle(app: &AppHandle) {
    let state = app.state::<ConfigState>();
    let hide = {
        let config = state.update_config(|c| c.hide_window_decorations = !c.hide_window_decorations);
        if let Err(e) = save_config(&config) {
            log_backend_error(app, &format!("Failed to save config: {e}"));
        }
        config.hide_window_decorations
    };

    for (_, window) in app.webview_windows() {
        if let Err(e) = window.set_decorations(!hide) {
            log_backend_error(app, &format!("Failed to toggle window decorations: {e}"));
        }
    }

    if let Some(handles) = app.try_state::<MenuHandles>() {
        if let Err(e) = handles.hide_decorations.set_checked(hide) {
            log_backend_error(app, &format!("Failed to sync decorations checkbox: {e}"));
        }
    }
}

fn build_tray_menu(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let open_app = MenuItem::with_id(app, TRAY_MENU_OPEN_APP_ID, "Open Onyx", true, None::<&str>)?;
    let open_chat = MenuItem::with_id(
        app,
        TRAY_MENU_OPEN_CHAT_ID,
        "Open Chat Window",
        true,
        None::<&str>,
    )?;
    let show_in_menu_bar = CheckMenuItem::with_id(
        app,
        TRAY_MENU_SHOW_IN_BAR_ID,
        "Show in Menu Bar",
        true,
        true,
        None::<&str>,
    )?;
    // Keep it visible/pinned without letting users uncheck (avoids orphaning the tray)
    let _ = show_in_menu_bar.set_enabled(false);
    let quit = PredefinedMenuItem::quit(app, Some("Quit Onyx"))?;

    MenuBuilder::new(app)
        .item(&open_app)
        .item(&open_chat)
        .separator()
        .item(&show_in_menu_bar)
        .separator()
        .item(&quit)
        .build()
}

fn handle_tray_menu_event(app: &AppHandle, id: &str) {
    match id {
        TRAY_MENU_OPEN_APP_ID => {
            focus_main_window(app);
        }
        TRAY_MENU_OPEN_CHAT_ID => {
            focus_main_window(app);
            trigger_new_chat(app);
        }
        TRAY_MENU_QUIT_ID => {
            app.exit(0);
        }
        TRAY_MENU_SHOW_IN_BAR_ID => {
            // No-op for now; the item stays checked/disabled to indicate it's pinned.
        }
        _ => {}
    }
}

pub fn setup_tray_icon(app: &AppHandle) -> tauri::Result<()> {
    let mut builder = TrayIconBuilder::with_id(TRAY_ID).tooltip("Onyx");

    let tray_icon = Image::from_bytes(TRAY_ICON_BYTES)
        .ok()
        .or_else(|| app.default_window_icon().cloned());

    if let Some(icon) = tray_icon {
        builder = builder.icon(icon);

        #[cfg(target_os = "macos")]
        {
            builder = builder.icon_as_template(true);
        }
    }

    if let Ok(menu) = build_tray_menu(app) {
        builder = builder.menu(&menu);
    }

    builder
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { .. } = event {
                focus_main_window(tray.app_handle());
            }
        })
        .on_menu_event(|app, event| handle_tray_menu_event(app, event.id().as_ref()))
        .build(app)?;

    Ok(())
}
