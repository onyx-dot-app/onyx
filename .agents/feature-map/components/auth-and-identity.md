# Auth and Identity

> Who is making this request, and what are they allowed to do. Covers every way
> a human or a machine proves identity (password, OAuth/OIDC, SAML, API key,
> PAT, SCIM), how a session is held and expired, and the permission model that
> decides what an authenticated identity may do once inside.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** auth-and-identity
**Edition:** CE for password/OAuth/OIDC/SAML login, sessions, API keys, PATs, and
the `Permission`/`PermissionGrant` model. EE for multi-provider SSO rows,
domain-verified auto-provisioning, SCIM, and cloud superuser/control-plane
auth.
**Owns:**
`backend/onyx/auth/` (`users.py`, `permissions.py`, `scoped_permissions.py`,
`permission_projection.py`, `api_key.py`, `pat.py`, `jwt.py`, `session_tokens.py`,
`oidc_client.py`, `pkce.py`, `oauth_refresher.py`, `oauth_token_manager.py`,
`anonymous_user.py`, `invited_users.py`, `captcha.py`, `signup_rate_limit.py`,
`disposable_email_validator.py`, `sso_tenant_token.py`, `sso_url_guard.py`,
`login_claims_capture.py`, `mobile_sso/`, `schemas.py`, `constants.py`),
`backend/ee/onyx/auth/` (`users.py`, `sso_domain_verification.py`),
`backend/onyx/server/auth/`, `server/saml.py`, `server/saml_multi.py`,
`server/oidc_multi.py`, `server/sso_discovery.py`, `server/auth_check.py`,
`server/manage/sso/`, `server/manage/users.py`, `server/api_key/`,
`server/pat/`, `server/security/`, `backend/ee/onyx/server/scim/`,
`backend/ee/onyx/server/auth_check.py`,
`backend/onyx/db/users.py`, `db/auth.py`, `db/api_key.py`, `db/pat.py`,
`db/saml.py`, `db/sso_provider.py`, `db/permissions.py`,
`db/scoped_permissions.py`, `db/oauth_config.py`, `server/features/user_oauth_token/`,
`backend/onyx/oauth/`, the `User`/`PermissionGrant`/`ApiKey`/
`PersonalAccessToken`/`SSOProvider`/`SamlAccount`/`ScimToken`/`OAuthConfig`/
`OAuthUserToken` tables in `backend/onyx/db/models.py`.

