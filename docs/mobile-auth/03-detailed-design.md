> Status: active · Task: mobile-auth · Approach: C — Mobile Auth Gateway (BFF)

# Mobile Authentication — Detailed Design

> Scope: **V1 = email/password + Google**, against **cloud + self-hosted**, native Bearer auth. SAML / OIDC / Apple are designed-for but not built (see "Later providers"). All paths assume the existing `/api` global prefix convention the mobile foundation already uses for `/api/me`.

## Database design

**Database design: N/A for V1 — by design.** Approach C reuses Onyx's existing session-token store: `AUTH_BACKEND=redis` writes the token to Redis with a TTL (`TenantAwareRedisStrategy.write_token`, `backend/onyx/auth/users.py:1363-1382`); `postgres` reuses the existing `access_token` table; `jwt` is stateless. The one-time SSO code is a short-lived **Redis** entry, not a SQL row. No new table, no Alembic migration.

> Forward note (not V1): the deferred rotation subsystem (Approach B) would add a `mobile_session` table (per-device family + reuse-detection + audit). When that lands it goes under `backend/onyx/db/` with a hand-written migration, behind the `issue_session_credential` seam. Out of scope here.

## Class / interface design

### Backend

- **`bearer_transport: BearerTransport`** (new) — `BearerTransport(tokenUrl="auth/mobile/login")`. fastapi-users primitive; its `get_login_response(token)` returns `{access_token, token_type:"bearer"}`. Lives beside `cookie_transport` in `backend/onyx/auth/users.py:1326`.
- **`mobile_auth_backend: AuthenticationBackend`** (new) — `AuthenticationBackend(name="mobile-bearer", transport=bearer_transport, get_strategy=<same get_strategy as the active cookie backend>)`. Added to the `fastapi_users` backend list: `FastAPIUserWithLogoutRouter[User, uuid.UUID](get_user_manager, [auth_backend, mobile_auth_backend])` (`users.py:1684`). Route names become `auth:mobile-bearer.{login,refresh,logout}` — no collision with `auth:redis.*`.
- **`issue_session_credential(user: User, strategy: Strategy) -> str`** (new) — the token-issuance seam. V1 body: `return await strategy.write_token(user)` (mints the same stateful token, transport-agnostic). Single indirection point so a future access+refresh-rotation implementation swaps here without touching callers. Lives in `backend/onyx/auth/mobile_sso/tokens.py`.
- **One-time SSO code store** (new, `backend/onyx/auth/mobile_sso/code_store.py`) — stores a PKCE-bound record, not just the token:
  - `async def store_sso_code(token: str, code_challenge: str, tenant_id: str | None) -> str` — generate `code = secrets.token_urlsafe()`, `redis.set(f"{MOBILE_SSO_CODE_PREFIX}{code}", json.dumps({"token": token, "code_challenge": code_challenge, "tenant_id": tenant_id}), ex=MOBILE_SSO_CODE_TTL_SECONDS)`, return `code`.
  - `async def consume_sso_code(code: str, code_verifier: str) -> str | None` — atomic `GETDEL` (single-use); if missing/expired → `None`; recompute `BASE64URL(SHA256(code_verifier))` and constant-time-compare to the stored `code_challenge` (S256) — on mismatch return `None` (the code is already burned). Returns the token on success. Uses `get_async_redis_connection()` (always available — Redis is core infra even when `AUTH_BACKEND=jwt`). PKCE helpers (`generate_pkce_pair`/S256) already exist in the codebase (`users.py:2279`); reuse the verification half.
- **`complete_mobile_sso(user, state_data, strategy, request) -> RedirectResponse`** (new, in `mobile_sso/`) — the shared SSO completion: validate `state_data["app_redirect_uri"]` is in the allowlist; `token = await issue_session_credential(user, strategy)`; `code = await store_sso_code(token, state_data["app_code_challenge"], ...)`; `return RedirectResponse(add_url_params(app_redirect_uri, {"code": code, "state": state_data["app_state"]}), status_code=302)`. Called by every provider's callback when `state_data.get("client") == "mobile"`. (Reject at this point if `app_code_challenge` is absent — mobile SSO requires PKCE.)
- **Mobile gateway router** (new, `backend/onyx/server/auth/mobile.py`) — owns `POST /auth/mobile/sso/exchange` and mounts the bearer backend's login/refresh/logout (see "New files"). Typed functions, no `response_model`, raises `OnyxError` (CLAUDE.md).

