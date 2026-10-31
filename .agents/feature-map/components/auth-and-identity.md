# Auth and Identity

> Who is making a request. It covers every way a person or a machine proves
> identity, how a session lives and ends, the OAuth provider and outgoing action
> OAuth, the user lifecycle, and the SSRF guard for outbound fetches.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE has password, Google, OIDC and SAML login, sessions, API keys,
PATs, the OAuth provider and action OAuth. EE adds SCIM, domain-verified SSO
routing and the cloud superuser. A second enabled SSO provider needs the
Business tier.

---

## User experience

- **A person signing in** uses email and password, or a Google, OIDC or SAML
  button, as the admin configured. On Onyx Cloud one login page serves every
  workspace: the user types an email first, and the page shows the SSO buttons
  of the workspace the user belongs to. A new user goes to the workspace that
  verified their email domain. An unknown email gets the same answer as an
  email with no SSO, so the page cannot be used to find workspaces.
- **The first person to register** in a new deployment or workspace becomes its
  admin. Later signups may need an invite, an allowed email domain or a
  captcha.
- **A session ends** in a way the user can tell apart. With the default Redis
  session store, log out, an admin password reset and an expired session each
  show a "session ended" message with its reason. A password change signs out
  every other session and keeps the current one. Every password change or
  reset also revokes all of that user's PATs.
