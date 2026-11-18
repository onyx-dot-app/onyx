//! Aonyx, the desktop pet: an easter egg. Five quick clicks on the launcher's
//! logo bring the otter onto the screen (and send it away again). It sits on
//! top of other apps, on every Space, without ever activating Onyx; it reacts
//! to the launcher (thinking while an answer streams, happy when it is done),
//! a click opens the launcher, and it can be dragged anywhere.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem};
use tauri::{AppHandle, Emitter, LogicalPosition, Manager, WindowEvent};

use crate::state::AppState;
use crate::windows::{local_navigation_allowed, local_new_window};

pub const LABEL: &str = "aonyx";
/// Menu item in the pet's right-click menu.
pub const HIDE: &str = "aonyx-hide";
/// Event the page listens for: the animation to play.
const STATE_EVENT: &str = "aonyx-state";
const SIZE: f64 = 96.0;
/// Space between the pet and the screen's bottom-right corner, above the Dock.
const MARGIN: (f64, f64) = (32.0, 120.0);

/// What the pet shows. The page maps each to an animation.
#[derive(Clone, Copy)]
pub enum Mood {
    Idle,
    Thinking,
    Happy,
    Hop,
}

impl Mood {
    fn name(self) -> &'static str {
        match self {
            Mood::Idle => "idle",
            Mood::Thinking => "thinking",
            Mood::Happy => "happy",
            Mood::Hop => "hop",
        }
    }
}

/// Tells the pet what is going on; does nothing while it is not shown.
pub fn set_mood(app: &AppHandle, mood: Mood) {
    let visible = app
        .get_webview_window(LABEL)
        .is_some_and(|w| w.is_visible().unwrap_or(false));
    if visible {
        let _ = app.emit_to(LABEL, STATE_EVENT, mood.name());
    }
}

/// Shows the pet at startup if it was on screen when the app last ran.
pub fn restore(app: &AppHandle) {
    if app.state::<AppState>().config.get().aonyx == Some(true) {
        show(app);
    }
}

/// The launcher's easter egg: shows the pet, or sends it away.
pub fn toggle(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if platform::is_visible(&handle) {
            hide_now(&handle);
        } else {
            show_now(&handle);
        }
    });
}

pub fn hide(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || hide_now(&handle));
}

fn show(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || show_now(&handle));
}

// The pet window is created once and then only shown and hidden: destroying
// an NSPanel window raises an AppKit exception.
fn show_now(app: &AppHandle) {
    let position = start_position(app);
    match platform::show(app, position) {
        Ok(()) => remember_shown(app, true),
        Err(e) => log::warn!("could not show Aonyx: {e}"),
    }
}

fn hide_now(app: &AppHandle) {
    platform::hide(app);
    remember_shown(app, false);
}

fn remember_shown(app: &AppHandle, shown: bool) {
    if let Err(e) = app
        .state::<AppState>()
        .config
        .update(|c| c.aonyx = Some(shown))
    {
        log::warn!("could not save Aonyx: {e}");
    }
}

/// The saved position if it is still on a display, else the primary
/// display's bottom-right corner.
fn start_position(app: &AppHandle) -> LogicalPosition<f64> {
    let monitors = app.available_monitors().unwrap_or_default();
    if let Some([x, y]) = app.state::<AppState>().config.get().aonyx_position {
        let on_screen = monitors.iter().any(|m| {
            let scale = m.scale_factor();
            let pos = m.position().to_logical::<f64>(scale);
            let size = m.size().to_logical::<f64>(scale);
            x >= pos.x
                && y >= pos.y
                && x + SIZE <= pos.x + size.width
                && y + SIZE <= pos.y + size.height
        });
        if on_screen {
            return LogicalPosition::new(x, y);
        }
    }
    let Some(monitor) = app.primary_monitor().ok().flatten() else {
        return LogicalPosition::new(200.0, 200.0);
    };
    let scale = monitor.scale_factor();
    let pos = monitor.position().to_logical::<f64>(scale);
    let size = monitor.size().to_logical::<f64>(scale);
    LogicalPosition::new(
        pos.x + size.width - SIZE - MARGIN.0,
        pos.y + size.height - SIZE - MARGIN.1,
    )
}

/// The latest position while the pet is dragged; saved once it rests.
static PENDING_POSITION: Mutex<Option<[f64; 2]>> = Mutex::new(None);
static MOVE_ID: AtomicU64 = AtomicU64::new(0);

fn on_window_event(app: &AppHandle, event: &WindowEvent) {
    let WindowEvent::Moved(physical) = event else {
        return;
    };
    let Some(window) = app.get_webview_window(LABEL) else {
        return;
    };
    let scale = window.scale_factor().unwrap_or(1.0);
    let logical = physical.to_logical::<f64>(scale);
    *PENDING_POSITION.lock().unwrap_or_else(|p| p.into_inner()) = Some([logical.x, logical.y]);
    // A drag sends many moves: save only after it has been still for a moment.
    let id = MOVE_ID.fetch_add(1, Ordering::SeqCst) + 1;
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(Duration::from_millis(400)).await;
        if MOVE_ID.load(Ordering::SeqCst) != id {
            return;
        }
        let pending = PENDING_POSITION
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .take();
        if let Some(position) = pending {
            let _ = app
                .state::<AppState>()
                .config
                .update(|c| c.aonyx_position = Some(position));
        }
    });
}

