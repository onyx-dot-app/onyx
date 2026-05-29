# External-App OAuth Token Refresh — Implementation Plan

> **Scope.** This plan implements **lazy, just-in-time refresh** of a connected
> external app's OAuth access token at the egress credential-injection seam. It
> builds on [action policies](./action-policies.md) (which decides *whether* a
> request is forwarded) and the egress proxy's credential injection — this plan
> only ensures the token injected on an approved forward is **live**.
>
> **Why lazy / why this shape.** The approach trade-offs (lazy vs. background vs.
> on-401, and the three ways to single-flight a lazy refresh) are argued in
> `plans/external-app-lazy-token-refresh-design.md`. This doc is the
> implementation contract for the chosen path — **Approach 2: offloaded refresh
> via `asyncio.to_thread`, single-flighted by a system-wide Redis lock** — and
> exists so a reviewer can map the PR diff to an agreed design.

## Summary

OAuth access tokens for connected apps are captured once at connect time and
never refreshed. Google Calendar tokens expire ~1 hour later, after which the
egress proxy injects a dead `Bearer` token, the upstream 401s, and the agent's
request fails until the user manually reconnects. The `refresh_token` is already
stored — it is simply never used.

This change refreshes the access token transparently, the first time it is
needed after it goes stale, using the stored `refresh_token`. A burst of
concurrent sandbox requests is single-flighted through a Redis lock so the
provider's token endpoint is hit at most once per (tenant, app, user) per
expiry.

## Problem

- `extract_credentials` persists `refresh_token` + `expires_in` at connect time
  (`backend/onyx/external_apps/providers/{google_calendar,slack,linear}.py`), but
  nothing ever calls the token endpoint again and no absolute expiry is stored.
- The sole injection seam, `GateAddon._inject_credentials`
  (`backend/onyx/sandbox_proxy/addons/gate.py`) → `resolve_injection_headers`
  (`backend/onyx/external_apps/credentials.py`), renders whatever is stored —
  including an expired token. It already opens a synchronous DB session here, so
  the refresh is a natural in-line addition at this one seam.

## What is already in place (not part of this PR)

