use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use crate::api::Api;
use crate::config::{ConfigStore, TOKEN_NEEDS_RECORD};
use crate::policy::Policy;
use crate::session_store;

pub struct AppState {
    pub config: ConfigStore,
    pub api: Api,
    policy: Mutex<Policy>,
    // Cached so the keychain is read once per run.
    token: Mutex<Option<(String, String)>>,
    /// The server whose stored session could not be read this run, and why.
    read_failure: Mutex<Option<(String, String)>>,
    /// Bumped when a session ends (sign-out, server change). Work that started
    /// under an older value is stale and must not save tokens or open windows.
    epoch: AtomicU64,
    /// The server's session cookie name, by server origin.
    cookie_name: Mutex<Option<(String, String)>>,
    /// Launcher uploads in flight, by the page's upload id: true once cancelled.
    uploads: Mutex<HashMap<u64, Arc<AtomicBool>>>,
}

/// Ends an upload's entry in `AppState::uploads` when the upload ends.
pub struct UploadEntry<'a> {
    state: &'a AppState,
    id: u64,
    cancelled: Arc<AtomicBool>,
}

impl UploadEntry<'_> {
    pub fn cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }

    /// The flag `cancel_upload` sets, for work that outlives a borrow of the state.
    pub fn cancel_flag(&self) -> Arc<AtomicBool> {
        self.cancelled.clone()
    }
}

impl Drop for UploadEntry<'_> {
    fn drop(&mut self) {
        // A reloaded launcher can reuse the id for a newer upload; leave that one.
        let mut uploads = self.state.uploads.lock().unwrap_or_else(|p| p.into_inner());
        if uploads
            .get(&self.id)
            .is_some_and(|flag| Arc::ptr_eq(flag, &self.cancelled))
        {
            uploads.remove(&self.id);
        }
    }
}

impl AppState {
    pub fn new(config: ConfigStore, policy: Policy, api: Api) -> Self {
        Self {
            config,
            api,
            policy: Mutex::new(policy),
            token: Mutex::new(None),
            read_failure: Mutex::new(None),
            epoch: AtomicU64::new(0),
            cookie_name: Mutex::new(None),
            uploads: Mutex::new(HashMap::new()),
        }
    }

