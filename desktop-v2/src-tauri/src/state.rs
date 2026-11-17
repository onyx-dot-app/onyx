use std::sync::Mutex;

use crate::api::Api;
use crate::config::ConfigStore;
use crate::session_store;

pub struct AppState {
    pub config: ConfigStore,
    pub api: Api,
    // Cached so the keychain is read once per run.
    token: Mutex<Option<(String, String)>>,
}

impl AppState {
    pub fn new(config: ConfigStore) -> Self {
        Self {
            config,
            api: Api::new(),
            token: Mutex::new(None),
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
        *self.token.lock().unwrap_or_else(|p| p.into_inner()) = None;
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
