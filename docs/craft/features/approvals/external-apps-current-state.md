# External Apps — 05-19-2026 State

Snapshot of what ships on branch `dane/ea-craft-5` (33 commits, +3756/-1 LOC; merge-base `c6df40b1`). Background reading for the approvals system design — approvals will gate the egress credential resolution path described in §3 and §4.

## TL;DR

- **Data model**: two new tables — `external_app` (org-owned config + auth template) and `external_app_user_credential` (per-user JSONB secrets keyed `(app, user)`).
- **Two app flavors**: built-in OAuth providers (`SLACK`, `GOOGLE_CALENDAR`, `LINEAR`) with a backend-defined preset, plus a `CUSTOM` admin-defined app type with no built-in OAuth dispatch.
- **Auth model**: `auth_template` is a JSON dict of header/param values with `{placeholder}` slots filled from `organization_credentials` ∪ user's stored creds. No tokens flow through the agent.
- **Egress resolver shipped, not wired**: `get_external_app_credentials(url)` and `refresh_credentials(url)` exist with full test coverage, but **no production caller yet** — the egress proxy / sandbox HTTP path that will use them is downstream work.
- **Skill bundle delivery**: each authenticated built-in app ships a SKILL.md + helpers under `_external_apps/<id>-<type>/` in the user's sandbox, alongside skills but excluded from the skills tab.
- **OAuth flow**: provider-agnostic `start` + `callback` routes; Redis-backed state with TTL and per-user binding; callback redirect lives on the frontend at `/craft/v1/apps/oauth/callback`.
- **Refresh**: token refresh with Postgres advisory lock per `(app_id, user_id)`; standard OAuth flat-response shape parsed by `StandardFlatRefresh`.
- **Frontend**: two pages — `/craft/v1/apps` (user connect/disconnect) and `/craft/v1/apps/admin` (admin configure presets). Admin nav gated on `isAdmin`.

## 1. Data Model

Migration `db87b27e93ef_external_app_tables.py` (down-revision `2c7f9d3a84a0`). ORM in `backend/onyx/db/models.py`.

### `external_app`

Org-level row — one per configured integration instance.


| Column                      | Type                     | Notes                                                                                                                                                                                                                                                             |
| --------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                        | int                      | PK                                                                                                                                                                                                                                                                |
| `name`                      | str                      | display name (admin-editable)                                                                                                                                                                                                                                     |
| `description`               | str                      | display description                                                                                                                                                                                                                                               |
| `app_type`                  | enum (`ExternalAppType`) | `SLACK`, `GOOGLE_CALENDAR`, `LINEAR`, `CUSTOM`. Discriminator for OAuth-provider dispatch — **decoupled from `name`** so renaming doesn't break OAuth. Not unique: a self-hosted GitLab/Jira could have multiple rows with the same `app_type`. Default `CUSTOM`. |
| `upstream_url_patterns`     | `ARRAY(String)`          | **Regex patterns** (Python PCRE-ish), matched via `re.fullmatch` against outbound URLs. `fullmatch` is deliberate — `search`/`match` would let `https://api.example.com.evil.com/foo` slip through a pattern like `https://api\.example\.com/.`*.                 |
| `auth_template`             | JSONB                    | Dict whose **values** contain `{placeholder}` slots (e.g. `{"Authorization": "Bearer {access_token}"}`). Keys are header/param names; the placeholder names are credential keys.                                                                                  |
| `organization_credentials`  | JSONB                    | Admin-supplied secrets (`client_id`, `client_secret`, etc.).                                                                                                                                                                                                      |
| `enabled`                   | bool                     | Admin soft-disable. Hides from user list and resolution.                                                                                                                                                                                                          |
| `created_at` / `updated_at` | TimestampTZ              | server-managed.                                                                                                                                                                                                                                                   |


### `external_app_user_credential`

Per-user secrets — created on OAuth callback or manual save.


| Column                      | Type        | Notes                                                       |
| --------------------------- | ----------- | ----------------------------------------------------------- |
| `id`                        | int         | PK                                                          |
| `external_app_id`           | int         | FK → `external_app.id`, `ON DELETE CASCADE`                 |
| `user_id`                   | UUID        | FK → `user.id`, `ON DELETE CASCADE`, indexed                |
| `user_credentials`          | JSONB       | Provider-extracted dict (access_token, refresh_token, etc.) |
| `created_at` / `updated_at` | TimestampTZ | server-managed                                              |


**Unique constraint** on `(external_app_id, user_id)` — one credential row per user per app. Upserts use `ON CONFLICT` so concurrent callbacks can't double-insert.