> The "provider registry" is intentionally **thin on the backend**: Onyx's `get_oauth_router` (`users.py:2204`) is *already* provider-generic (Google + OIDC share it), and SAML has its own router. So provider-genericity is achieved by the single shared `complete_mobile_sso` helper that each callback calls — not a new abstraction layer. The richer registry lives on the **mobile** side (descriptors).

### Mobile

- **`SessionManager`** (new, `mobile/src/api/auth/sessionManager.ts`) — `login(method: LoginMethod): Promise<void>`, `logout(): Promise<void>`, `getValidToken(): Promise<string | null>` (single-flight: concurrent callers share one in-flight refresh promise). Orchestrates `tokenStore` + query-cache purge. `LoginMethod = { kind: "password"; email; password } | { kind: "browser"; provider: ProviderId }`.
- **`providerRegistry`** (new, `mobile/src/api/auth/providers.ts`) — `Record<ProviderId, ProviderDescriptor>` where `ProviderDescriptor = { id; label; kind: "password" | "browser"; authorizePath?: string }`. V1: `password`, `google` (`authorizePath: "/api/auth/oauth/authorize"`). Later rows: `oidc`, `saml`, `apple`. The login screen renders buttons from this filtered by `GET /auth/type`.
- **`runBrowserSso(descriptor, baseUrl): Promise<{ code: string; codeVerifier: string }>`** (new, `mobile/src/api/auth/browserSso.ts`) — generates `state` and a **PKCE pair** (`codeVerifier` = random 32-byte base64url via `expo-crypto`; `codeChallenge` = base64url(SHA256(codeVerifier)) via `expo-crypto` `digestStringAsync`), builds `{baseUrl}{authorizePath}?redirect=true&mobile_redirect_uri=onyx://auth/callback&app_state=<state>&app_code_challenge=<challenge>`, opens it via `WebBrowser.openAuthSessionAsync(url, "onyx://auth/callback")`, parses the returned deep link, verifies `state`, and returns `{ code, codeVerifier }` (the verifier never leaves the device until the TLS exchange). Throws `ApiError`-shaped on state mismatch/cancel.
- **`tokenStore`** (modified) — add `keychainAccessibility` option; keep `getToken`/`setToken`; `setToken(null)` stays the logout primitive (cache purge orchestrated by `SessionManager`).
- **`useSession()` / `AuthGate`** (new) — gate component reading `useCurrentUser`; `isAuthError` → redirect to `/(auth)/connect` or `/(auth)/login`.
- **`getBaseUrl()`** (modified, `config.ts`) — read the runtime-stored server URL from `appStorage` (MMKV), falling back to `EXPO_PUBLIC_API_URL` for dev.

## New files

| File | Responsibility |
|------|----------------|
| `backend/onyx/server/auth/mobile.py` | Mobile gateway router: mounts bearer-backend login/refresh/logout + `POST /auth/mobile/sso/exchange`. |
| `backend/onyx/auth/mobile_sso/__init__.py` | Package marker. |
| `backend/onyx/auth/mobile_sso/tokens.py` | `issue_session_credential(user, strategy)` token-issuance seam. |
| `backend/onyx/auth/mobile_sso/code_store.py` | `store_sso_code` / `consume_sso_code` (60s single-use Redis codes). |
| `backend/onyx/auth/mobile_sso/sso_completion.py` | `complete_mobile_sso(...)` shared completion + `app_redirect_uri` allowlist check. |
| `mobile/src/api/auth/sessionManager.ts` | `login/logout/getValidToken` + single-flight refresh + cache purge. |
| `mobile/src/api/auth/providers.ts` | Provider registry (descriptors). |
| `mobile/src/api/auth/browserSso.ts` | System-browser OAuth runner + deep-link capture/validation. |
| `mobile/src/api/auth/useAuthConfig.ts` | `GET /api/auth/type` discovery hook. |
| `mobile/src/api/auth/useEmailLogin.ts` | TanStack mutation → `POST /api/auth/mobile/login`. |
| `mobile/src/api/auth/useLogout.ts` | Mutation → `POST /api/auth/mobile/logout` + cache purge. |
| `mobile/src/api/auth/useSessionRefresh.ts` | Single-flight `POST /api/auth/mobile/refresh` (foreground + pre-expiry). |
| `mobile/src/state/session.ts` | Zustand store: `status: "loading" \| "authed" \| "anon"` + serverUrl. |
| `mobile/src/app/(auth)/_layout.tsx` | Auth route group layout. |
| `mobile/src/app/(auth)/connect.tsx` | Server-URL entry (cloud default / self-hosted). |
| `mobile/src/app/(auth)/login.tsx` | Email/password form + provider buttons. |
| `mobile/src/components/auth/AuthGate.tsx` | Redirect gate based on `useCurrentUser`. |

