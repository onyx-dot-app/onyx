use std::collections::BTreeMap;
use std::sync::Mutex;

use tauri::image::Image;
#[cfg(any(not(target_os = "macos"), test))]
use tauri::menu::AboutMetadata;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
#[cfg(any(windows, test))]
use tauri::tray::{MouseButton, MouseButtonState, TrayIconEvent};
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
#[cfg(any(not(target_os = "macos"), test))]
const CLOSE_WINDOW: &str = "close_window";
#[cfg(any(not(target_os = "macos"), test))]
const FULLSCREEN: &str = "fullscreen";

/// The main window's menu accelerators on Windows and Linux. WebView2 keeps
/// key presses from the menu while the page has focus, so `key_action` maps
/// them to the same items.
#[cfg(any(not(target_os = "macos"), test))]
const WINDOW_ACCELERATORS: [(&str, &str); 11] = [
    (NEW_CHAT, "Ctrl+N"),
    (PREFERENCES, "Ctrl+,"),
    (CLOSE_WINDOW, "Ctrl+W"),
    (QUIT, "Ctrl+Q"),
    (RELOAD, "Ctrl+R"),
    (BACK, "Alt+Left"),
    (FORWARD, "Alt+Right"),
    (ZOOM_RESET, "Ctrl+0"),
    (ZOOM_IN, "Ctrl+="),
    (ZOOM_OUT, "Ctrl+-"),
    (FULLSCREEN, "F11"),
];

#[cfg(not(target_os = "macos"))]
fn accelerator(id: &str) -> Option<&'static str> {
    WINDOW_ACCELERATORS
        .iter()
        .find(|(item, _)| *item == id)
        .map(|(_, accelerator)| *accelerator)
}

/// Modifier keys held with a key press.
#[cfg(any(windows, test))]
#[derive(Clone, Copy, Default)]
pub struct Modifiers {
    pub ctrl: bool,
    pub alt: bool,
    pub shift: bool,
}

/// The Windows virtual-key codes of a key in an accelerator. Digits, `=` and
/// `-` also match the numeric keypad.
#[cfg(any(windows, test))]
fn virtual_keys(key: &str) -> Vec<u32> {
    match key {
        "," => vec![0xBC],
        "=" => vec![0xBB, 0x6B],
        "-" => vec![0xBD, 0x6D],
        "Left" => vec![0x25],
        "Right" => vec![0x27],
        "F11" => vec![0x7A],
        _ => match key.as_bytes() {
            [c @ b'A'..=b'Z'] => vec![u32::from(*c)],
            [d @ b'0'..=b'9'] => vec![u32::from(*d), 0x60 + u32::from(d - b'0')],
            _ => Vec::new(),
        },
    }
}

/// The main window menu item for a key press (a Windows virtual-key code).
#[cfg(any(windows, test))]
pub fn key_action(virtual_key: u32, held: Modifiers) -> Option<&'static str> {
    WINDOW_ACCELERATORS.iter().find_map(|(id, accelerator)| {
        let mut parts: Vec<&str> = accelerator.split('+').collect();
        let key = parts.pop()?;
        let wants = |m: &str| parts.contains(&m);
        let matches = wants("Ctrl") == held.ctrl
            && wants("Alt") == held.alt
            && wants("Shift") == held.shift
            && virtual_keys(key).contains(&virtual_key);
        matches.then_some(*id)
    })
}

/// The macOS app menu bar.
#[cfg(target_os = "macos")]
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
            &launcher_item(app, "app")?,
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

/// The main window's menu bar on Windows and Linux. They have no app menu,
/// and an app-wide menu would also show in the launcher and other windows.
/// Copy and paste need no Edit menu there: the web view handles them.
#[cfg(not(target_os = "macos"))]
pub fn build_window_menu(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let separator = || PredefinedMenuItem::separator(app);
    let file = Submenu::with_items(
        app,
        "File",
        true,
        &[
            &MenuItem::with_id(app, NEW_CHAT, "New Chat", true, accelerator(NEW_CHAT))?,
            &launcher_item(app, "window")?,
            &separator()?,
            &MenuItem::with_id(
                app,
                PREFERENCES,
                "Preferences…",
                true,
                accelerator(PREFERENCES),
            )?,
            &separator()?,
            &MenuItem::with_id(
                app,
                CLOSE_WINDOW,
                "Close Window",
                true,
                accelerator(CLOSE_WINDOW),
            )?,
            &MenuItem::with_id(app, QUIT, "Quit Onyx", true, accelerator(QUIT))?,
        ],
    )?;
    let view = Submenu::with_items(
        app,
        "View",
        true,
        &[
            &MenuItem::with_id(app, RELOAD, "Reload", true, accelerator(RELOAD))?,
            &MenuItem::with_id(app, BACK, "Back", true, accelerator(BACK))?,
            &MenuItem::with_id(app, FORWARD, "Forward", true, accelerator(FORWARD))?,
            &separator()?,
            &MenuItem::with_id(
                app,
                ZOOM_RESET,
                "Actual Size",
                true,
                accelerator(ZOOM_RESET),
            )?,
            &MenuItem::with_id(app, ZOOM_IN, "Zoom In", true, accelerator(ZOOM_IN))?,
            &MenuItem::with_id(app, ZOOM_OUT, "Zoom Out", true, accelerator(ZOOM_OUT))?,
            &separator()?,
            &MenuItem::with_id(
                app,
                FULLSCREEN,
                "Full Screen",
                true,
                accelerator(FULLSCREEN),
            )?,
        ],
    )?;
    let help = Submenu::with_items(
        app,
        "Help",
        true,
        &[&PredefinedMenuItem::about(
            app,
            Some("About Onyx"),
            Some(about_metadata(&app.package_info().version.to_string())),
        )?],
    )?;
    Menu::with_items(app, &[&file, &view, &help])
}

