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
    /// rename it (`AUTH_COOKIE_NAME`); older servers do not report it.
    pub async fn cookie_name(&self, server: &str) -> String {
        if let Some((cached_server, name)) = self
            .cookie_name
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .as_ref()
        {
            if cached_server == server {
                return name.clone();
            }
        }
        // A brief metadata failure would otherwise give the web UI the wrong
        // cookie and show a valid session as signed out: retry, and cache
        // only a name the server reported.
        let mut last_error = String::new();
        for attempt in 0..3 {
            if attempt > 0 {
                tokio::time::sleep(std::time::Duration::from_millis(500)).await;
            }
            match self.api.session_cookie_name(server).await {
                Ok(name) => {
                    *self.cookie_name.lock().unwrap_or_else(|p| p.into_inner()) =
                        Some((server.to_string(), name.clone()));
                    return name;
                }
                Err(e) => last_error = e,
            }
        }
        log::warn!("could not read the session cookie name: {last_error}");
        crate::api::DEFAULT_SESSION_COOKIE.to_string()
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

    pub fn set_token(&self, server: &str, token: &str) -> Result<(), String> {
        session_store::store(server, token)?;
        *self.token.lock().unwrap_or_else(|p| p.into_inner()) =
            Some((server.to_string(), token.to_string()));
        Ok(())
    }

    pub fn clear_token(&self, server: &str) -> Result<(), String> {
        // Held until the keychain entry is gone, so a concurrent `token()`
        // cannot load the old token back into the cache.
        let mut cache = self.token.lock().unwrap_or_else(|p| p.into_inner());
        *cache = None;
        session_store::clear(server)
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