## File structure (tree)

```
backend/onyx/
├── auth/
│   ├── users.py                         (modified: add bearer_transport + mobile_auth_backend to fastapi_users list;
│   │                                      add optional mobile_redirect_uri/app_state to /authorize; add
│   │                                      `if state_data.client == "mobile": return await complete_mobile_sso(...)`
│   │                                      branch in complete_login_flow before backend.login)
│   └── mobile_sso/                      (new package)
│       ├── __init__.py                  (new)
│       ├── tokens.py                    (new: issue_session_credential)
│       ├── code_store.py                (new: store/consume one-time SSO codes)
│       └── sso_completion.py            (new: complete_mobile_sso + redirect allowlist)
├── server/
│   ├── auth/
│   │   └── mobile.py                    (new: mobile gateway router)
│   ├── manage/get_state.py              (reused: GET /auth/type)
│   └── saml.py                          (LATER: same mobile branch in callback)
├── configs/app_configs.py              (modified: MOBILE_SSO_CODE_TTL_SECONDS, MOBILE_ALLOWED_REDIRECT_URIS)
└── main.py                              (modified: include mobile gateway router; mount bearer
                                          login/refresh/logout via include_auth_router_with_prefix)

mobile/src/
├── api/
│   ├── client.ts                        (modified: optional — call SessionManager.getValidToken before Bearer
│   │                                      injection so a near-expiry token refreshes; or keep as-is + 401 retry)
│   ├── config.ts                        (modified: getBaseUrl() reads runtime server URL from appStorage)
│   ├── query-keys.ts                    (modified: add auth/config keys if needed)
│   └── auth/
│       ├── tokenStore.ts                (modified: keychainAccessibility THIS_DEVICE_ONLY; resolve logout TODOs)
│       ├── sessionManager.ts            (new)
│       ├── providers.ts                 (new)
│       ├── browserSso.ts                (new)
│       ├── useAuthConfig.ts             (new)
│       ├── useEmailLogin.ts             (new)
│       ├── useLogout.ts                 (new)
│       └── useSessionRefresh.ts         (new)
├── state/
│   ├── session.ts                       (new: Zustand auth-status + serverUrl store, persisted to appStorage)
│   └── storage.ts                       (modified: encryptionKey for query-cache MMKV, or PII-dehydrate exclusion)
├── components/auth/AuthGate.tsx         (new)
└── app/
    ├── _layout.tsx                      (modified: wrap Stack in <AuthGate>; mount deep-link listener)
    ├── index.tsx                        (reused: protected home)
    └── (auth)/                          (new group)
        ├── _layout.tsx                  (new)
        ├── connect.tsx                  (new)
        └── login.tsx                    (new)

mobile/app.json                          (modified: confirm scheme "onyx"; document auth/callback path)
mobile/package.json                      (modified: + expo-auth-session, expo-web-browser, expo-crypto)
```

## What each file will contain