/// The newest "Open Launcher" item of each menu, so policy can turn them off.
static LAUNCHER_ITEMS: Mutex<BTreeMap<&str, MenuItem<Wry>>> = Mutex::new(BTreeMap::new());

fn launcher_item(app: &AppHandle, menu: &'static str) -> tauri::Result<MenuItem<Wry>> {
    let enabled = !app.state::<AppState>().policy().disable_launcher;
    let item = MenuItem::with_id(app, LAUNCHER, "Open Launcher", enabled, None::<&str>)?;
    LAUNCHER_ITEMS
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .insert(menu, item.clone());
    // A policy refresh during the build may have missed this item.
    sync_launcher_items(app);
    Ok(item)
}

/// Sets every "Open Launcher" item to the policy at the time it runs. Queued
/// on the main thread without waiting, like `updater::set_menu_label`.
pub fn sync_launcher_items(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        let enabled = !handle.state::<AppState>().policy().disable_launcher;
        let items: Vec<MenuItem<Wry>> = LAUNCHER_ITEMS
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .values()
            .cloned()
            .collect();
        for item in &items {
            let _ = item.set_enabled(enabled);
        }
    });
}

/// Windows shows the About dialog only for an item with metadata.
#[cfg(any(not(target_os = "macos"), test))]
fn about_metadata(version: &str) -> AboutMetadata<'static> {
    AboutMetadata {
        name: Some("Onyx".into()),
        version: Some(version.into()),
        ..Default::default()
    }
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
            &launcher_item(app, "tray")?,
            &MenuItem::with_id(app, PREFERENCES, "Preferences…", true, None::<&str>)?,
        ],
    )?;
    if updater::SUPPORTED {
        menu.append(&updates_item(app)?)?;
    }
    menu.append_items(&[
        &PredefinedMenuItem::separator(app)?,
        &MenuItem::with_id(app, QUIT, "Quit Onyx", true, None::<&str>)?,
    ])?;
    let builder = TrayIconBuilder::with_id("onyx-tray")
        .icon(Image::from_bytes(include_bytes!("../icons/tray-icon.png"))?)
        .icon_as_template(true)
        .tooltip("Onyx")
        .menu(&menu)
        // Windows convention: a left click opens the app, a right click the menu.
        .show_menu_on_left_click(!cfg!(windows));
    #[cfg(windows)]
    let builder = builder.on_tray_icon_event(|tray, event| {
        if opens_app(&event) {
            handle(tray.app_handle(), OPEN);
        }
    });
    // Linux writes the icon to a file before the tray shows.
    #[cfg(target_os = "linux")]
    let builder = {
        let runtime_dir = std::env::var_os("XDG_RUNTIME_DIR");
        match tray_icon_dir(
            runtime_dir.as_deref().map(std::path::Path::new),
            app.path().app_cache_dir().ok(),
        ) {
            Some(dir) => builder.temp_dir_path(dir),
            None => builder,
        }
    };
    // No tray `on_menu_event`: Tauri delivers every menu event, tray items
    // included, to the app-level handler in main.rs. A second listener here
    // ran each menu action twice.
    builder.build(app)?;
    Ok(())
}

/// The directory for the Linux tray icon file, or `None` for the library
/// default (`$XDG_RUNTIME_DIR/tray-icon`). With no runtime directory the
/// default is `/tmp/tray-icon`, which only its first user can write to.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn tray_icon_dir(
    runtime_dir: Option<&std::path::Path>,
    cache_dir: Option<std::path::PathBuf>,
) -> Option<std::path::PathBuf> {
    if runtime_dir.is_some_and(std::path::Path::is_absolute) {
        return None;
    }
    cache_dir.map(|dir| dir.join("tray-icon"))
}

