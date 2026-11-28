//! Server sign-outs that could not reach the server. The token stays in
//! memory only and the sign-out is tried again while the app runs: a token
//! the user signed out of is not written back to the keychain.

use std::time::Duration;

use tauri::{AppHandle, Manager};

use crate::state::AppState;

/// Seconds between tries; the last step repeats.
const RETRY_SECS: [u64; 5] = [15, 30, 60, 120, 300];

/// Ends the session on `server`. Returns false if the server could not be
/// reached; the sign-out is then tried again in the background.
pub async fn end_server_session(app: &AppHandle, server: &str, token: &str) -> bool {
    if app.state::<AppState>().api.logout(server, token).await {
        return true;
    }
    let app = app.clone();
    let (server, token) = (server.to_string(), token.to_string());
    tauri::async_runtime::spawn(async move {
        for step in 0.. {
            let secs = RETRY_SECS[usize::min(step, RETRY_SECS.len() - 1)];
            tokio::time::sleep(Duration::from_secs(secs)).await;
            if app.state::<AppState>().api.logout(&server, &token).await {
                log::info!("ended the earlier session on the server");
                return;
            }
        }
    });
    false
}