### Backend
- **`backend/onyx/auth/users.py`** (modified) — (1) `bearer_transport = BearerTransport(tokenUrl="auth/mobile/login")` next to `cookie_transport`; (2) build `mobile_auth_backend` with the same `get_strategy` selected at `:1547-1560` and append it to the `fastapi_users` backend list at `:1684`; (3) in `get_oauth_router.authorize` (`:2251`), accept optional `mobile_redirect_uri: str | None = Query(None)` + `app_state: str | None = Query(None)` + `app_code_challenge: str | None = Query(None)`, and when present add `client="mobile"`, `app_redirect_uri`, `app_state`, `app_code_challenge` into `state_data` (`:2270`) — these ride inside the signed state token, so they're tamper-proof through the Google round-trip; (4) in `complete_login_flow` (`:2523`), immediately before `response = await backend.login(strategy, user)` (`:2573`), add `if state_data.get("client") == "mobile": return await complete_mobile_sso(user, state_data, strategy, request)`. All additive and guarded — the web path is unchanged when the params/marker are absent.
- **`backend/onyx/auth/mobile_sso/tokens.py`** — `async def issue_session_credential(user, strategy) -> str: return await strategy.write_token(user)`. (Seam; documented as the future rotation insertion point.)
- **`backend/onyx/auth/mobile_sso/code_store.py`** — `store_sso_code(token, code_challenge, tenant_id)` / `consume_sso_code(code, code_verifier)` using `get_async_redis_connection()` + `MOBILE_SSO_CODE_PREFIX` + `MOBILE_SSO_CODE_TTL_SECONDS`. Stores a JSON record `{token, code_challenge, tenant_id}`. `consume` uses Redis `GETDEL` (or a `pipeline` GET+DEL) for atomic single-use, then S256-verifies `code_verifier` against the stored `code_challenge` (constant-time) before returning the token.
- **`backend/onyx/auth/mobile_sso/sso_completion.py`** — `complete_mobile_sso(user, state_data, strategy, request)`: require `state_data["app_code_challenge"]` (reject if absent); validate `state_data["app_redirect_uri"]` ∈ `MOBILE_ALLOWED_REDIRECT_URIS`; `token = await issue_session_credential(user, strategy)`; `code = await store_sso_code(token, state_data["app_code_challenge"], ...)`; `return RedirectResponse(add_url_params(app_redirect_uri, {"code": code, "state": state_data["app_state"]}), 302)`. Raises `OnyxError(VALIDATION_ERROR, ...)` on a bad/absent redirect URI or missing challenge.
- **`backend/onyx/server/auth/mobile.py`** — a router that (a) `include`s `fastapi_users.get_auth_router(mobile_auth_backend)` (→ `/login`), `get_refresh_router(mobile_auth_backend)` (→ `/refresh`), `get_logout_router(mobile_auth_backend)` (→ `/logout`) under the `/auth/mobile` prefix, and (b) defines `@router.post("/auth/mobile/sso/exchange")` → typed `async def sso_exchange(payload: SsoExchangeRequest) -> SsoTokenResponse` where `SsoExchangeRequest = {code: str, code_verifier: str}`: `token = await consume_sso_code(payload.code, payload.code_verifier)`; if `None` raise `OnyxError(UNAUTHENTICATED, "Invalid or expired code")` (same generic error for missing/expired/PKCE-mismatch — no oracle); else return `{"access_token": token, "token_type": "bearer"}`.
- **`backend/onyx/main.py`** (modified) — register the mobile gateway via `include_auth_router_with_prefix(...)` (inherits the global prefix + auth rate-limiting), gated on `AUTH_TYPE in {basic, google_oauth, oidc, saml, cloud}`, mirroring the existing blocks at `:572-690`.
- **`backend/onyx/configs/app_configs.py`** (modified) — `MOBILE_SSO_CODE_TTL_SECONDS = int(os.environ.get(..., 60))`; `MOBILE_ALLOWED_REDIRECT_URIS` (default `["onyx://auth/callback"]`, comma-split env override for Universal-Link hardening later).