- **Encryption at rest** (PR #11514): `ExternalAppUserCredential.user_credentials`
  and `ExternalApp.organization_credentials` are `EncryptedJson()` /
  `SensitiveValue[dict]`, read via `.get_value(apply_mask=False)`. No encryption
  migration is needed here.
- **Refresh token + `expires_in` capture**: providers already store both. This
  PR adds only the absolute `expires_at` and the refresh machinery.

## Design decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Trigger | Lazy, at the injection seam (`GateAddon._inject_credentials`) | Two calls — `ensure_fresh_credentials(...)` then `resolve_injection_headers(...)`. |
| Interface boundary | The seam passes the **session factory + ids**; the helper abstracts read + refresh + store entirely | The gate stays ignorant of refresh mechanics (no DB calls, no lock, no token POST, no session handling at the seam). |
| `ensure_fresh_credentials` shape | `(db_session_factory, tenant_id, external_app_id, user_id) -> None` | Self-contained: opens its own short sessions, single-flights, persists. Returns nothing — the caller just renders next. |
| Single-flight | Fleet-wide Redis lock (`redis_shared_lock`) with double-checked re-read | Dedupes a stampede across processes/pods and is safe for token-rotating providers; fully hidden inside the helper. |
| Session lifetime | The helper takes its own **short** sessions per step (pre-check, re-read, persist) | No connection held across the Redis-lock wait or the token POST. The factory is passed in (not a live session, not threaded through call after call). |
| Terminal handling | Helper **clears** the credential and **returns** (does not raise) | A revoked grant becomes "disconnected" — the same path as a never-connected app (render finds no creds → forwards unauthenticated → upstream 401 + UI reconnect). Keeps the gate free of refresh-specific error handling. |
| Expiry storage | Absolute UTC `expires_at` instant | No "when was this written" bookkeeping on read. |
| `expires_at` stamping | At the callback and inside the refresh helper, not the provider | `extract_credentials` / `refresh_credentials` stay clockless and trivially testable. |
| Refresh-token-only rows backfill | Self-heal (treat missing `expires_at` as never-expire) | The pre-change population is tiny and transient; one extra 401 then a reconnect. |

**Event-loop note.** The refresh runs synchronously on the proxy event loop
(matching the sync DB I/O already there); it is rare (once per token lifetime per
user), single-flighted, and the token POST is tightly timed out. If a slow token
endpoint blocking the loop becomes a problem, the seam can wrap the one
`ensure_fresh_credentials(...)` call in `asyncio.to_thread` — its internals don't
change.

## Changes (file-by-file — the PR review map)

### 1. Stamp absolute `expires_at` at write time
- **`backend/onyx/server/features/build/api/external_apps_oauth_api.py`** — after
  `provider.extract_credentials(...)` in the callback, compute `expires_at` (UTC,
  from the response's `expires_in`) and merge it into the stored dict before
  `upsert_external_app_user_credential`. `extract_credentials` stays a pure
  response→dict mapper (no clock).

### 2. Provider refresh capability (template method)
- **`backend/onyx/external_apps/providers/base.py`** — `OAuthExternalAppProvider`
  owns refresh as a **template method**, so the format knowledge lives on the
  provider class (not in free functions) and a divergent provider overrides only
  the piece that differs — it never re-implements the POST + error boilerplate:
  - **`refresh_credentials(stored, client_id, client_secret)`** — the template:
    read the refresh token → build request → POST → classify error → map + carry
    the refresh token forward. Clockless (caller stamps `expires_at`).
  - **Class properties** (override per provider): `refresh_http_timeout_seconds`,
    `terminal_refresh_errors` (which OAuth error codes are fatal vs. retryable).
  - **Hooks** (override per provider): `build_refresh_request(...) -> dict` (the
    refresh POST form body — add `scope`/`resource`/etc.), `classify_token_response(...)`
    (failure detection), and `extract_credentials` (response → creds, shared with
    the initial grant).
  - All built-ins use the default RFC-6749 path today; the hooks exist so the next
    built-in or a (future, config-driven) custom OAuth provider slots in by
    overriding one method. Slack/Linear return no `expires_in`, so they're never
    refreshed regardless.

### 3. Refresh-and-persist helper (new)
- **`backend/onyx/external_apps/token_refresh.py`** (new) — the one call the gate
  makes; everything about keeping the token fresh lives behind it:
  ```
  ensure_fresh_credentials(db_session_factory, tenant_id, external_app_id, user_id) -> None
  ```
  - **Pre-check** (own short session, then closed): resolve app + provider; bail
    if non-OAuth; read creds; `needs_refresh(stored, now)`? If not → return (the
    common path — no lock, no network, connection released).
  - Acquire `redis_shared_lock("ea_token_refresh:{tenant}:{app}:{user}", …)`.
  - **Re-read** (own short session, then closed): a fresh session sees a
    concurrent winner's committed refresh (read-committed); if no longer stale,
    return. Otherwise gather the POST inputs (provider, stored creds,
    `client_id`/`client_secret`) and close the session.
  - `provider.refresh_credentials(...)` — the token POST runs with **no DB
    connection held**.
  - **Persist** (own short session): `upsert_external_app_user_credential` with
    the `stamp_expires_at`-stamped creds.
  - **Never raises for a refresh outcome:** transient → log + return (keep the
    existing token); terminal → `delete_external_app_user_credential` + return
    (app reads disconnected); lock contention → yield to the winner + return.
  - `needs_refresh(stored, now, skew_s=120)`: no `expires_at` → `False`; else
    `expires_at - now <= skew`. `stamp_expires_at` builds a new dict, so the
    `get_value(apply_mask=False)` cache is never mutated. The factory is passed
    in (not a live session); **persistence stays in `db/external_app.py`**.

### 4. Wire into the egress seam
- **`backend/onyx/sandbox_proxy/addons/gate.py`** — `_inject_credentials` makes
  two calls inside its existing `try`/`except`:
  ```python
  ensure_fresh_credentials(self._db_session_factory, tenant_id, app_id, user_id)
  with self._db_session_factory(tenant_id) as db:
      headers = resolve_injection_headers(db, app_id, user_id)
  ```
  The gate imports only `ensure_fresh_credentials` + `resolve_injection_headers`
  — no DB functions, no lock, no refresh exceptions. A revoked grant is cleared
  inside the helper, so the render finds no creds and forwards unauthenticated
  (upstream 401), the same as a never-connected app. Unexpected errors hit the
  existing broad `except` → `False` (fail closed). Both ALWAYS and ASK-approved
  go through `_inject_credentials_or_block` → `_inject_credentials` unchanged.

## Failure handling

All inside `ensure_fresh_credentials` — the gate never sees a refresh-specific
exception:

- **`invalid_grant` / revoked (terminal):** clear the credential row
  (`delete_external_app_user_credential`) and return. The render then finds no
  creds → forwards unauthenticated → upstream 401 + the app reads as
  disconnected (UI prompts reconnect). No retry loop.
- **Transient network / 5xx:** log and return the existing token in place; the
  request proceeds (may 401) and the next request retries. Never destroy a
  possibly-valid token on a blip.
- **Lock contention (`RedisSharedLockAcquisitionError`):** yield to the
  concurrent refresher and return; this request proceeds with the current token.
- **Unexpected (DB down, etc.):** propagates to the gate's broad `except` →
  `False` → block (fail closed).

## Concurrency & edge cases

- **Stampede:** N parallel stale requests → one wins the Redis lock and
  refreshes; the rest re-read (fresh session) and see the committed token.
- **Skew:** the 120s window refreshes early so no in-flight request reaches
  upstream with a just-expired token.
- **Slack / Linear / static-credential apps:** no `expires_at` → `needs_refresh`
  is `False` → `ensure_fresh_credentials` is a no-op; behaviour unchanged.
- **Lock scope:** `redis_shared_lock` is on the shared (not tenant) Redis client,
  so the lock name encodes `tenant_id:app_id:user_id`.
- **No connection across the POST:** each step takes its own short session; the
  token POST holds none.
- **Clock:** compare against UTC `now`; store/parse absolute instants.

## Tests

- **Unit** (`backend/tests/unit/external_apps/`):
  - `needs_refresh`: fresh → no-op; within-skew / expired → refresh; no
    `expires_at` → no-op. (`test_token_utils.py`)
  - `refresh_credentials` mapping: success maps fields; rotation persists a new
    `refresh_token`; no-rotation carries the old one forward; `invalid_grant` →
    terminal; 5xx / network → transient. (`test_token_refresh.py`)
  - Template-method extensibility: a subclass overriding one hook
    (`build_refresh_request`, `terminal_refresh_errors`) changes only that
    behavior and inherits the rest. (`test_token_refresh.py`)
  - `ensure_fresh_credentials` orchestration (mocked DB factory + lock +
    provider): fresh → no-op; double-checked re-read skips when the winner
    refreshed; stale → upserts a `stamp_expires_at`-stamped dict; terminal clears
    the row **without raising**; transient keeps the existing token; non-OAuth →
    no-op. (`test_token_refresh.py`)
- **Gate** (`backend/tests/unit/sandbox_proxy/test_gate.py`):
  - `_inject_credentials` calls `ensure_fresh_credentials(factory, tenant, app,
    user)` before rendering. An autouse fixture defaults the refresh to a no-op so
    the other gate tests pin injection/approval only.

## Reviewer checklist

- [ ] `extract_credentials` remains a pure mapper; `expires_at` is stamped by the
      callback and the refresh helper — never the provider.
- [ ] Refresh format lives on `OAuthExternalAppProvider` as overridable
      properties/hooks (template method), not in free functions/constants — a new
      provider's divergence is a one-method override, not a reimplementation.
- [ ] The gate seam is two calls and imports only `ensure_fresh_credentials` +
      `resolve_injection_headers` — no DB functions, lock, or refresh exceptions.
- [ ] `ensure_fresh_credentials` takes the session **factory** (not a live
      session); each step's session is short — none spans the lock wait or POST.
- [ ] `stamp_expires_at` builds a new dict — the `get_value(apply_mask=False)`
      cache is never mutated.
- [ ] All DB calls go through `db/external_app.py`; the provider token POST has a
      bounded HTTP timeout; lock name includes tenant + app + user.
- [ ] Failure paths (all inside the helper, never raised to the gate): terminal
      clears the row; transient/lock-contention keep the existing token; only
      unexpected errors propagate (gate blocks).
- [ ] Slack/Linear (no `expires_in`) and static-credential apps are provably
      no-ops.
- [ ] Refresh tokens never logged; injection logging stays header-names-only.

## References

- Approach comparison & rationale: `plans/external-app-lazy-token-refresh-design.md`
- Original problem framing & option pitches: `plans/external-app-token-refresh.md`
- Policy layer (what gates the forward): [`action-policies.md`](./action-policies.md)
- Egress enforcement: [`egress-proxy-action-policy-enforcement.md`](./egress-proxy-action-policy-enforcement.md)