/// A left click on the tray icon (on release, as Windows menus open).
#[cfg(any(windows, test))]
fn opens_app(event: &TrayIconEvent) -> bool {
    matches!(
        event,
        TrayIconEvent::Click {
            button: MouseButton::Left,
            button_state: MouseButtonState::Up,
            ..
        }
    )
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
        #[cfg(not(target_os = "macos"))]
        CLOSE_WINDOW => {
            if let Some(window) = app.get_webview_window(main_window::LABEL) {
                let _ = window.close();
            }
        }
        #[cfg(not(target_os = "macos"))]
        FULLSCREEN => {
            if let Some(window) = app.get_webview_window(main_window::LABEL) {
                let fullscreen = window.is_fullscreen().unwrap_or(false);
                let _ = window.set_fullscreen(!fullscreen);
            }
        }
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

// Unix paths: "/run/user/1000" is not absolute on Windows.
#[cfg(all(test, unix))]
mod tray_dir_tests {
    use super::tray_icon_dir;
    use std::path::{Path, PathBuf};

    #[test]
    fn tray_icon_dir_keeps_the_runtime_dir_default() {
        let cache = Some(PathBuf::from("/home/a/.cache/app"));
        assert_eq!(
            tray_icon_dir(Some(Path::new("/run/user/1000")), cache),
            None
        );
    }

    #[test]
    fn tray_icon_dir_is_per_user_without_a_runtime_dir() {
        let cache = PathBuf::from("/home/a/.cache/app");
        let expected = Some(cache.join("tray-icon"));
        assert_eq!(tray_icon_dir(None, Some(cache.clone())), expected);
        // dirs::runtime_dir ignores a relative XDG_RUNTIME_DIR.
        assert_eq!(tray_icon_dir(Some(Path::new("run")), Some(cache)), expected);
    }

    #[test]
    fn tray_icon_dir_falls_back_to_the_default_without_a_cache_dir() {
        assert_eq!(tray_icon_dir(None, None), None);
    }
}

#[cfg(test)]
mod tests {
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconEvent};

    use super::*;

    fn ctrl() -> Modifiers {
        Modifiers {
            ctrl: true,
            ..Modifiers::default()
        }
    }

    #[test]
    fn menu_keys_map_to_their_items() {
        assert_eq!(key_action(0xBC, ctrl()), Some(PREFERENCES));
        assert_eq!(key_action(u32::from(b'N'), ctrl()), Some(NEW_CHAT));
        assert_eq!(key_action(u32::from(b'W'), ctrl()), Some(CLOSE_WINDOW));
        assert_eq!(key_action(u32::from(b'Q'), ctrl()), Some(QUIT));
        assert_eq!(key_action(u32::from(b'R'), ctrl()), Some(RELOAD));
        assert_eq!(key_action(0xBB, ctrl()), Some(ZOOM_IN));
        assert_eq!(key_action(0x6B, ctrl()), Some(ZOOM_IN));
        assert_eq!(key_action(0xBD, ctrl()), Some(ZOOM_OUT));
        assert_eq!(key_action(0x30, ctrl()), Some(ZOOM_RESET));
        assert_eq!(key_action(0x60, ctrl()), Some(ZOOM_RESET));
        assert_eq!(key_action(0x7A, Modifiers::default()), Some(FULLSCREEN));
        let alt = Modifiers {
            alt: true,
            ..Modifiers::default()
        };
        assert_eq!(key_action(0x25, alt), Some(BACK));
        assert_eq!(key_action(0x27, alt), Some(FORWARD));
    }

    #[test]
    fn other_keys_reach_the_page() {
        // Ctrl+K and plain typing are the page's.
        assert_eq!(key_action(u32::from(b'K'), ctrl()), None);
        assert_eq!(key_action(u32::from(b'N'), Modifiers::default()), None);
        assert_eq!(key_action(0x25, Modifiers::default()), None);
        let ctrl_shift = Modifiers {
            ctrl: true,
            shift: true,
            alt: false,
        };
        assert_eq!(key_action(u32::from(b'N'), ctrl_shift), None);
    }

    #[test]
    fn every_menu_accelerator_has_a_key() {
        for (id, accelerator) in WINDOW_ACCELERATORS {
            let key = accelerator.rsplit('+').next().unwrap_or_default();
            assert!(!virtual_keys(key).is_empty(), "{id}: {accelerator}");
        }
    }

    #[test]
    fn the_about_item_has_the_name_and_version() {
        let metadata = about_metadata("1.2.3");
        assert_eq!(metadata.name.as_deref(), Some("Onyx"));
        assert_eq!(metadata.version.as_deref(), Some("1.2.3"));
    }

    fn click(button: MouseButton, button_state: MouseButtonState) -> TrayIconEvent {
        TrayIconEvent::Click {
            id: "onyx-tray".into(),
            position: tauri::PhysicalPosition::new(0.0, 0.0),
            rect: tauri::Rect::default(),
            button,
            button_state,
        }
    }

    #[test]
    fn a_left_click_on_the_tray_icon_opens_the_app() {
        assert!(opens_app(&click(MouseButton::Left, MouseButtonState::Up)));
        assert!(!opens_app(&click(
            MouseButton::Left,
            MouseButtonState::Down
        )));
        assert!(!opens_app(&click(MouseButton::Right, MouseButtonState::Up)));
    }
}