### Mobile
- **`sessionManager.ts`** — `login()` routes to `useEmailLogin`'s fetch (`POST /api/auth/mobile/login`, form-encoded) or `runBrowserSso` → `POST /api/auth/mobile/sso/exchange {code, code_verifier}`; both end with `setToken(token)` + `queryClient.invalidateQueries(['me'])`. `logout()` = `POST /api/auth/mobile/logout` → `setToken(null)` → `queryClient.clear()` + `persister.removeClient()`. `getValidToken()` holds a module-level in-flight refresh promise (single-flight).
- **`browserSso.ts`** — as specified above; uses `expo-crypto` (PKCE pair), `expo-web-browser` `openAuthSessionAsync` + `expo-linking` `parse`. Never reads a token from the deep link — only `code` + `state` — and never sends the `code_verifier` over the deep link (only on the TLS `sso/exchange` POST).
- **`providers.ts`** — the registry; `visibleProviders(authConfig)` filters by `auth_type`/`oauth_enabled` from `/auth/type`.
- **`useAuthConfig.ts`** — `useQuery(['auth-config', serverUrl], () => apiFetch('/api/auth/type', { auth:false }))`.
- **`useEmailLogin.ts` / `useLogout.ts` / `useSessionRefresh.ts`** — thin TanStack mutations wrapping `SessionManager`.
- **`session.ts`** — Zustand store (`status`, `serverUrl`), `serverUrl` persisted to `appStorage`.
- **`AuthGate.tsx`** — `useCurrentUser()`; while loading show splash; on `isAuthError`/no-token → `<Redirect href="/(auth)/connect" />` (or `/login` if serverUrl set); else render children.
- **`(auth)/connect.tsx`** — server-URL field (default "Onyx Cloud" = `https://cloud.onyx.app`), validate reachability via `GET /auth/type`, store, advance to login.
- **`(auth)/login.tsx`** — email/password (with `textContentType`/`autoComplete` autofill) + provider buttons from `visibleProviders`. Generic error text on failure.
- **`config.ts`** — `getBaseUrl()` reads `session.ts`/`appStorage` server URL; dev fallback to `EXPO_PUBLIC_API_URL`.
- **`_layout.tsx`** — wrap `<Stack>` in `<AuthGate>`; register the `onyx://auth/callback` deep-link handler (delegates to the in-progress `runBrowserSso` promise).
- **`tokenStore.ts`** — pass `{ keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY }` to `setItemAsync`; the logout TODO in the header comment is now satisfied by `SessionManager.logout()`.

## Integration points

- **`backend/onyx/auth/users.py:1684`** — the `fastapi_users` backend list is the single extension point for the bearer backend (the framework already supports multiple backends).
- **`backend/onyx/auth/users.py:2251` & `:2573`** — the only two edits to shared OAuth code: an optional query-param read in `authorize`, and a guarded branch in `complete_login_flow`. Reuses all existing CSRF/state/PKCE validation and `user_manager.oauth_callback` (`:2549`).
- **`backend/onyx/main.py:572-690`** — registration site for the mobile gateway, following `include_auth_router_with_prefix` (rate-limiting + global prefix inherited).
- **`backend/onyx/server/manage/get_state.py:34` (`GET /auth/type`)** — reused for mobile config discovery, unchanged.
- **`backend/onyx/server/manage/users.py:885-954` (`GET /me`)** — becomes the post-login identity probe for mobile; authenticates the new Bearer because the bearer backend shares the existing strategy.
- **`mobile/src/api/client.ts:40-43`** — already injects `Authorization: Bearer`; the gateway just supplies a token. Optional enhancement: call `SessionManager.getValidToken()` here for proactive refresh.
- **`mobile/src/api/errors.ts` `isAuthError()` + `mobile/src/query/client.ts`** — the gate and the single reactive-refresh-and-retry key off the existing 401/402/403 classification (retry already skipped).
- **`mobile/src/query/focus.ts`** — the existing `AppState`→focus bridge is the hook for proactive foreground refresh.
- **`mobile/app.json`** — scheme `onyx` already matches `onyx://auth/callback`; bundle `app.onyx.mobile` unchanged.

## Important notes before implementation