/// The right-click menu on the pet.
pub fn show_menu(app: &AppHandle) -> Result<(), String> {
    let window = app.get_webview_window(LABEL).ok_or("Aonyx is not shown")?;
    let menu = Menu::with_items(
        app,
        &[
            &MenuItem::with_id(
                app,
                crate::menu::LAUNCHER,
                "Open Launcher",
                true,
                None::<&str>,
            )
            .map_err(|e| e.to_string())?,
            &MenuItem::with_id(app, HIDE, "Hide Aonyx", true, None::<&str>)
                .map_err(|e| e.to_string())?,
        ],
    )
    .map_err(|e| e.to_string())?;
    window.popup_menu(&menu).map_err(|e| e.to_string())
}

#[cfg(target_os = "macos")]
#[allow(clippy::unused_unit)]
mod platform {
    use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager, Position, Size, WebviewUrl};
    use tauri_nspanel::{
        tauri_panel, CollectionBehavior, ManagerExt, PanelBuilder, PanelLevel, StyleMask,
    };

    use super::{local_navigation_allowed, local_new_window, on_window_event, LABEL, SIZE};

    tauri_panel! {
        panel!(AonyxPanel {
            config: {
                can_become_key_window: false,
                is_floating_panel: true
            }
        })
    }

    /// A borderless, non-activating panel: clicking or dragging the pet never
    /// brings Onyx forward or takes focus from the app you are in.
    pub fn is_visible(app: &AppHandle) -> bool {
        app.get_webview_window(LABEL)
            .is_some_and(|w| w.is_visible().unwrap_or(false))
    }

    pub fn hide(app: &AppHandle) {
        if let Ok(panel) = app.get_webview_panel(LABEL) {
            panel.hide();
        }
    }

    pub fn show(app: &AppHandle, position: LogicalPosition<f64>) -> Result<(), String> {
        if app.get_webview_panel(LABEL).is_err() {
            create(app, position)?;
        } else if let Some(window) = app.get_webview_window(LABEL) {
            let _ = window.set_position(Position::Logical(position));
        }
        // A panel that never becomes key must be ordered front explicitly;
        // showing the window does nothing while another app is active.
        app.get_webview_panel(LABEL)
            .map_err(|e| format!("{e:?}"))?
            .show();
        Ok(())
    }

    fn create(app: &AppHandle, position: LogicalPosition<f64>) -> Result<(), String> {
        let nav_app = app.clone();
        let new_window = local_new_window(app);
        PanelBuilder::<_, AonyxPanel>::new(app, LABEL)
            .url(WebviewUrl::App("aonyx.html".into()))
            .title("Aonyx")
            .size(Size::Logical(LogicalSize::new(SIZE, SIZE)))
            .position(Position::Logical(position))
            .level(PanelLevel::Floating)
            .style_mask(StyleMask::empty().borderless().nonactivating_panel())
            .collection_behavior(
                CollectionBehavior::new()
                    .can_join_all_spaces()
                    .full_screen_auxiliary()
                    .ignores_cycle(),
            )
            .hides_on_deactivate(false)
            .no_activate(true)
            .has_shadow(false)
            .transparent(true)
            .with_window(move |window| {
                window
                    .decorations(false)
                    .transparent(true)
                    .skip_taskbar(true)
                    .resizable(false)
                    .focused(false)
                    .accept_first_mouse(true)
                    .on_navigation(move |url| local_navigation_allowed(&nav_app, url))
                    .on_new_window(new_window)
            })
            .build()
            .map_err(|e| e.to_string())?;
        if let Some(window) = app.get_webview_window(LABEL) {
            let events_app = app.clone();
            window.on_window_event(move |event| on_window_event(&events_app, event));
        }
        Ok(())
    }
}

#[cfg(not(target_os = "macos"))]
mod platform {
    use tauri::{AppHandle, LogicalPosition, Manager, WebviewUrl, WebviewWindowBuilder};

    use super::{local_navigation_allowed, local_new_window, on_window_event, LABEL, SIZE};

    pub fn is_visible(app: &AppHandle) -> bool {
        app.get_webview_window(LABEL)
            .is_some_and(|w| w.is_visible().unwrap_or(false))
    }

    pub fn hide(app: &AppHandle) {
        if let Some(window) = app.get_webview_window(LABEL) {
            let _ = window.hide();
        }
    }

    pub fn show(app: &AppHandle, position: LogicalPosition<f64>) -> Result<(), String> {
        if let Some(window) = app.get_webview_window(LABEL) {
            let _ = window.set_position(position);
            return window.show().map_err(|e| e.to_string());
        }
        let nav_app = app.clone();
        let window = WebviewWindowBuilder::new(app, LABEL, WebviewUrl::App("aonyx.html".into()))
            .title("Aonyx")
            .inner_size(SIZE, SIZE)
            .position(position.x, position.y)
            .decorations(false)
            .transparent(true)
            .shadow(false)
            .always_on_top(true)
            .visible_on_all_workspaces(true)
            .skip_taskbar(true)
            .resizable(false)
            .focused(false)
            .on_navigation(move |url| local_navigation_allowed(&nav_app, url))
            .on_new_window(local_new_window(app))
            .build()
            .map_err(|e| e.to_string())?;
        let events_app = app.clone();
        window.on_window_event(move |event| on_window_event(&events_app, event));
        Ok(())
    }
}
