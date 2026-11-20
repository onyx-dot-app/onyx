//! Host-only session cookie for WebKit.
//!
//! wry's `set_cookie` always sets an explicit `Domain`. WebKit then stores the
//! cookie but never sends it to `localhost`, so a local server sees no session.
//! A cookie built from `OriginURL` (and no `Domain`) is host-only, which is what
//! the server itself would have set.

use std::sync::mpsc;
use std::time::Duration;

use block2::RcBlock;
use objc2::rc::Retained;
use objc2::runtime::AnyObject;
use objc2::{class, msg_send};
use objc2_foundation::{NSDictionary, NSString};
use tauri::WebviewWindow;
use url::Url;

pub fn set_session_cookie(
    window: &WebviewWindow,
    server: &Url,
    name: &str,
    value: &str,
) -> Result<(), String> {
    store_cookie(window, server, name, value, false)
}

/// Expires the host-only session cookie (sign-out).
pub fn clear_session_cookie(
    window: &WebviewWindow,
    server: &Url,
    name: &str,
) -> Result<(), String> {
    store_cookie(window, server, name, "", true)
}

fn store_cookie(
    window: &WebviewWindow,
    server: &Url,
    name: &str,
    value: &str,
    expire: bool,
) -> Result<(), String> {
    let (tx, rx) = mpsc::channel::<bool>();
    let origin = server.origin().ascii_serialization();
    let secure = server.scheme() == "https";
    let name = name.to_string();
    let value = value.to_string();

    window
        .with_webview(move |webview| {
            // A present `Secure` key makes the cookie secure whatever its value,
            // so it is only added for https servers.
            let mut pairs: Vec<(&str, &str)> = vec![
                ("Name", name.as_str()),
                ("Value", value.as_str()),
                ("Path", "/"),
                ("OriginURL", origin.as_str()),
                ("HttpOnly", "TRUE"),
                ("SameSite", "lax"),
            ];
            if secure {
                pairs.push(("Secure", "TRUE"));
            }
            if expire {
                pairs.push(("Max-Age", "0"));
            }
            let keys: Vec<Retained<NSString>> =
                pairs.iter().map(|(k, _)| NSString::from_str(k)).collect();
            let values: Vec<Retained<NSString>> =
                pairs.iter().map(|(_, v)| NSString::from_str(v)).collect();
            let key_refs: Vec<&NSString> = keys.iter().map(|k| &**k).collect();
            let value_refs: Vec<&NSString> = values.iter().map(|v| &**v).collect();
            let properties = NSDictionary::from_slices(&key_refs, &value_refs);

            // SAFETY: `with_webview` runs on the main thread with a live WKWebView;
            // every message below is a documented WebKit/Foundation API.
            unsafe {
                let wk_webview = webview.inner().cast::<AnyObject>();
                let configuration: *mut AnyObject = msg_send![wk_webview, configuration];
                let data_store: *mut AnyObject = msg_send![configuration, websiteDataStore];
                let cookie_store: *mut AnyObject = msg_send![data_store, httpCookieStore];
                let cookie: *mut AnyObject =
                    msg_send![class!(NSHTTPCookie), cookieWithProperties: &*properties];
                if cookie.is_null() || cookie_store.is_null() {
                    let _ = tx.send(false);
                    return;
                }
                let done = tx.clone();
                let completion = RcBlock::new(move || {
                    let _ = done.send(true);
                });
                let _: () =
                    msg_send![cookie_store, setCookie: cookie, completionHandler: &*completion];
            }
        })
        .map_err(|e| e.to_string())?;

    match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(true) => Ok(()),
        Ok(false) => Err("WebKit rejected the session cookie".into()),
        Err(_) => Err("timed out while setting the session cookie".into()),
    }
}