`ExternalAppType` enum lives in `backend/onyx/db/enums.py`.

## 2. CRUD Layer — `backend/onyx/db/external_app.py`

All write helpers are `__no_commit` (flush only); callers own the transaction.

### Reads

- `get_external_app_by_id(db, id) -> ExternalApp | None`
- `get_external_apps(db) -> list[ExternalApp]` — all, ordered by id.
- `get_user_credentials_by_app_id(db, user_id) -> dict[int, ExternalAppUserCredential]` — apps the user hasn't configured are absent.
- `get_authenticated_builtin_apps_for_user(db, user_id) -> list[ExternalApp]` — enabled built-in apps where every required user-supplied credential key is present. Used by skill push to decide which bundles to ship.

### Writes

- `create_external_app__no_commit(...)`
- `update_external_app__no_commit(id, ...)` — replaces all mutable fields; 404s if missing.
- `delete_external_app__no_commit(id)` — credentials cascade via FK.
- `upsert_external_app_user_credential__no_commit(app_id, user_id, creds)` — `ON CONFLICT (app_id, user_id) DO UPDATE`.

### Egress resolution (defined, not yet wired)

- `get_external_app_credentials(db, user_id, url) -> dict | None` — finds the matching enabled app, resolves the auth template against org + user creds, returns the rendered dict (e.g. `{"Authorization": "Bearer <token>"}`). Returns `None` if no match, missing creds, or unfilled placeholder.
- `refresh_credentials(db, user_id, url) -> dict | None` — refreshes OAuth tokens for the app matching `url`. Acquires `pg_advisory_xact_lock((app_id, user_id))` so concurrent callers don't invalidate each other's `refresh_token` on rotating providers. Re-reads creds inside the lock, makes the network call inside the lock (refresh is rare per token lifetime), then merges so Google's non-rotating responses preserve the old `refresh_token`.

### Helpers

- `required_user_credential_keys(auth_template, org_creds)` — scans template *values* for `{placeholders}`, subtracts org-supplied keys; returns the sorted list of credential names the user must supply.

**No production callers of `get_external_app_credentials` / `refresh_credentials` exist yet on this branch.** Both are fully unit-tested but currently dead-ended at the public API of `onyx.db.external_app`. The approvals system will be the first consumer (or sit between an egress proxy and these resolvers).

## 3. Provider Layer — `backend/onyx/external_apps/providers/`

### Abstract interface (`base.py`)

- `OAuth` (ABC): per-provider ClassVars — `app_type`, `app_name`, `authorize_url`, `token_url`, `scope`, `scope_param` (Slack uses `user_scope`), `extra_authorize_params`, plus UI descriptor fields (`description`, `upstream_url_patterns`, `auth_template`, `required_org_credential_fields`, `setup_instructions`). One abstract method: `extract_credentials(response_data) -> dict`.
- `Refresh` (mixin): adds `extract_refresh_credentials`. Refresh dispatcher in `refresh.py` checks `isinstance(provider, Refresh)`.
- `StandardFlatRefresh`: default parser for OAuth 2.0 flat refresh responses (Google, Linear, Slack-on-refresh).
- `OrgCredentialField`: Pydantic spec for a single admin-input field — `key`, `label`, `description`, `secret`.

### Concrete providers


| Provider              | `upstream_url_patterns`                    | Notes                                                                                                             |
| --------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `SlackOAuth`          | `https://slack\.com/api/.`*                | Uses `scope_param="user_scope"`; user token is nested under `authed_user.access_token`. Bot tokens not requested. |
| `GoogleCalendarOAuth` | `https://www\.googleapis\.com/calendar/.*` | `access_type=offline` + `prompt=consent` to guarantee `refresh_token` reissue.                                    |
| `LinearOAuth`         | `https://api\.linear\.app/.*`              | `actor=user` (explicit; otherwise app-acting).                                                                    |


All three currently use `auth_template = {"Authorization": "Bearer {access_token}"}`.

### Registry (`providers/__init__.py`)

- `PROVIDERS: dict[ExternalAppType, OAuth]` built at import time from `_PROVIDER_CLASSES`.
- `get_provider_for_app(app)` / `get_provider_or_raise(app)` — dispatch by `app.app_type`.
- `fetch_available_built_in_apps()` / `fetch_built_in_app(app_type)` — serialize provider class-vars into `BuiltInExternalAppDescriptor` Pydantic models for the admin UI. **Adding a provider = backend-only change** — the descriptor drives the Configure modal.

### Refresh adapter (`refresh.py`)