    /// Tracks an upload until the returned entry drops.
    pub fn begin_upload(&self, id: u64) -> UploadEntry<'_> {
        let cancelled = Arc::new(AtomicBool::new(false));
        self.uploads
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .insert(id, cancelled.clone());
        UploadEntry {
            state: self,
            id,
            cancelled,
        }
    }

    /// Marks an upload in flight as cancelled; other ids are ignored.
    pub fn cancel_upload(&self, id: u64) {
        if let Some(cancelled) = self
            .uploads
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .get(&id)
        {
            cancelled.store(true, Ordering::SeqCst);
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

    pub fn policy(&self) -> Policy {
        self.policy
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .clone()
    }

    pub fn set_policy(&self, policy: Policy) {
        *self.policy.lock().unwrap_or_else(|p| p.into_inner()) = policy;
    }

    /// The server in use; a managed one wins as `Policy::server` says.
    pub fn server(&self) -> Result<String, String> {
        self.policy()
            .server(self.config.get().server_url)
            .ok_or_else(|| "No server is configured.".to_string())
    }

    /// The launcher shortcut to register, or `None` if the launcher is off.
    pub fn hotkey(&self) -> Option<String> {
        self.policy().hotkey(self.config.get().hotkey())
    }

    pub fn token(&self, server: &str) -> Option<String> {
        let mut cache = self.token.lock().unwrap_or_else(|p| p.into_inner());
        if let Some((cached_server, token)) = cache.as_ref() {
            if cached_server == server {
                return Some(token.clone());
            }
        }
        let mut failure = self.read_failure.lock().unwrap_or_else(|p| p.into_inner());
        let token = read_token(
            &mut failure,
            server,
            session_store::KEEP_READ_FAILURE,
            || session_store::load(server),
        )?;
        if self.config.get().rejects_token(server, &token) {
            // A sign-out could not delete it: try again, and never use it.
            match session_store::clear(server) {
                Ok(()) => self.forget_rejected(server),
                Err(e) => log::warn!("could not delete a signed-out session token: {e}"),
            }
            return None;
        }
        if !self
            .config
            .get()
            .trusts_stored_token(server, TOKEN_NEEDS_RECORD)
        {
            // Left by an earlier install: remove it so it signs no one in.
            if let Err(e) = session_store::clear(server) {
                log::warn!("could not remove a session from an earlier install: {e}");
            }
            return None;
        }
        *cache = Some((server.to_string(), token.clone()));
        Some(token)
    }

    /// Why the stored session for `server` could not be read, if a read
    /// failed this run (Linux only, see `session_store::KEEP_READ_FAILURE`).
    pub fn read_failure(&self, server: &str) -> Option<String> {
        match self
            .read_failure
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .as_ref()
        {
            Some((failed_server, error)) if failed_server == server => Some(error.clone()),
            _ => None,
        }
    }

    /// Lets the next `token` call read the store again.
    pub fn forget_read_failure(&self) {
        *self.read_failure.lock().unwrap_or_else(|p| p.into_inner()) = None;
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
        save_then_record(
            TOKEN_NEEDS_RECORD,
            || session_store::store(server, token),
            || {
                self.config.update(|c| {
                    c.session_servers.insert(server.to_string());
                })
            },
        )?;
        *cache = Some((server.to_string(), token.to_string()));
        // The store now holds the new token, not the rejected one.
        self.forget_rejected(server);
        self.forget_read_failure();
        self.end_epoch();
        Ok(true)
    }

    fn forget_rejected(&self, server: &str) {
        if !self.config.get().rejected_tokens.contains_key(server) {
            return;
        }
        if let Err(e) = self.config.update(|c| {
            c.rejected_tokens.remove(server);
        }) {
            log::warn!("could not update the signed-out token record: {e}");
        }
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
        // The next renewal saves again. Until then the stored token is the
        // older one, and a failed sign-out rejects both.
        if let Err(e) = session_store::store(server, new) {
            log::warn!(
                "could not save the renewed session; the stored token is now older than the one in use: {e}"
            );
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
        let in_memory = match cache.take() {
            Some((cached_server, token)) if cached_server == server => Some(token),
            _ => None,
        };
        let stored = session_store::load(server).ok().flatten();
        let cleared = session_store::clear(server);
        if cleared.is_err() {
            // Kept in config, so neither token is used again, also after a
            // restart.
            let rejected =
                crate::config::tokens_to_reject(server, in_memory.as_deref(), stored.as_deref());
            if !rejected.is_empty() {
                if let Err(e) = self.config.update(|c| {
                    c.rejected_tokens
                        .entry(server.to_string())
                        .or_default()
                        .extend(rejected);
                }) {
                    log::warn!("could not record the signed-out token: {e}");
                }
            }
        }
        let token = in_memory.or(stored);
        self.forget_read_failure();
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
            _ => session_store::load(server).ok().flatten(),
        };
        if current.as_deref() != Some(rejected) {
            return Ok(false);
        }
        *cache = None;
        session_store::clear(server).map(|()| true)
    }

    /// Runs `f` only if session `epoch` is still current. The check and `f`
    /// hold the lock `end_session` takes, so a sign-out cannot end the session
    /// between them.
    pub fn while_current<T>(&self, epoch: u64, f: impl FnOnce() -> T) -> Option<T> {
        let _cache = self.token.lock().unwrap_or_else(|p| p.into_inner());
        (self.epoch() == epoch).then(f)
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

/// Saves a new token, then records that this install saved it. A token that
/// another install left must not get a record before the new token replaces
/// it. If the record fails, the next launch rejects the new token.
fn save_then_record(
    needs_record: bool,
    save: impl FnOnce() -> Result<(), String>,
    record: impl FnOnce() -> Result<(), String>,
) -> Result<(), String> {
    save()?;
    if needs_record {
        record()?;
    }
    Ok(())
}

/// Reads the stored token with `load`. A failed read for `server` that
/// `keep_failure` keeps is not tried again: the caller gets `None`.
fn read_token(
    failure: &mut Option<(String, String)>,
    server: &str,
    keep_failure: bool,
    load: impl FnOnce() -> Result<Option<String>, String>,
) -> Option<String> {
    if failure.as_ref().is_some_and(|(failed, _)| failed == server) {
        return None;
    }
    match load() {
        Ok(token) => token,
        Err(e) => {
            log::warn!("could not read the stored session: {e}");
            if keep_failure {
                *failure = Some((server.to_string(), e));
            }
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[test]
    fn token_is_saved_before_it_is_recorded() {
        let steps = RefCell::new(Vec::new());
        save_then_record(
            true,
            || {
                steps.borrow_mut().push("save");
                Ok(())
            },
            || {
                steps.borrow_mut().push("record");
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(*steps.borrow(), ["save", "record"]);
    }

    #[test]
    fn failed_save_writes_no_record() {
        let recorded = RefCell::new(false);
        let result = save_then_record(
            true,
            || Err("no store".to_string()),
            || {
                *recorded.borrow_mut() = true;
                Ok(())
            },
        );
        assert!(result.is_err());
        assert!(!*recorded.borrow());
    }

    #[test]
    fn no_record_where_none_is_required() {
        save_then_record(false, || Ok(()), || panic!("recorded")).unwrap();
    }

    #[test]
    fn a_kept_read_failure_is_not_tried_again() {
        let mut failure = None;
        let mut reads = 0;
        for _ in 0..3 {
            let token = read_token(&mut failure, "https://a", true, || {
                reads += 1;
                Err("locked".to_string())
            });
            assert_eq!(token, None);
        }
        assert_eq!(reads, 1, "one unlock prompt per run");
        assert_eq!(failure, Some(("https://a".into(), "locked".into())));

        // Another server reads its own entry.
        let token = read_token(&mut failure, "https://b", true, || {
            Ok(Some("t".to_string()))
        });
        assert_eq!(token.as_deref(), Some("t"));
    }

    #[test]
    fn a_failure_that_is_not_kept_is_tried_again() {
        let mut failure = None;
        let mut reads = 0;
        for _ in 0..2 {
            read_token(&mut failure, "https://a", false, || {
                reads += 1;
                Err("denied".to_string())
            });
        }
        assert_eq!(reads, 2);
        assert_eq!(failure, None);
    }
}