**Does not own:** which *documents* an authenticated user can see. That is
[[access-control]]: this document supplies the `User` object and the
`Permission`/`AccountType` model access-control keys on; access-control owns
the ACL. Tenant resolution and cross-tenant isolation are
[[multi-tenancy]]. Rate limiting on chat/API usage is
[[rate-and-usage-limits]] (this document only covers signup and SSO-discovery
rate limits, which exist to slow abuse of *this* component's endpoints).

---

## 1. What the user experiences

A user signs in with email and password, or with a button for Google, a
generic OIDC provider, or SAML, depending on what an admin configured. On
Onyx Cloud, a single login page serves every workspace: the user types their
email first, and the page discovers which SSO buttons (if any) that
workspace exposes before showing them (`server/sso_discovery.py`). The first
person to register in a fresh deployment becomes an implicit admin (seeded
via `get_default_admin_user_emails_`, `backend/onyx/auth/users.py` and
`backend/ee/onyx/auth/users.py:get_default_admin_user_emails_`); after that,
new signups are ordinary users unless an admin invites them or a domain is
configured to auto-provision.

Once signed in, the session persists across page loads via a cookie, and
"log out" invalidates it immediately rather than waiting for expiry.
Native mobile clients get the same session in a header instead of a cookie
(`bearer_transport`, `backend/onyx/auth/users.py`). A signed-out
anonymous visitor can still use chat if an admin turned that on, with public
documents only.

An admin manages users and their capabilities from the admin panel: inviting
by email, assigning a user to groups (which is what actually grants
capabilities, see §3), configuring SSO providers, and issuing non-human
credentials (API keys for service integrations, personal access tokens for
scripts, SCIM for IdP-driven provisioning). There is no "set this user's
role" control that does anything: role assignment as a concept was replaced
by group membership plus account type (§3, §9).

A developer or script authenticates the same way over HTTP with a bearer
token instead of a cookie: an API key (admin-issued, tied to a service
account) or a personal access token (self-issued, optionally scope-limited,
for example to `use:llm_gateway` for [[llm-gateway]] or `craft_sandbox` for
the coding-agent sandbox).

---

## 2. Surfaces

### Login and session endpoints

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/auth/register` | fastapi-users register router | Public. Captcha, disposable-email, invite-list, and signup rate-limit checks run inside `UserManager.create` (`auth/users.py`). |
| POST | `/auth/login` | fastapi-users cookie/JWT/Redis login router | Public. Issues the session token per `AUTH_BACKEND`. |
| POST | `/auth/logout` | same router | Writes a tombstone value instead of deleting the Redis key (`session_tokens.py:build_session_tombstone_value`). |
| POST | `/auth/forgot-password`, `/auth/reset-password` | fastapi-users | Public, signed with `USER_AUTH_SECRET`. |
| POST | `/auth/request-verify-token`, `/auth/verify` | fastapi-users | Public. |
| GET | `/auth/type` | | Public. Tells the frontend which login flow to render before any session exists. |
| POST | `/auth/mobile/login`, `/auth/mobile/refresh`, `/auth/mobile/logout` | `server/auth/mobile.py` | Bearer-token mirror of the cookie flow for native clients. |
| POST | `/auth/mobile/sso/exchange` | `mobile_sso/sso_completion.py` via `server/auth/mobile.py` | Exchanges a one-time PKCE-bound code (minted after an OAuth/SAML callback) for the session token; declared public because the code itself is the credential. |
| GET | `/auth/oauth/authorize`, `/auth/oauth/callback` | fastapi-users OAuth router (`create_onyx_oauth_router`, `auth/users.py`) | Legacy single-provider Google OAuth. Still active; multi-provider is the newer path (below). |
| GET | `/auth/oidc/authorize`, `/auth/oidc/callback` | legacy single-provider OIDC router | Same relationship to the multi-provider router as OAuth above. |
| GET | `/auth/oidc/{provider_name}/authorize`, `/auth/oidc/{provider_name}/callback` | `server/oidc_multi.py` | DB-backed multi-provider OIDC/Google; resolves an `SSOProvider` row per request, so adding a provider needs no restart. |
| GET/POST | `/auth/saml/authorize`, `/auth/saml/{provider_name}/authorize`, `/auth/saml/callback`, `/auth/saml/logout` | `server/saml.py`, `server/saml_multi.py` | One issuer-resolved callback serves every configured SAML provider (`_resolve_saml_provider_by_issuer`). |
| POST | `/auth/sso/discover` | `server/sso_discovery.py` | Public, rate-limited. Answers uniformly for unknown/ambiguous/no-SSO addresses so it cannot be used to enumerate workspaces or providers (§5). |
| GET | `/auth/mobile/oauth/authorize`, `/auth/mobile/oauth/callback` | dedicated mobile Google OAuth | Callback targets the API server directly, not the web app. |
| POST | `/auth/captcha/oauth-verify` | `server/auth/captcha_api.py` | Public; the user is not yet authenticated when solving the pre-OAuth captcha. |

### Admin / self-service management endpoints

| Method | Path | Handler | Permission |
|---|---|---|---|
| CRUD | `/admin/api-key*` | `server/api_key/api.py` | `Permission.MANAGE_SERVICE_ACCOUNT_API_KEYS`. Creating or updating a key is **admin-equivalent by design**: `group_ids` is uncapped, so a holder can add a key to the Admin group (`api.py:create_api_key` comment). |
| GET | `/user/pats/scopes` | `server/pat/api.py:list_selectable_scopes` | `Permission.BASIC_ACCESS`. Drops `use:llm_gateway` from the list while the workspace `llm_gateway_enabled` setting is off. |
| GET/POST/DELETE | `/user/pats` | `server/pat/api.py` | List/create needs `CREATE_USER_API_KEYS` (create) or `BASIC_ACCESS` (list/delete); a user only ever sees/revokes their own. Minting a PAT with `use:llm_gateway` while the setting is off is rejected with `INVALID_INPUT` (`server/pat/api.py:_validate_assignable_scopes`). |
| GET/PUT | `/admin/security`, GET `/admin/security/pinned-fields` | `server/security/api.py` | `FULL_ADMIN_PANEL_ACCESS`. Workspace security overrides: password policy, `password_auth_enabled`, `valid_email_domains`, JWT validation fields, SSRF level, incognito availability, and `allow_connector_group_restrictions`. Env-pinned fields win over stored values. Turning on `allow_connector_group_restrictions` needs the Business tier. |
| CRUD | `/admin/user-group*` | `ee/onyx/server/user_group/api.py` | See [[access-control]] §2; this is where group membership, and thus `PermissionGrant`-derived capability, is actually assigned. |
| GET/POST/PATCH | `/admin/sso-providers*`, `/admin/sso-providers/{id}/domains` | `server/manage/sso/api.py` | `FULL_ADMIN_PANEL_ACCESS` (exact gating per route). Domain-routing SSO providers beyond the first require business tier (`_require_business_tier_for_additional_enabled_provider`). |
| POST | `/admin/sso-providers/{id}/domains/{domain}/verify` | same file | Triggers `ee/onyx/auth/sso_domain_verification.py:verify_domain_via_dns`. |
| GET/PATCH/DELETE | `/users/me`, `/users/{id}` | fastapi-users users router | Declared public in `auth_check.py`'s spec list because the route's *own* dependency enforces identity (self, or admin for `{id}`); see §5. |
| SCIM | `/scim/v2/*` | `ee/onyx/server/scim/api.py` | Bearer-token auth via `verify_scim_token` (`ee/onyx/server/scim/auth.py`), not user auth. Provisions/deprovisions users and groups from an IdP. |

### Environment configuration

| Variable | File | Default | Effect |
|---|---|---|---|
| `USER_AUTH_SECRET` | `configs/app_configs.py` | `""` | Signs password-reset/verification tokens, OAuth state, captcha cookies, the SSO tenant-pin token, and anonymous-user JWTs. `verify_user_auth_secret` (`auth/users.py`) refuses to start a real deployment with it empty; `DEV_MODE`/`INTEGRATION_TESTS_MODE` downgrade the refusal to a warning. |
| `SESSION_EXPIRE_TIME_SECONDS` | `configs/app_configs.py` | 7 days (`86400 * 7`) | Redis/JWT session lifetime; also read from the legacy `REDIS_AUTH_EXPIRE_TIME_SECONDS` name. |
| `AUTH_BACKEND` | `configs/app_configs.py` | `redis` | `redis` \| `postgres` \| `jwt`; selects `TenantAwareRedisStrategy` / `RefreshableDatabaseStrategy` / `SingleTenantJWTStrategy` (`auth/users.py`). |
| `SIGNUP_RATE_LIMIT_ENABLED` | `configs/app_configs.py` | | Gates `signup_rate_limit.py`; only enforced under `MULTI_TENANT`. |
| `CAPTCHA_ENABLED`, `RECAPTCHA_*` | `configs/app_configs.py` | | reCAPTCHA Enterprise on signup and pre-OAuth. |
| `DISPOSABLE_EMAIL_DOMAINS_URL` | `configs/app_configs.py` | | Remote disposable-domain blocklist, refreshed stale-while-revalidate. |
| `MOBILE_ALLOWED_REDIRECT_URIS` | `configs/app_configs.py` | | Allowlist mobile SSO completion redirects against. |
| `OIDC_DISCOVERY_CACHE_TTL_SECONDS` | `auth/oauth_refresher.py` | 3600 | OIDC discovery-document cache for token-refresh endpoint resolution. |

**Not env, admin-configured (DB rows):** `SSOProvider` rows
(`db/sso_provider.py`) hold the OAuth/OIDC/SAML settings the legacy
single-provider env vars (`OAUTH_CLIENT_ID`, `OPENID_CONFIG_URL`, and the
removed `AUTH_TYPE=google_oauth|oidc|saml`) used to. `verify_auth_setting`
(`auth/users.py`) only warns on the stale env values; it does not read
them.

---

## 3. Data model

```
User ──< OAuthAccount (fastapi-users; oauth_name + linked SSOProvider identity)
     ──< SamlAccount (encrypted_cookie, expires_at)
     ──< ApiKey (as owner_id and as the credential's own user_id)
     ──< PersonalAccessToken
     ──< User__UserGroup >── UserGroup ──< PermissionGrant
     ──< OAuthUserToken >── OAuthConfig  (per-tool/MCP OAuth, distinct from login OAuth)

SSOProvider ── encrypted `config` blob (protocol-specific) + allowed_email_domains
ScimToken   ── hashed bearer token for IdP-driven provisioning
```

### `User` (`backend/onyx/db/models.py`)

| Column | Meaning |
|---|---|
| `role` | **Legacy tombstone.** Type is `UserRole` (`auth/schemas.py`), column comment: "Legacy tombstone column: no longer read or written by application code. Kept nullable so a pure-code rollback keeps working." See §9. |
| `account_type` | `AccountType`: `STANDARD`, `SERVICE_ACCOUNT`, `BOT`, `EXT_PERM_USER`, `ANONYMOUS` (`db/enums.py`). `is_web_login()` excludes `BOT`/`EXT_PERM_USER`. `allows_password_login()` also excludes `SERVICE_ACCOUNT` and `ANONYMOUS`: password login and password reset refuse a service account, and a service account signs in only with its API key. Classifies *what kind of identity this is*, independent of `Permission`. |
| `effective_permissions` | JSONB list of granted `Permission` values, recomputed by `db/permissions.py:recompute_user_permissions__no_commit` whenever group membership or grants change. Expanded with implied permissions only at read time (`auth/permissions.py:get_effective_permissions`), never persisted expanded. |
| `is_group_manager` | Cached bool: does this user manage at least one non-default group. Refreshed in the same write as `effective_permissions`. The live equivalent of "curator." |
| `prior_emails` | Addresses this user was renamed away from; still match indexed document ACLs, so kept for [[access-control]]. |
| `oidc_expiry` | OIDC token expiry; `double_check_user` rejects an expired-and-not-explicitly-allowed session (`auth/users.py`). |

### `PermissionGrant` (`models.py`)

`(group_id, permission)` unique pair, `grant_source: GrantSource` (`USER` \|
`SCIM` \| `SYSTEM`), `granted_by`, `is_deleted`. The only place a `Permission`
is durably attached to anything; a user's `effective_permissions` is the
union of every non-deleted grant across every group they belong to, plus
`account_derived_permissions` (`db/permissions.py`, currently only:
a `SERVICE_ACCOUNT` in no group gets `WRITE_CHAT` directly, since it has no
group to draw chat scope from).

### `ApiKey` (`models.py`) and `PersonalAccessToken` (`models.py`)

| Column | ApiKey | PersonalAccessToken |
|---|---|---|
| Hash | `hashed_api_key` (SHA-256 hex, or salted `sha256_crypt` for the deprecated prefix) | `hashed_token` (SHA-256, `String(64)`) |
| Display | `api_key_display` (masked) | `token_display` (masked) |
| Owner vs. bearer | `user_id` (the synthetic service-account identity the key authenticates as) is distinct from `owner_id` (the human who created it) | `user_id` is the creator; a PAT always authenticates as its owner, there is no separate bearer identity |
| Scoping | Capability comes entirely from the service-account user's group memberships | `pat_type: PatType` (`USER` \| `CRAFT`); optional `scopes` (a list of `Permission`, `None` = unrestricted, capped to the user's own `effective_permissions` at check time via `require_permission`'s `token_scopes` path) |
| Expiry/revocation | No expiry column; deleted to revoke | `expires_at` (`NULL` = no expiration; revocation sets it to `NOW()`), `is_revoked` |

Both `hashed_api_key` and `hashed_token` are unique-constrained and are the
*only* copy of the credential in the database; the raw value is returned to
the caller exactly once, at creation (`server/pat/api.py:create_token`
comment: `"# ONLY time we return the raw token!"`).

### `SSOProvider` (`models.py`)

`name` (URL path segment, also stored as `oauth_name` on linked accounts:
renaming a provider orphans those links), `provider_type: SSOProviderType`,
`config: EncryptedJson` (protocol-specific: OAuth/OIDC client creds and
discovery URL, or SAML IdP metadata), `allowed_email_domains`, `enabled`.
Rows, not startup wiring: login routes resolve the row at request time.

### `SamlAccount` (`models.py`)

One-to-one with `User`. `encrypted_cookie` + `expires_at`: the SAML session
artifact, separate from the fastapi-users session token.

### `ScimToken` (`models.py`)

`hashed_token` (SHA-256), `token_display`. Authenticates the IdP's SCIM
client, not a `User`; `verify_scim_token` returns the `ScimToken` row itself,
and `ee/onyx/server/scim/auth.py` is explicit that it does not carry a
`User` dependency.

### `OAuthConfig` / `OAuthUserToken` (`models.py`)

Per-tool/MCP OAuth (for custom actions calling third-party APIs), unrelated
to login SSO. `client_id`/`client_secret` and the token blob are
`EncryptedString`/`EncryptedJson`.

---

## 4. How it works

### 4.1 Password login

```
POST /auth/register  → UserManager.create (auth/users.py)
  ├─ enforce_signup_rate_limit (signup_rate_limit.py)
  ├─ verify_email_is_invited / verify_email_domain (auth/users.py)
  ├─ DisposableEmailValidator check
  └─ captcha token verification (auth/captcha.py), if CAPTCHA_ENABLED

POST /auth/login     → fastapi-users login router
  └─ password check → cookie_transport / bearer_transport issues a session
     token via TenantAwareRedisStrategy (default) | RefreshableDatabaseStrategy
     | SingleTenantJWTStrategy, keyed by AUTH_BACKEND
```

### 4.2 OAuth / OIDC (single- and multi-provider)

```
GET /auth/oidc/{provider}/authorize   server/oidc_multi.py
  ├─ _resolve_oidc_provider: load the SSOProvider row
  ├─ validate_idp_url on the discovery/authorize/token/userinfo endpoints
  │   (sso_url_guard.py): SSRF guard, since the URL is admin-configured
  ├─ generate_pkce_pair (pkce.py) if _pkce_enabled(config)
  └─ redirect to the IdP with signed state (fastapi-users OAuth2 state)

GET /auth/oidc/callback (or /{provider}/callback)
  └─ complete_login_flow (auth/users.py)
       ├─ verify state, exchange code (+ PKCE verifier) for tokens
       ├─ login_claims_capture.py: capture id_token/userinfo claims,
       │   best-effort, swallows all failures
       └─ create-or-link User, issue session token
```

Mobile OAuth carries mobile parameters inside the signed OAuth `state` token
itself (`mobile_sso/sso_completion.py:apply_mobile_state`), so no extra
cookie is needed; the callback detects the marker and calls
`complete_mobile_sso`, which mints the session, stores it behind a one-time
PKCE-bound code (`mobile_sso/code_store.py`), and 302s to the app's deep link
carrying only that code. `POST /auth/mobile/sso/exchange` swaps the code (+
PKCE verifier) for the real session token; it has no `User` dependency
because the code itself is the credential, so it is declared public.

### 4.3 SAML

```
GET /auth/saml/{provider}/authorize   server/saml.py, saml_multi.py
  └─ build_saml_settings(SAMLProviderConfig) → OneLogin SP-initiated redirect

POST /auth/saml/callback
  └─ _resolve_saml_provider_by_issuer(_extract_issuer_from_saml_response(...))
       (issuer, not provider name, since the IdP posts back with no path
       segment identifying which configured provider issued it)
  ├─ _enforce_allowed_email_domain
  └─ upsert_saml_user(email) → SamlAccount row + session token
```

### 4.4 Cloud SSO discovery

```
POST /auth/sso/discover  (server/sso_discovery.py)
  ├─ _enforce_discovery_rate_limit (300/IP/hour on MULTI_TENANT only)
  ├─ resolve workspace(s) for the email's domain from the shared catalog
  └─ uniform response: [] for unknown, ambiguous, or SSO-less addresses
     (deliberately, so this endpoint cannot be used to distinguish them);
     else the provider buttons + generate_sso_tenant_token(tenant_id)
     (sso_tenant_token.py), a short-lived (600s) JWT signed with
     USER_AUTH_SECRET that pins the subsequent authorize call to the
     right tenant schema
```

### 4.5 Domain-verified auto-provisioning (EE)

An admin claims an email domain for their workspace; `ee/onyx/auth/
sso_domain_verification.py:verification_record` returns a TXT record
(`_onyx-verification.<domain>`) whose value is an HMAC of
`(tenant_id, domain)` keyed on `USER_AUTH_SECRET`. `verify_domain_via_dns`
resolves it and flips the domain to verified only on a match; a scheduled
`revalidate_tenant_domains` drops verification (and thus auto-provisioning
routing) if the record later disappears, treating a resolver blip
differently from a definitive miss (NXDOMAIN/no TXT/changed value).

### 4.6 Session lifecycle

```
Login  → strategy issues a token; Redis backend stores
         SessionTokenValue{sub, tenant_id, issued_at, expires_at}
         under fastapi_users_token:<token>            session_tokens.py
Cookie → cookie_max_age = SESSION_EXPIRE_TIME_SECONDS + grace(1h)
         (outlives the logical expiry so a dead token is still presented
         and can be *classified*, not silently dropped by the browser)
Refresh → on `AUTH_BACKEND=jwt`, `SingleTenantJWTStrategy.refresh_token` reissues the
         token with the same `sid` claim, so the session identity survives a refresh
Logout → build_session_tombstone_value writes {..., logged_out_at: now}
         over the same key instead of deleting it
Request → classify_session_token_value: EXPIRED / TERMINATED / NOT_FOUND /
          MALFORMED, stashed in a ContextVar, turned into a reasoned
          OnyxError (SESSION_EXPIRED / SESSION_TERMINATED /
          SESSION_UNRECOGNIZED) only once auth has conclusively failed
```

### 4.7 Non-human auth: API key, PAT, SCIM

```
Authorization: Bearer <token>  or raw key (API keys only, historically)
  optional_user → _resolve_optional_user (auth/users.py)
    ├─ SAML/JWT check
    ├─ get_hashed_pat_from_request → resolve_pat → sets request.state.token_scopes
    │    (Bearer-only; api_key.py additionally accepts a raw, non-Bearer key)
    └─ get_hashed_api_key_from_request → fetch_api_key_auth_result
  → user = the PAT's or key's owning User; request.state.usage_credential set
    for billing/audit attribution
```

SCIM is a separate lane: `verify_scim_token` (`ee/onyx/server/scim/auth.py`)
hashes the bearer token and looks it up in `ScimToken` directly; it never
goes through `optional_user`/`current_user` and does not resolve to a
requesting `User` at all (the SCIM actor is the token, audited as such).

### 4.8 Authorization: from request to decision

```
require_permission(Permission.X, allow_anonymous=, allow_scope=)
  (auth/permissions.py)
  └─ base dependency = current_chat_accessible_user | current_user
       (auth/users.py, 2408)
  └─ authority = has_permission(user, X)
       ├─ GLOBAL  if X ∈ get_effective_permissions(user)
       │            (granted ∪ implied ∪ CE_UNGATED_PERMISSIONS in CE,
       │             or ALL_PERMISSIONS if FULL_ADMIN_PANEL_ACCESS granted)
       ├─ SCOPED  if user.is_group_manager and X is in the expanded
       │            SCOPED_MANAGER_PERMISSIONS bundle          (GATE 1)
       └─ NONE    otherwise
  └─ permitted_by_user = (authority is GLOBAL) or
                         (allow_scope and authority is not NONE)
  └─ permitted_by_token = token_scopes is None or X is implied by them
       (caps a scoped PAT to what its own scopes allow)
  └─ 403 INSUFFICIENT_PERMISSIONS unless both hold
```

`allow_scope=True` only lets a SCOPED manager *reach* the handler (GATE 1).
The handler itself must independently confirm the manager's authority over
the *specific resource* (GATE 2): `scoped_permissions.py:assert_within_scope`
for writes, `db/scoped_permissions.py:within_managed_scope_clause` for reads.
A route with `allow_scope=True` and no GATE 2 check hands every scoped
manager global access to that resource type. See [[access-control]] §2 for
how this plays out for user groups, document sets, and connectors
specifically.

---

## 5. Contracts and invariants

This area is security-critical. Claims here are stated at the confidence the
code supports; anything not independently re-verified against a live system
is marked as such.

1. **`User.role` is dead and must never become live again.** It is read by
   nothing and written by nothing outside its own column definition and the
   `UserRole` enum. `grep -rn "UserRole" backend/onyx backend/ee` outside
   tests returns only the enum definition (`auth/schemas.py`), its import,
   and the `role` column (`db/models.py`). Any PR that starts reading or
   writing `user.role`, or that branches on `UserRole.ADMIN`/`CURATOR`, is
   reintroducing a mechanism the rest of the system has moved off of; it
   will not compose with `Permission`/`effective_permissions`.
2. **Every non-public endpoint must declare a real auth dependency.**
   `server/auth_check.py:check_router_auth` walks every registered FastAPI
   route at startup and raises `RuntimeError` if it finds no
   `current_user`/`current_limited_user`/`current_chat_accessible_user`/
   `current_user_from_websocket`/`current_user_with_expired_token`/
   `control_plane_dep`/`current_cloud_superuser`/`verify_scim_token`, and no
   `require_permission(...)`-generated dependency (detected via the
   `_is_require_permission` marker attribute), unless the route's
   `(path, methods)` is in `PUBLIC_ENDPOINT_SPECS` (`ee/onyx/server/
   auth_check.py` extends this list for SCIM discovery and billing). **A new
   endpoint is protected by default only if you add a real dependency**;
   there is no fallback auth applied automatically. Verify this check still
   runs at startup before shipping a new router.
3. **Secrets are stored hashed, never reversibly.** `ApiKey.hashed_api_key`,
   `PersonalAccessToken.hashed_token`, and `ScimToken.hashed_token` are all
   SHA-256 (`hash_api_key`, `hash_pat`, `_hash_scim_token`); the legacy API
   key prefix uses salted `sha256_crypt` for backward compatibility only.
   The raw value is returned to the caller exactly once, at creation, and is
   never re-derivable from the stored hash or re-displayed later (only a
   masked `*_display` string is kept). A change that logs, caches, or
   re-serializes a raw token anywhere past creation breaks this.
4. **A scoped PAT is capped to its own scopes, never wider.**
   `require_permission`'s `permitted_by_token` check
   (`auth/permissions.py:require_permission`) and
   `_scoped_pat_permitted_on_route` (`auth/users.py`) both fail closed:
   a PAT with `scopes` set can only reach routes whose required permission is
   implied by those scopes, or that are marked `scope_exempt()`.
   `_resolve_optional_user` rejects a scoped PAT with `INSUFFICIENT_PERMISSIONS`
   on any route that has neither dependency. A new route without a
   `require_permission` guard is therefore blocked for scoped PATs. It still
   admits unscoped PATs (`scopes` is `None`), which are not capped.
5. **Anonymous access must stay limited to the routes and documents intended
   for it.** `get_anonymous_user()` (`auth/users.py`) grants only
   `Permission.BASIC_ACCESS` and is only reachable through
   `current_chat_accessible_user`, never `current_user`; CE's ungated
   permission auto-grant (`CE_UNGATED_PERMISSIONS`) explicitly excludes
   `AccountType.ANONYMOUS` (`auth/permission_projection.py:get_effective_
   permissions`). [[access-control]] §5.7 covers the document-visibility
   half (anonymous users see `PUBLIC_DOC_PAT` documents only); this
   component covers the endpoint-reachability half. A new
   `allow_anonymous=True` route is a security review, not a routine change.
6. **`USER_AUTH_SECRET` must never be empty in a real deployment.**
   `verify_user_auth_secret` (`auth/users.py:verify_user_auth_secret`) raises on
   startup unless `DEV_MODE` or `INTEGRATION_TESTS_MODE` is set, which downgrade
   it to a warning so local and CI runs keep working. It runs on app startup
   only, not during migrations or scripts.
   `deployment/docker_compose/env.template` ships the key as `USER_AUTH_SECRET=""`
   and tells the operator the API server refuses to start with an empty value,
   so the template and the code agree.
7. **A session logout must be visible immediately, not just letting the
   cookie expire.** `session_tokens.py`'s tombstone (`logged_out_at`) is
   checked by `classify_session_token_value` on every subsequent read of that
   key; a change to session storage that deletes instead of tombstones loses
   the ability to distinguish "logged out" from "Redis dropped the key" for
   diagnostics, and a change that skips writing the tombstone at all
   reintroduces a token usable after logout until its physical TTL expires.
8. **IdP-facing URLs (OIDC discovery, JWT public key, per-request discovery
   document fields) are SSRF-guarded before every fetch.**
   `sso_url_guard.py:validate_idp_url`/`validate_discovered_endpoints` and
   `jwt.py:verify_jwt_token`'s `operator_pinned` branch are the two paths;
   `jwt.py` also rate-limits public-key refetches per URL (60 seconds after a
   success, 5 seconds after a failure), because a caller-supplied token can
   force a refetch;
   an admin-configured URL always goes through validation, an
   environment-pinned one is treated as trusted operator config-as-code. A
   new admin-configurable URL that skips this guard is a fetch an attacker
   who controls DNS or the admin panel could redirect at internal
   infrastructure.
9. **SCIM authenticates as the token, not as a user, and must stay outside
   the `current_user` dependency chain.** `verify_scim_token` returning a
   `ScimToken` (not a `User`) is deliberate: SCIM is a machine-to-machine
   provisioning channel keyed by tenant via the embedded token format, not a
   human session. Routing SCIM through `current_user` would require a
   `User` row to exist for the IdP itself, which is not the model here.

---

## 6. Relationships

**Depends on**
- [[multi-tenancy]]: tenant resolution (`resolve_tenant_for_user`,
  `sso_tenant_token.py`'s workspace pin) decides which schema's `User`,
  `SSOProvider`, and permission rows a login reaches.
- [[editions-and-gating]]: `global_version.is_ee_version()` gates
  `CE_UNGATED_PERMISSIONS`, and EE-only surfaces (multi-provider SSO domain
  routing beyond the first, SCIM) are business-tier gated
  (`_require_business_tier_for_additional_enabled_provider`).
- [[rate-and-usage-limits]]: a separate mechanism from this component's own
  signup/discovery rate limits; PAT/API-key usage attribution
  (`request.state.usage_credential`) feeds it.

**Depended on by**
- [[access-control]]: every ACL computation keys on the `User` object and
  `Permission`/`AccountType` this component produces; see that document's §2
  and §6.
- [[core-chat-loop]]: `require_permission(Permission.WRITE_CHAT,
  allow_anonymous=True)` gates `send-chat-message`; anonymous chat sessions
  are this component's anonymous user flowing through that loop.
- [[onyx-api]]: the public API authenticates the same way (API key / PAT)
  through the same `optional_user` resolution.
- [[llm-gateway]]: the `use:llm_gateway` PAT scope (`Permission.
  USE_LLM_GATEWAY`, `db/enums.py`) is a `SELECTABLE_PAT_SCOPES` entry
  (`server/pat/models.py`) minted and checked entirely by this component's
  PAT machinery. The workspace `llm_gateway_enabled` setting hides the scope
  in `list_selectable_scopes` and blocks minting it, but only for third-party
  PATs; a Craft sandbox's `craft_sandbox`-scoped PAT is unaffected.
- [[cc-pairs-and-credentials]]: connector credentials are a separate
  encrypted-secret concept from user auth; both use the same
  `EncryptedString`/`EncryptedJson` column types but are unrelated tables.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a new HTTP route anywhere in the app | it needs a real auth dependency (§5.2) or an explicit, justified entry in `PUBLIC_ENDPOINT_SPECS`; run the app and confirm `check_router_auth` still passes at startup |
| adds a new `Permission` | update `IMPLIED_PERMISSIONS` if it should be implied by an existing bundle, decide whether it belongs in `PERMISSION_REGISTRY` (toggleable) or `NON_TOGGLEABLE_PERMISSIONS`/`Permission.IMPLIED`, and decide whether a scoped group manager should ever hold it (`SCOPED_MANAGER_PERMISSIONS`); if scoped, add the matching GATE 2 check at every write site |
| changes session or cookie handling (`session_tokens.py`, `cookie_transport`, the strategy classes) | logout tombstoning, the grace-period math, and every `AUTH_BACKEND` variant (Redis/Postgres/JWT), not just the default |
| adds a new SSO provider or protocol | `sso_url_guard.py` validation on every new admin-configurable URL, `auth_check.py`'s public-route list if it adds a new pre-session endpoint, and [[multi-tenancy]] if it touches cloud discovery |
| changes API key or PAT issuance/validation | confirm the raw value is still returned exactly once, the stored value is still hashed, and `require_permission`'s token-scope capping still applies to the new code path |
| changes `UserManager.create` or any signup gate (captcha, disposable email, invite list, rate limit) | test both the enabled and disabled path for each gate independently; they are independent checks, not one pipeline |
| touches `fetch_versioned_implementation`/EE dispatch anywhere in this component | verify the CE fallback narrows rather than widens, mirroring the rule in [[access-control]] §5.9 |
| adds a new non-human credential type (beyond API key / PAT / SCIM) | it needs its own hashed-storage table, its own `optional_user`/`_resolve_optional_user` resolution branch, and its own entry in `auth_check.py`'s recognized-dependency list if it introduces a new FastAPI dependency |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/integration/tests/auth
cd backend && uv run pytest tests/integration/tests/api_key
cd backend && uv run pytest tests/integration/tests/pat
cd backend && uv run pytest tests/integration/tests/scim
cd backend && uv run pytest tests/integration/tests/mobile_auth
cd backend && uv run pytest tests/integration/tests/anonymous_user
cd backend && uv run pytest tests/integration/tests/users
cd backend && uv run pytest tests/integration/tests/permissions tests/integration/tests/permissions_membership
cd web && bun run playwright tests/e2e/auth
```

`backend/tests/integration/tests/auth/test_saml_user_conversion.py` is the
current SAML-specific integration test; there is no equivalent dedicated
OIDC-multi or SSO-discovery integration test in this checkout as of this
writing (unverified beyond this repository snapshot: a broader test suite
may exist that this search did not surface). `web/tests/e2e/auth/
login.spec.ts` and `web/tests/e2e/utils/auth.ts` cover the frontend login
flow. See `backend/AGENTS.md` for authoritative commands and required
secrets/env.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. **Password login**: register a new user at `http://localhost:3000`; the
   first user registered in a fresh deployment becomes admin. Confirm
   `/me` (frontend-proxied) returns the new user and `effective_permissions`
   includes `FULL_ADMIN_PANEL_ACCESS` only for that first user.
3. **Session lifecycle**: log in as `admin_user@example.com` /
   `TestPassword123!`, confirm the cookie is set, log out, and confirm the
   old cookie is rejected with a "signed out" message rather than a generic
   401 (proves the tombstone path, not just cookie expiry).
4. **Group-based authorization, not role**: create a second user, put them
   in a group with no `PermissionGrant` rows, and confirm they cannot reach
   an admin-only page. Then grant the group `MANAGE_CONNECTORS` and confirm
   `is_group_manager` plus scoped (not global) access to only that group's
   connectors, per [[access-control]]'s two-user test pattern.
5. **API key / PAT**: as admin, create an API key
   (`/admin/api-key`, frontend-proxied) and a PAT
   (`/user/pats`), capture the raw value from the response, and confirm a
   `curl` with `Authorization: Bearer <token>` against a
   `require_permission`-gated endpoint succeeds; confirm the same request
   with the token truncated or reused after revocation fails.
6. **Anonymous access**, if enabled: sign out fully, confirm chat still
   works and only public documents are cited; confirm an admin page 401s.

### What "working" looks like

- No route is reachable without a declared auth dependency
  (`check_router_auth` passes at app startup).
- A logged-out session is rejected immediately, not after its physical TTL.
- A revoked or expired API key/PAT/PAT-scope is rejected on the very next
  request, not the next cache refresh.
- A scoped group manager can act only within groups they manage; an
  unscoped attempt raises `INSUFFICIENT_PERMISSIONS`, never a silent no-op.

---

## 9. Footguns

- **`User.role` looks like the authorization mechanism and is not.** It is a
  populated, typed, seemingly-normal enum column with realistic-looking
  values (`ADMIN`, `CURATOR`, `BASIC`...). Nothing about looking at the
  schema alone tells you it is dead. If you find yourself writing
  `if user.role == UserRole.ADMIN`, stop: use `has_global_permission(user,
  Permission.FULL_ADMIN_PANEL_ACCESS)` (`auth/permissions.py:is_user_admin`
  is the existing helper) or `has_permission` for anything scoped.
- **"Curator" is not a role anymore either.** The old `UserRole.CURATOR`/
  `GLOBAL_CURATOR` values still exist in the tombstone enum (so old rows
  still parse) but grant nothing. The live equivalent is `is_group_manager`
  plus `SCOPED_MANAGER_PERMISSIONS`, and it is *scoped to specific groups*,
  not a blanket capability.
- **A group manager's own document access is unrelated to what they
  manage.** Being a manager of a group grants administrative reach over
  that group's connectors/document sets/agents (this component), not
  document-level search visibility into that group's documents (that comes
  only from the manager's own group *membership*, per [[access-control]]
  §9).
- **`allow_scope=True` is a reachability gate, not an authorization
  decision.** Seeing it on a route tells you nothing about whether that
  route is actually safe for a scoped manager; you have to find the GATE 2
  check inside the handler. Its absence is a live vulnerability class, not
  a style nit.
- **A PAT's scopes cap `require_permission` only for the permission named on
  the route.** A scoped PAT cannot reach a route with neither
  `require_permission` nor `scope_exempt()`, because
  `_scoped_pat_permitted_on_route` fails closed in `_resolve_optional_user`.
  An unscoped PAT (`scopes` is `None`) is not capped on any route.
- **The deprecated API key hash path still exists and is weaker.**
  `hash_api_key` branches on the key's prefix and falls back to salted
  `sha256_crypt` for `DEPRECATED_API_KEY_PREFIX` keys. Do not assume every
  stored API key hash is a bare SHA-256 digest when reasoning about a
  migration or a hash-format change.
- **`optional_user` commits its own read transaction early**, specifically
  so a long-running streamed chat response doesn't hold the auth DB
  connection for its whole duration. A change that adds a DB write inside
  the auth-resolution path needs to account for this early-commit behavior,
  not assume the session stays open until request teardown.
- **Anonymous, service-account, and ext-perm-user identities are real `User`
  rows with real IDs, not a special-cased absence of one.** Code that
  assumes "no session = no `User` object" will not notice an
  `AccountType.ANONYMOUS` or `AccountType.BOT` user flowing through the same
  code paths as a standard interactive user.