- `refresh_oauth_tokens(provider, client_id, client_secret, refresh_token)` — pure HTTP, no DB, no locking. Returns the merge dict or `None`. Handles Slack's `200 + {"ok": false}` failure shape.

### Skill bundles (`skill_bundle.py`)

- `get_builtin_external_app_bundle(app_type) -> FileSet | None` — returns `{relpath: bytes}` for the app's SKILL.md + helpers.
- **Storage seam**: today bundles are zipped from `backend/onyx/external_apps/providers/skill_bundles/<app_type_lower>/` on disk. `_load_builtin_bundle_zip` is the single function to swap when bundles move to FileStore / object storage. (Note: no `skill_bundles/` directory ships in this branch yet — the function returns `None` for every provider until bundles are added.)

## 4. Sandbox Integration — `backend/onyx/skills/push.py`

External apps reuse the skill-delivery pipeline but are intentionally **kept out of the skills tab**.

- `build_skills_fileset_for_user` + `build_user_skills_payload` call `get_authenticated_builtin_apps_for_user` and merge each app's bundle under `_external_apps/<id>-<app_type_lower>/` (id-prefixed so multiple instances of the same provider can't collide).
- The leading underscore guarantees no collision with skill slugs (`^[a-z]...`) — no explicit filtering needed to keep external-app bundles off the skills tab.
- `build_external_apps_section(apps)` renders a `## Connected External Apps` block appended to the skills section of AGENTS.md. Tells the agent "API calls are authenticated automatically — you do not handle tokens."
- After `upsert_user_credentials` and after the OAuth callback completes, the API calls `push_skills_for_users({user.id}, db_session)` so the sandbox picks up new bundles immediately.

## 5. HTTP API — `backend/onyx/server/features/build/api/`

Two routers mounted on the existing `/build` prefix:

### Admin (require `FULL_ADMIN_PANEL_ACCESS`) — `external_apps_api.py`


| Method | Path                                      | Purpose                                                     |
| ------ | ----------------------------------------- | ----------------------------------------------------------- |
| POST   | `/admin/apps`                             | Create (no id) or update (id set).                          |
| GET    | `/admin/apps`                             | List all, including disabled.                               |
| DELETE | `/admin/apps/{id}`                        | Delete; cascades user creds.                                |
| GET    | `/admin/apps/built-in/options`            | List built-in provider descriptors for the Configure modal. |
| GET    | `/admin/apps/built-in/options/{app_type}` | Single descriptor.                                          |


### User (require `BASIC_ACCESS`) — `external_apps_api.py`


| Method | Path                     | Purpose                                                                                                                                                                                                                                                                                                                                     |
| ------ | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/apps`                  | List enabled apps, with `authenticated` flag and visible credential keys/values for the calling user. **Strips** `auth_template`, `organization_credentials`, `upstream_url_patterns`, `enabled` — admin-only. Filters stored credential values to keys the *current* template still requires (stale keys from prior templates don't show). |
| POST   | `/apps/{id}/credentials` | Upsert user creds (also used for "disconnect" by posting `{}`). Triggers a skill push.                                                                                                                                                                                                                                                      |


### OAuth — `external_apps_oauth_api.py`


| Method | Path                     | Purpose                                                                                                                                                                            |
| ------ | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/apps/{id}/oauth/start` | Returns `{authorize_url}`. Mints a 600s Redis state record keyed `da_ea_oauth:<uuid>` containing `(user_id, external_app_id)`. Distinct from connector-OAuth's `da_oauth:` prefix. |
| POST   | `/apps/oauth/callback`   | Validates state → matches user → POSTs to `provider.token_url` → `provider.extract_credentials` → upserts → pushes skills → deletes Redis key (one-shot).                          |


Provider-agnostic OAuth: routes look up `OAuth` by `app.app_type` and delegate authorize-URL construction + response parsing.

