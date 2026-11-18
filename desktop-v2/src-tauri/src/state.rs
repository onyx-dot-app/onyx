use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use crate::api::Api;
use crate::config::ConfigStore;
use crate::session_store;

pub struct AppState {
    pub config: ConfigStore,
    pub api: Api,
    // Cached so the keychain is read once per run.
    token: Mutex<Option<(String, String)>>,
    /// Bumped when a session ends (sign-out, server change). Work that started
    /// under an older value is stale and must not save tokens or open windows.
    epoch: AtomicU64,
    /// The server's session cookie name, by server origin.
    cookie_name: Mutex<Option<(String, String)>>,
}

impl AppState {
    pub fn new(config: ConfigStore) -> Self {
        Self {
            config,
            api: Api::new(),
            token: Mutex::new(None),
            epoch: AtomicU64::new(0),
            cookie_name: Mutex::new(None),
        }
    }

    pub fn epoch(&self) -> u64 {
        self.epoch.load(Ordering::SeqCst)
    }

    /// Marks every sign-in or renewal still in flight as stale.
    pub fn end_epoch(&self) {
        self.epoch.fetch_add(1, Ordering::SeqCst);
    }

    /// The cookie the server's web UI reads its session from. Servers can
    /// rename it (`AUTH_COOKIE_NAME`); older servers do not report it. An
    /// error means the server could not say: the caller must not guess, or
    /// the web UI would show a valid session as signed out.
    pub async fn cookie_name(&self, server: &str) -> Result<String, String> {
        if let Some((cached_server, name)) = self
            .cookie_name
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .as_ref()
        {
            if cached_server == server {
                return Ok(name.clone());
            }
        }
        // Retried, and only a name the server reported is cached.
        let mut last_error = String::new();
        for attempt in 0..3 {
            if attempt > 0 {
                tokio::time::sleep(std::time::Duration::from_millis(500)).await;
            }
            match self.api.session_cookie_name(server).await {
                Ok(name) => {
                    *self.cookie_name.lock().unwrap_or_else(|p| p.into_inner()) =
                        Some((server.to_string(), name.clone()));
                    return Ok(name);
                }
                Err(e) => last_error = e,
            }
        }
        Err(last_error)
    }

    /// The cookie name already looked up for `server`, or the default.
    pub fn cached_cookie_name(&self, server: &str) -> String {
        match self
            .cookie_name
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .as_ref()
        {
            Some((cached_server, name)) if cached_server == server => name.clone(),
            _ => crate::api::DEFAULT_SESSION_COOKIE.to_string(),
        }
    }

    pub fn server(&self) -> Result<String, String> {
        self.config
            .get()
            .server_url
            .ok_or_else(|| "No server is configured.".to_string())
    }

    pub fn token(&self, server: &str) -> Option<String> {
        let mut cache = self.token.lock().unwrap_or_else(|p| p.into_inner());
        if let Some((cached_server, token)) = cache.as_ref() {
            if cached_server == server {
                return Some(token.clone());
            }
        }
        let token = session_store::load(server)?;
        *cache = Some((server.to_string(), token.clone()));
        Some(token)
    }

    /// Saves a new sign-in's token if the session it started in (`epoch`) is
    /// still current, then starts a new epoch. The check and the save happen
    /// under one lock, so of two sign-ins that finish together only the first
    /// is kept. Returns `Ok(false)` for a stale sign-in.
    pub fn commit_sign_in(&self, server: &str, token: &str, epoch: u64) -> Result<bool, String> {
        let mut cache = self.token.lock().unwrap_or_else(|p| p.into_inner());
        if self.epoch() != epoch || self.server().ok().as_deref() != Some(server) {
            return Ok(false);
        }
        session_store::store(server, token)?;
        *cache = Some((server.to_string(), token.to_string()));
        self.end_epoch();
        Ok(true)
    }

    /// Replaces `old` with `new` only if `old` is still the stored session;
    /// a sign-out or a new sign-in during a renewal wins. Returns whether it
    /// replaced the token. If the keychain cannot save it, the new token is
    /// still used for this run (the session stays usable) and the failure is
    /// logged; the next launch starts from the token saved before.
    pub fn replace_token(&self, server: &str, old: &str, new: &str) -> bool {
        let mut cache = self.token.lock().unwrap_or_else(|p| p.into_inner());
        if cache.as_ref() != Some(&(server.to_string(), old.to_string())) {
            return false;
        }
        if let Err(e) = session_store::store(server, new) {
            log::warn!("could not save the renewed session: {e}");
        }
        *cache = Some((server.to_string(), new.to_string()));
        true
    }

    /// Ends the session: takes its token, clears it and starts a new epoch
    /// under the lock `commit_sign_in` holds, so a sign-in that finishes at the
    /// same time is either signed out here or stale. Returns the token (for
    /// the server logout) and the result of clearing the stored one.
    pub fn end_session(&self, server: &str) -> (Option<String>, Result<(), String>) {
        let mut cache = self.token.lock().unwrap_or_else(|p| p.into_inner());
        let token = match cache.take() {
            Some((cached_server, token)) if cached_server == server => Some(token),
            _ => session_store::load(server),
        };
        let cleared = session_store::clear(server);
        self.end_epoch();
        (token, cleared)
    }

    /// Clears a token the server rejected, unless a new sign-in replaced it.
    /// Returns whether the rejected token was still the session.
    pub fn clear_rejected_token(&self, server: &str, rejected: &str) -> Result<bool, String> {
        // Held until the keychain entry is gone, so a concurrent `token()`
        // cannot load the old token back into the cache.
        let mut cache = self.token.lock().unwrap_or_else(|p| p.into_inner());
        let current = match cache.as_ref() {
            Some((cached_server, token)) if cached_server == server => Some(token.clone()),
            _ => session_store::load(server),
        };
        if current.as_deref() != Some(rejected) {
            return Ok(false);
        }
        *cache = None;
        session_store::clear(server).map(|()| true)
    }

    /// The server and token for an authenticated call.
    pub fn session(&self) -> Result<(String, String), String> {
        let server = self.server()?;
        let token = self
            .token(&server)
            .ok_or_else(|| "Sign in first.".to_string())?;
        Ok((server, token))
    }
}
