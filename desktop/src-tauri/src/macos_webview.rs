//! wry's `WKUIDelegate` does not implement JavaScript dialogs or
//! `window.close()`. Without them `alert()` and `prompt()` return at once,
//! `confirm()` always returns `false`, and script-opened popups (OAuth)
//! cannot close themselves. This adds those methods to wry's delegate class.
//! `class_addMethod` never replaces a method, so a later wry that implements
//! them keeps its own behaviour.

use std::ffi::CStr;
use std::ptr;
use std::sync::Once;

use block2::Block;
use objc2::ffi::class_addMethod;
use objc2::rc::Retained;
use objc2::runtime::{AnyClass, AnyObject, Bool, Imp, Sel};
use objc2::{msg_send, sel, MainThreadMarker};
use objc2_app_kit::{NSAlert, NSAlertFirstButtonReturn, NSTextField};
use objc2_foundation::{ns_string, NSSize, NSString};
use tauri::WebviewWindow;

use crate::debug_log::log_backend_error;

static INSTALL: Once = Once::new();

pub fn install_ui_delegate_extensions(window: &WebviewWindow) {
    if INSTALL.is_completed() {
        return;
    }
    let result = window.with_webview(|webview| {
        let wk_webview = webview.inner().cast::<AnyObject>();
        INSTALL.call_once(|| {
            // SAFETY: `with_webview` runs on the main thread with a live
            // `WKWebView`; each IMP matches its selector's type encoding.
            unsafe { install(wk_webview) }
        });
    });
    if let Err(e) = result {
        log_backend_error(
            window.app_handle(),
            &format!("Failed to install webview dialog handlers: {e}"),
        );
    }
}

unsafe fn install(wk_webview: *mut AnyObject) {
    let delegate: *mut AnyObject = msg_send![wk_webview, UIDelegate];
    let Some(delegate) = delegate.as_ref() else {
        return;
    };
    let class = ptr::from_ref::<AnyClass>(delegate.class()).cast_mut();

    type AlertImp = unsafe extern "C-unwind" fn(
        &AnyObject,
        Sel,
        &AnyObject,
        &NSString,
        &AnyObject,
        &Block<dyn Fn()>,
    );
    type ConfirmImp = unsafe extern "C-unwind" fn(
        &AnyObject,
        Sel,
        &AnyObject,
        &NSString,
        &AnyObject,
        &Block<dyn Fn(Bool)>,
    );
    type PromptImp = unsafe extern "C-unwind" fn(
        &AnyObject,
        Sel,
        &AnyObject,
        &NSString,
        *mut NSString,
        &AnyObject,
        &Block<dyn Fn(*mut NSString)>,
    );
    type CloseImp = unsafe extern "C-unwind" fn(&AnyObject, Sel, &AnyObject);

    add_method(
        class,
        sel!(webView:runJavaScriptAlertPanelWithMessage:initiatedByFrame:completionHandler:),
        std::mem::transmute::<AlertImp, Imp>(run_alert),
        c"v@:@@@@?",
    );
    add_method(
        class,
        sel!(webView:runJavaScriptConfirmPanelWithMessage:initiatedByFrame:completionHandler:),
        std::mem::transmute::<ConfirmImp, Imp>(run_confirm),
        c"v@:@@@@?",
    );
    add_method(
        class,
        sel!(webView:runJavaScriptTextInputPanelWithPrompt:defaultText:initiatedByFrame:completionHandler:),
        std::mem::transmute::<PromptImp, Imp>(run_prompt),
        c"v@:@@@@@?",
    );
    add_method(
        class,
        sel!(webViewDidClose:),
        std::mem::transmute::<CloseImp, Imp>(web_view_did_close),
        c"v@:@",
    );
}

unsafe fn add_method(class: *mut AnyClass, name: Sel, imp: Imp, types: &CStr) {
    class_addMethod(class, name, imp, types.as_ptr());
}

fn new_alert(
    mtm: MainThreadMarker,
    message: &NSString,
    buttons: &[&NSString],
) -> Retained<NSAlert> {
    let alert = NSAlert::new(mtm);
    alert.setMessageText(message);
    for title in buttons {
        alert.addButtonWithTitle(title);
    }
    alert
}

unsafe extern "C-unwind" fn run_alert(
    _this: &AnyObject,
    _cmd: Sel,
    _webview: &AnyObject,
    message: &NSString,
    _frame: &AnyObject,
    completion: &Block<dyn Fn()>,
) {
    if let Some(mtm) = MainThreadMarker::new() {
        new_alert(mtm, message, &[ns_string!("OK")]).runModal();
    }
    completion.call(());
}

unsafe extern "C-unwind" fn run_confirm(
    _this: &AnyObject,
    _cmd: Sel,
    _webview: &AnyObject,
    message: &NSString,
    _frame: &AnyObject,
    completion: &Block<dyn Fn(Bool)>,
) {
    let confirmed = MainThreadMarker::new().is_some_and(|mtm| {
        new_alert(mtm, message, &[ns_string!("OK"), ns_string!("Cancel")]).runModal()
            == NSAlertFirstButtonReturn
    });
    completion.call((Bool::new(confirmed),));
}

unsafe extern "C-unwind" fn run_prompt(
    _this: &AnyObject,
    _cmd: Sel,
    _webview: &AnyObject,
    prompt: &NSString,
    default_text: *mut NSString,
    _frame: &AnyObject,
    completion: &Block<dyn Fn(*mut NSString)>,
) {
    let Some(mtm) = MainThreadMarker::new() else {
        completion.call((ptr::null_mut(),));
        return;
    };
    let alert = new_alert(mtm, prompt, &[ns_string!("OK"), ns_string!("Cancel")]);
    let field =
        NSTextField::textFieldWithString(default_text.as_ref().unwrap_or(ns_string!("")), mtm);
    field.setFrameSize(NSSize::new(280.0, 24.0));
    alert.setAccessoryView(Some(&field));
    alert.window().setInitialFirstResponder(Some(&field));

    if alert.runModal() == NSAlertFirstButtonReturn {
        let value = field.stringValue();
        completion.call((Retained::as_ptr(&value).cast_mut(),));
    } else {
        completion.call((ptr::null_mut(),));
    }
}

unsafe extern "C-unwind" fn web_view_did_close(_this: &AnyObject, _cmd: Sel, webview: &AnyObject) {
    let window: *mut AnyObject = msg_send![webview, window];
    if !window.is_null() {
        let _: () = msg_send![window, performClose: ptr::null::<AnyObject>()];
    }
}