**Frontend callback path**: `/craft/v1/apps/oauth/callback` (must be added to each provider's developer console as a Redirect URI).

### Models — `models.py`

- `UpsertExternalAppRequest`, `ExternalAppAdminResponse` — admin view, full row.
- `UpsertUserCredentialsRequest`, `ExternalAppUserResponse` — user view, with `credential_keys` + `credential_values` + `authenticated`.
- `OAuthStartResponse`, `OAuthCallbackRequest`, `OAuthCallbackResponse`.
- `OrgCredentialFieldDescriptor`, `BuiltInExternalAppDescriptor` — UI descriptors.

## 6. Frontend — `web/src/app/craft/v1/apps/`


| Route                           | Audience                                   | What it does                                                                                                                 |
| ------------------------------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| `/craft/v1/apps`                | Any user                                   | List enabled apps; "Connect" → redirect to `authorize_url`; "Disconnect" → POST empty creds.                                 |
| `/craft/v1/apps/admin`          | Admins only (gated by `useUser().isAdmin`) | Two sections: "Configure" (presets list) and "Configured" (existing rows). Edit/enable-disable/delete per row.               |
| `/craft/v1/apps/oauth/callback` | Any user                                   | One-shot exchange page. `useRef` guards against React StrictMode double-fire. Auto-redirects to `/craft/v1/apps` on success. |


- Service layer: `web/src/app/craft/services/externalAppsService.ts` — all HTTP in one place.
- Registry: `web/src/app/craft/v1/apps/registry.ts` — mirrors backend `ExternalAppType` enum and Pydantic descriptors as TS interfaces; `getAppTypeLogo` falls back to a generic plug icon for unknown / `CUSTOM` types.
- Configure modal: `ConfigureProviderModal.tsx` — re-seeds on every open, merges credential edits onto existing org creds (so future non-credential metadata survives), saves with `enabled: true`.
- Sidebar tabs added: **My Apps** (always visible) and **Manage Apps** (admin-only).
- New SWR keys: `buildExternalApps`, `buildExternalAppsAdmin`, `buildExternalAppsBuiltInOptions`.

## 7. Tests

### External dependency unit (`backend/tests/external_dependency_unit/db/`)

- `test_external_app_credentials.py` — 11 tests covering URL → credential resolution: match-and-fill, no-user-keys case, multi-pattern, no match, disabled app skipped, missing user creds, partial creds, unfilled placeholder, fullmatch rejecting partial overlaps, deterministic ordering by id, and cross-user isolation.
- `test_external_app_skill_bundles.py` — 7 tests covering bundle loader return shape, authentication gating, disabled/CUSTOM exclusion, mount-prefix isolation, unauthenticated case.

### Integration (`backend/tests/integration/tests/external_apps/test_external_apps.py`)

9 tests via `ExternalAppManager` covering the full admin→user happy path, RBAC, cascade delete, cross-user isolation, disable-preserves-creds, template-reshape behavior, 404s on missing ids, the partial-vs-org-template authentication boundary, and `app_type` round-trip + default.

**No tests yet** for: the OAuth callback flow end-to-end (`external_apps_oauth_api.py`), `refresh_credentials` (refresh.py is exercised only at the resolution-layer entry point), or the live `pg_advisory_xact_lock`-under-contention behavior.

## 8. Gaps Relevant to the Approvals Design

Things the approvals system will likely need to define or pick up:

1. **Where credential resolution is invoked.** `get_external_app_credentials(url)` and `refresh_credentials(url)` are written and tested but have no production caller. The approvals system probably sits on the egress path — either calling these directly or being called between an egress proxy and these resolvers. The shape of "agent makes outbound HTTPS request → egress proxy decides which app matches → asks for resolved auth headers" is implied by the pattern-matching API but not yet implemented.
2. **No audit/event trail.** Nothing logs which app was matched, which URL the agent tried, or which user owned the resolved credentials. Approvals will need to decide whether to add structured logging here or layer it on the egress side.
3. **No per-call user prompt mechanism.** All approval-style decisions are coarse: enabled/disabled at the app level, authenticated/unauthenticated at the user level. No infra for "agent wants to POST to slack.com/api/chat.postMessage — approve once / always / deny."
4. **Token refresh is reactive only.** `refresh_credentials` is a pull operation — caller decides when to refresh. There's no background expiry tracking or proactive refresh. Approvals may want to know whether a token is fresh enough before granting use.
5. **CUSTOM apps have no OAuth path.** Only built-in providers reach the OAuth routes. Custom apps require admins to inject user credentials manually (no UI shipped for that yet). If approvals applies to custom apps, the credential-entry flow needs design work.
6. **No revocation hook.** Disconnect (`user_credentials = {}`) clears creds and re-pushes skills but does not call any provider revoke endpoint. Approvals may want to enforce real revocation on disconnect.
7. **No rate limiting / quota.** Nothing caps how often the agent can resolve credentials for an app. Approvals may need to add per-user or per-app counters.
8. **Skill bundle dir doesn't exist yet on disk.** `_load_builtin_bundle_zip` returns `None` for every provider on this branch — until SKILL.md + helpers are added under `providers/skill_bundles/<type>/`, no agent instructions are shipped for any of the three built-ins. (The AGENTS.md "Connected External Apps" section still renders, since it's driven by `get_authenticated_builtin_apps_for_user`, not bundle presence.)