- **EAS Dev Build required.** `expo-web-browser` OAuth (ASWebAuthenticationSession / Chrome Custom Tabs) does **not** work in Expo Go. Set up a dev build before testing the Google flow; email/password works without it.
- **CSRF cookie must live in the system browser, so `sso/start` is browser-opened, not fetched.** The app opens `…/auth/oauth/authorize?redirect=true&mobile_redirect_uri=…` *in the system browser* (a 302), exactly like the web `?redirect=true` path, so the CSRF cookie set on that response is present at the callback. Do **not** fetch the authorize URL as JSON from `apiFetch` and then open it — the CSRF cookie would land on the wrong client and the callback would reject it.
- **Reuse the registered IdP redirect URI.** The authorization URL must use the same `redirect_uri` (`{WEB_DOMAIN}/api/auth/oauth/callback`) the OAuth code-exchange uses and that Google already has registered. Do not introduce a new callback path — that would force every self-hosted admin to register a new redirect URI.
- **The deep link carries only a PKCE-bound one-time code, never a token.** Enforce: single-use (`GETDEL`), 60s TTL, TLS-only exchange, **app-generated PKCE** (`app_code_challenge` stored with the code; `sso/exchange` requires the matching `code_verifier`, S256, constant-time compare), `app_state` round-trip verification in the app, and a server-side `app_redirect_uri` allowlist. PKCE is the primary mitigation for custom-scheme hijack on self-hosted (no Universal Links there): a hijacked code is useless without the verifier, which is never transmitted over the deep link. Mobile SSO **requires** `app_code_challenge` — reject the flow if it's absent (don't silently fall back to a non-PKCE code). The backend↔Google leg remains a separate confidential-client exchange (secret server-side); PKCE there stays optional/off for Google.
- **Multi-tenant / tenant context.** `strategy.write_token` resolves/provisions the tenant from the user's email (`users.py:1366-1370`); the mobile login, refresh, and SSO-completion paths must execute inside the same tenant-resolution middleware as the web flow (they do, since they're mounted on the same app) — verify on the SSO-exchange path specifically.
- **Works across all three `AUTH_BACKEND`s.** Redis is always available (core infra) so the one-time code store works even when `AUTH_BACKEND=jwt`. `issue_session_credential` → `strategy.write_token` produces a valid Bearer for redis/postgres/jwt alike; the bearer backend's strategy reads it back. Note `jwt` tokens are not server-revocable — logout deletes locally but cannot revoke server-side (documented limitation; redis/postgres revoke properly via `destroy_token`).
- **Route-name collision avoidance.** Mount the bearer backend's auth/refresh/logout via the framework routers (`auth:mobile-bearer.*`) and do **not** re-mount the stock `/auth/login` — that name belongs to the cookie backend.
- **Security hygiene (from `01-research.md`):** token only in `expo-secure-store` THIS_DEVICE_ONLY; iOS Keychain survives uninstall + has no bulk-clear → explicit delete on logout; never persist the password; generic auth error messages (no enumeration); rely on existing backend rate-limiting; purge the persisted MMKV query cache on logout and give it an `encryptionKey` (or exclude PII queries) to close the plaintext-PII-at-rest gap flagged in `tokenStore.ts`.
- **Apple / App Store 4.8 (accepted risk).** Shipping Google without Sign in with Apple risks App Store rejection. The provider registry + shared `complete_mobile_sso` make Apple a small add (one provider descriptor + one button + an Apple OAuth client / native `AuthenticationServices` feeding the same exchange) if review forces it.
- **`prompt=none` silent-auth.** The Google authorize path already uses `prompt=consent` (`users.py:2300`) — keep interactive consent; do not add silent re-auth, which is the ASWebAuthenticationSession hijack vector.

## Later providers (designed-for, not built)

- **OIDC** — `GET /auth/oidc/{authorize,callback}` share `get_oauth_router`, so the same guarded `mobile_redirect_uri` param + `complete_mobile_sso` branch covers it; mobile adds an `oidc` registry row. PKCE already supported via `OIDC_PKCE_ENABLED`.
- **SAML** — `backend/onyx/server/saml.py` callback gets the same `if client=="mobile": complete_mobile_sso(...)` branch (SP-initiated); mobile adds a `saml` row. No native SDK needed — the system browser handles the IdP.
- **Apple** — register an Apple OAuth client through the same generic path, or use native `expo-apple-authentication` feeding the same `/auth/mobile/sso/exchange` seam.
- **Token rotation (Approach B)** — swap `issue_session_credential` to mint a short access token + rotating refresh family + reuse-detection, add a real `/auth/mobile/refresh` body and a `mobile_session` table. No gateway or mobile-client API change.