- **An anonymous visitor** can chat without an account when an admin turns
  this on ([[authorization#anonymous-stays-on-chat]]).
- **An admin** configures SSO providers, password rules and other security
  settings, creates service accounts with API keys, and connects an IdP through
  SCIM. What each person may do is set through groups ([[authorization]]).
- **A developer or script** sends a PAT or an API key as a bearer token. A PAT
  acts as its owner. An API key acts as its service account. A service account
  cannot sign in or reset a password; a forgot-password request for one gets
  the same answer as an unknown address
  (`db/enums.py:AccountType.allows_password_login`).
- **A third-party app, such as an MCP client,** sends the user to an Onyx
  consent page. After the user allows it, the app acts as that user. The user
  can see and disconnect these apps.
- **A user of a custom action** connects their own third-party account through
  OAuth. If an admin changes the action's OAuth settings while the user is
  connecting, the connection fails and the user starts again.

---

## Scope

This component owns identity: login flows and SSO provider rows, sessions and
their revocation, non-human credentials as identities (API keys with service
accounts, PATs, SCIM tokens), the OAuth provider (Onyx as authorization
server), outgoing OAuth for custom actions, the security settings store with
the SSRF protection level, the SSRF guard that every outbound fetch uses, and
user creation, activation and deletion.

Neighbours own:
- [[authorization]]: what an identity may do, PAT scope enforcement and group
  grants.
- [[multi-tenancy]]: the tenant of a request.
- [[access-control]]: which documents the user can retrieve.
- [[rate-and-usage-limits]]: signup, invite and auth-route rate limits.
- [[billing]]: seat counts and the Community downgrade that deletes API keys
  and turns off SCIM tokens.
- [[mcp-and-custom-tools]]: MCP credential resolution.
- [[mcp-server]]: the allowlist of routes that an OAuth-provider token may
  reach.
- [[editions-and-gating]]: tier checks.

---

## Architecture

**Identity resolution.** Every authenticated route depends on
`onyx/auth/users.py:optional_user`, through `current_user`,
`current_chat_accessible_user` or `require_permission`.
`_resolve_optional_user` tries the credentials in this order:

```
OAuth-provider bearer (onyx_oat_ prefix)    -> that grant's user; never falls back to the cookie
session cookie or mobile bearer             -> fastapi-users strategy (AUTH_BACKEND)
JWT bearer (if a JWT public key URL is set) -> _check_for_saml_and_jwt
PAT                                         -> its owner; request.state.token_scopes = pat.scopes
API key                                     -> its SERVICE_ACCOUNT user, only if that user is active
```

Each branch sets `request.state.usage_credential`, which usage limits and audit
read. `optional_user` then commits its read transaction, so a streamed chat
response does not hold the auth connection for minutes.

**Sessions.** `AUTH_BACKEND` selects Redis (default), Postgres or JWT
strategies in `onyx/auth/users.py`. A Redis session value records its own
expiry. Logout overwrites it with a tombstone
(`auth/session_tokens.py:build_session_tombstone_value`). The cookie lives a
grace period past the session, so a dead token still arrives and
`classify_session_token_value` can name the reason. The web client
(`web/src/lib/auth/hooks.ts:useSessionWatcher`) turns that 403 into the
session-ended message.

**SSO.** `SSOProvider` rows hold the OIDC, Google and SAML settings. Login
routes load the row on each request (`server/oidc_multi.py`,
`server/saml_multi.py`), so a new provider needs no restart. SAML has one
callback for all providers and finds the provider from the response issuer
(`_resolve_saml_provider_by_issuer`). Cloud discovery
(`server/sso_discovery.py:discover_sso_providers`) maps the email to a
workspace, by membership first and verified domain second, and returns a
short-lived signed workspace token that pins the next authorize call to that
tenant. Mobile SSO puts its parameters in the signed OAuth state and returns a
one-time PKCE-bound code to the app (`auth/mobile_sso/`, [[mobile-app]]).
The custom login's token refresh
(`backend/ee/onyx/server/enterprise_settings/api.py:refresh_access_token`) sits
in the enterprise settings router, but it is an identity rule: `_caller_owns_subject`
binds the subject in the request body to the caller and to the current tenant
before `oauth_callback` runs.

**OAuth provider.** The routes mount only when `WEB_DOMAIN` is HTTPS, or HTTP on
a loopback host (`oauth_provider/config.py:OAUTH_PROVIDER_SETTINGS`). The
consent routes (`server/oauth_provider/api.py`) bind a pending request to one
user, tenant, login session and CSRF token. Grants and tokens live in the
tenant schema; registered clients live in the shared catalog on cloud.
Workspace membership is checked again at consent, on refresh
(`server/oauth_provider/provider.py:_with_authorized_refresh`) and on each
token use.

**Outgoing OAuth for actions.** `oauth/authorization_attempt.py` stores a
user-bound pending attempt, which the callback consumes before it calls the
provider. `oauth/protocol.py:build_authorization_url` builds the URL.
Configured extra parameters cannot override `state`, client identity, redirect
URI, scope or PKCE fields.

**Users that never logged in.** Doc sync and group sync create `User` rows for
unknown emails, so that access is ready at signup ([[permission-sync]]).

---

## Contracts and traps

1. `raw-credentials-hashed` **Raw credentials are shown once and stored only
   as hashes.** PATs (`auth/pat.py`), SCIM tokens
   (`ee/onyx/server/scim/auth.py`) and API keys (`ApiKey.hashed_api_key`) keep
   only a hash. Never log, cache or return a raw value after creation.
2. `logout-writes-tombstone` **Redis logout must write a tombstone.**
   `onyx/auth/users.py:TenantAwareRedisStrategy.destroy_token` and
   `onyx/auth/users.py:TenantAwareRedisStrategy.revoke_user_sessions`
   overwrite the key. Deleting it makes a sign-out look like a lost key.
   Postgres sessions delete the `AccessToken` row, so they cannot name a
   reason. JWT sessions cannot be revoked: logout and
   `UserManager.revoke_sessions` do nothing for them. Test every
   `AUTH_BACKEND` when you change session code.
3. `password-write-revokes-pats` **Password writes revoke PATs in the same
   commit.** `onyx/auth/users.py:UserManager._update` calls
   `db/pat.py:revoke_all_pats_for_user__no_commit`. This includes Craft PATs; a
   running sandbox gets a new PAT at its next reservation. API keys belong to
   service accounts and stay valid.
4. `outbound-fetch-uses-ssrf-guard` **Every fetch from the Onyx backend to a
   URL that an admin, a user or the LLM sets goes through the SSRF guard.** Use
   `utils/url.py:ssrf_safe_get` or `ssrf_safe_request`, which resolve DNS once
   and connect to the checked IP, so a rebinding DNS server cannot swap the
   target. A client that cannot use them checks the URL with
   `validate_outbound_http_url` before each request and after each redirect.
   A Playwright page calls `utils/playwright_fetch.py:install_ssrf_guard`
   before it navigates.
   Take the flags from the admin SSRF protection level:
   `server/security/models.py:outbound_ssrf_params` for LLM-initiated and
   admin-endpoint paths, `connector_ssrf_enforced` for connector URLs. Most
   callers read the level with the default env fallback; only
   `sandbox_proxy/destination_policy.py` reads it strictly
   ([[#security-settings-strict-read]]). Admin-set identity URLs
   use `auth/sso_url_guard.py:validate_idp_url` and
   `validate_discovered_endpoints`; env-pinned URLs are trusted.
   `auth/jwt.py:verify_jwt_token` also throttles public-key refetches, because a
   caller can force one. List the current callers with
   `git grep -l 'ssrf_safe_\|validate_outbound_http_url' backend`.
5. `user-auth-secret-signs-many` **`USER_AUTH_SECRET` signs many things.** It
   signs reset and verify tokens, OAuth state, the SSO workspace token,
   anonymous-user JWTs and the DNS proof for SSO domains
   (`ee/onyx/auth/sso_domain_verification.py:verification_record`).
   `onyx/auth/users.py:verify_user_auth_secret` refuses to start with an empty value unless
   `DEV_MODE` or `INTEGRATION_TESTS_MODE` is set. A rotation breaks every
   published domain proof, and
   `ee/onyx/auth/sso_domain_verification.py:revalidate_tenant_domains` drops those
   domains from SSO routing.
6. `scim-authenticates-token` **SCIM authenticates the token, not a user.**
   `ee/onyx/server/scim/auth.py:verify_scim_token` returns the `ScimToken` row
   and rejects an inactive token. Keep SCIM out of the `current_user` chain.
7. `oauth-provider-state` **OAuth-provider codes and consent requests are
   single-use, and each piece of state has one cache.**
   `oauth_provider/attempts.py:consume_authorization_code` and
   `consume_authorization_request` read with `getdel`; a two-step read and
   delete allows a second redemption. The same holds for action OAuth attempts.
   Only pre-sign-in state goes to `get_shared_cache_backend`: the pending
   request, which holds client fields only, and the first-tenant claim. Consent
   bindings and codes hold user data and go to the tenant's cache. A code key is
   a hash of the whole code, so a code with an edited tenant prefix misses.
   Never move a binding or a code to the shared cache. The protocol routes are
   in `TENANT_RESOLUTION_SKIP_PATHS`, so `token` and `revoke` in
   `server/oauth_provider/protocol.py` set `CURRENT_TENANT_ID_CONTEXTVAR` from
   the code or token before they touch storage. New storage access must too.
8. `sso-provider-name-is-link-key` **SSO provider names are link keys, and a
   delete must see every in-flight login.** The provider `name` is the URL path
   segment and the `oauth_name` on linked accounts, so
   `db/sso_provider.py:update_sso_provider` cannot change it. Delete removes the
   links, and on cloud the catalog copies
   (`ee/onyx/db/user_tenant_mapping.py:forget_oauth_identities`), so another
   provider can claim those accounts by email. An OIDC or Google login
   share-locks its provider row before each link write
   (`onyx/auth/users.py:UserManager._hold_sso_provider`). A delete then waits for
   in-flight logins and removes their links too, and a login whose provider is
   gone fails before it writes. A new link write path that skips the lock lets
   links survive a delete. The admin API refuses to disable or delete the last
   enabled provider while password login is off
   (`server/manage/sso/api.py:_reject_removing_last_sign_in`).
9. `sso-claim-windows-default-off` **Relinking and renamed-account claims stay
   closed unless an admin opens them.** A web-login user who already has a
   link, or who was renamed, cannot be claimed by an SSO login. The security
   settings `allow_same_provider_subject_relink` and
   `allow_renamed_account_claim` open these windows, because neither case
   proves the holder (`onyx/auth/users.py:UserManager.oauth_callback`). Both default
   to off in `server/security/store.py`. A disabled user is never linked.
10. `security-settings-strict-read` **Authorization decisions read security
    settings strictly.** `server/security/store.py:get_security_settings` falls
    back to env values when no tenant is set or the read fails, so the auth
    path survives a Postgres outage. A failed read never fills the cache. A
    security decision must pass `allow_fallback=False`, as
    `sandbox_proxy/destination_policy.py` does for the SSRF level. The default
    can silently apply env values for the tenant.
11. `action-oauth-config-fingerprint` **Action OAuth rejects a callback after a
    configuration change.** Initiate stores
    `server/features/oauth_config/api.py:_oauth_config_fingerprint`, which
    hashes all of `OAuthFlowParams`, PKCE and the redirect URI. The callback
    compares it, so a change while authorization is pending fails, and the
    user must start again. A field that changes the flow must live in
    `OAuthFlowParams`. A provider failure in the exchange returns 502
    `BAD_GATEWAY`. Traps: `/pkce-support` needs global `MANAGE_ACTIONS` and
    sends no client credentials; the test flow discards its tokens but leaves
    the grant at the provider.
12. `seat-lock-on-user-write` **User creation and activation take the seat
    lock.** Call `onyx/auth/users.py:enforce_seat_limit_locked` on the session that
    writes the user, and `_invalidate_license_cache_after_seat_change` after a
    seat change ([[billing#seat-lock-before-write]],
    [[billing#two-seat-counts]]).
13. `logout-clears-craft-storage` **Logout clears Craft browser storage by
    prefix.** `web/src/lib/users/svc.ts:logout` removes every `sessionStorage`
    key that starts with `onyx:craft:` or `onyx:draft:craft:` and clears the
    Craft thumbnail cache. New Craft browser storage must use the
    `onyx:craft:` prefix, or it survives logout ([[craft-frontend]]).

---

## Known issues

- **User deletion fails while the user owns private skills**
  (`db/users.py:delete_user_from_db__no_commit`). The admin must transfer or
  delete them first.
- **Anonymous access can turn itself off.** `auth/users.py` reads
  `anonymous_user_enabled` from the same cache key as the settings store, and
  the key expires ([[chat-preferences]] Known issues).

---

## Dependencies

- [[multi-tenancy]]: the tenant decides which schema's `User`, provider and
  grant rows a login reads.
- [[authorization]]: `require_permission` gates the admin routes for SSO,
  security settings, API keys and SCIM.
- [[editions-and-gating]]: tier checks gate extra SSO providers and PAT
  scopes.
- [[billing]]: the seat limit on user creation and activation.

---

## Recipes

- `new-credential-type` **Add a credential type.** Copy the PAT path: a hashed table (`db/pat.py`),
  a branch in `_resolve_optional_user` that sets `usage_credential`, and a
  tenant prefix in `onyx/auth/utils.py:extract_tenant_from_auth_header` for
  cloud ([[multi-tenancy#tenant-from-auth-only]]). If it can carry scopes, set
  `request.state.token_scopes` and follow
  [[authorization#scoped-pat-fails-closed]].
- `new-security-setting` **Add a security setting.** Copy `allow_renamed_account_claim` through
  `server/security/models.py` and `server/security/store.py`; list the current
  settings in `SecuritySettings`. Read it with `allow_fallback=False` when it
  decides access ([[#security-settings-strict-read]]).
- `investigate-unexpected-signout` **Investigate "signed out unexpectedly".** Check `AUTH_BACKEND` first,
  because Postgres and JWT sessions keep no reason. With Redis, read the
  `detail` of the 403 that the browser received:
  `auth/session_tokens.py:classify_session_token_value` names the reason from
  the tombstone. No reason means the key was gone, which is not a logout
  ([[#logout-writes-tombstone]]).

---

## Verification

- Integration suites under `backend/tests/integration/tests/`: `auth/`,
  `api_key/`, `pat/`, `scim/`, `mobile_auth/`, `anonymous_user/`, `users/` and
  `mcp_oauth/`. Sessions, SSO and OAuth callbacks:
  `backend/tests/external_dependency_unit/auth/`. Web: `web/tests/e2e/auth/`.
- By hand, log out in one tab and act in another. The second tab must show the
  "signed out" reason.
