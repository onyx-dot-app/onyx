> Status: draft · Task: mobile-auth

# Mobile Authentication — Research

## Requirement

Build authentication for the Onyx mobile app (Expo / React Native) in the spirit of the desktop app — **email/password + Google OAuth in V1**, with **SAML + OIDC (and Apple Sign In) added later** — validated against industry best practices and security standards.

## Clarifications (verbatim Q&A)

**Q1 — The desktop "pattern" is a thin WebView (cookie auth, no native code); the mobile foundation already chose native + Bearer-token + secure-store. Which path?**
→ **Native auth.** Native login screens + Bearer token from `expo-secure-store`; reuse the SAME backend, adding small mobile-friendly token endpoints. OAuth/SAML/OIDC run in the system browser and return via deep link. (Explicitly NOT the webview-cookie approach.)

**Q2 — Which backend(s) must V1 target? (Decides the OAuth redirect strategy.)**
→ **Cloud + self-hosted both first-class in V1**, whatever complexity that adds. (This rules out relying on Universal/App Links alone — they only cover `cloud.onyx.app` — and pushes us to a host-agnostic backend SSO-bridge + deep-link return.)

**Q3 — App Store Guideline 4.8 requires Sign in with Apple if Google is offered. Include SIWA in V1?**
→ **No.** Google + email/password only for V1; handle Apple later / accept the App Store-rejection risk. (We still build the OAuth layer provider-generic so Apple slots in cheaply.)

## Current status & reuse (from codebase scan — exact paths)

### Backend (`backend/`) — fastapi-users 12.x, **cookie-transport only today**
- **User model + OAuthAccount**: `backend/onyx/db/models.py:307-463`. `UserManager` + `FastAPIUsers` setup in `backend/onyx/auth/users.py`.
- **Email/password**: `POST /auth/login` (`OAuth2PasswordRequestForm`) → **Set-Cookie `fastapiusersauth`** (HttpOnly, `samesite=lax`, `secure` if https), 7-day expiry. Router reg `backend/onyx/main.py:572-577`. `cookie_transport` `backend/onyx/auth/users.py:1326-1330`.
- **⚠️ Transport is cookie-only.** All three auth backends use `CookieTransport`: redis (`users.py:1549`), postgres (`:1553`), jwt (`:1557`). **No `BearerTransport` is mounted.** The session **strategies** are transport-agnostic, though — `write_token`/`read_token`/`destroy_token`/`refresh_token` operate on raw token strings (`users.py:1363/1384/1400/1405`). So a Bearer transport / token-returning endpoint *can* be added cleanly, but it is **net-new work** — the earlier "bearer already supported" note was inaccurate.
- **Auth backends** via `AUTH_BACKEND` env = `redis|postgres|jwt`; strategy selection `users.py:1539-1560`. Redis/Postgres = **stateful, server-side, revocable** opaque tokens (`secrets.token_urlsafe`, 7-day TTL = `SESSION_EXPIRE_TIME_SECONDS`). JWT = stateless, **not revocable** (its own docstring concedes this, `users.py:1463-1509`); JWT is **forbidden in multi-tenant/cloud** (`users.py:1540`).
- **Refresh already exists**: `get_refresh_router` `users.py:1600-1681` (`POST /auth/refresh`); `TenantAwareRedisStrategy.refresh_token` `:1405-1428` extends TTL in place; returns via `backend.transport.get_login_response` (`:1661`). Web calls it every 10 min (not for SAML/OIDC).
- **Google OAuth**: `GET /auth/oauth/authorize` → `{authorization_url}` (sets STATE+CSRF cookies); `GET /auth/oauth/callback` exchanges code, upserts user by email, calls `backend.login()` → cookie. Redirect hardcoded `f'{WEB_DOMAIN}/auth/oauth/callback'`. Code `users.py:2183-2521`; `complete_login_flow` `users.py:2523-2607`; reg `main.py:601-626`. **Google path is non-PKCE** (the client secret lives server-side — correct for a public client).
- **OIDC**: `GET /auth/oidc/{authorize,callback}`; PKCE optional via `OIDC_PKCE_ENABLED` (gen `users.py:2278-2295`); reg `main.py:636-665`.
- **SAML** (`backend/onyx/server/saml.py:35-298`): `/auth/saml/authorize` → `{authorization_url}`, `/auth/saml/callback` (GET+POST), `/auth/saml/logout`; extracts email, upserts, `backend.login()` → cookie. Reg `main.py:674-678`. No native mobile SDK exists for SAML.
- **AUTH_TYPE** enum `{basic, google_oauth, oidc, saml, cloud}` `backend/onyx/configs/constants.py:314-321`. Frontend discovers config via **`GET /auth/type`** (`AuthTypeMetadata`: `auth_type`, `requires_verification`, `password_min_length`, `oauth_enabled`, …) `backend/onyx/server/manage/get_state.py:34-59`.
- **`/me`**: `backend/onyx/server/manage/users.py:885-954` → `UserInfo` (`models.py:122-202`); checks `oidc_expiry`.
- **CORS**: `CORS_ALLOWED_ORIGIN` env; `'*'` disables credentials (`shared_configs/configs.py:146-170`, `main.py:699-712`). Irrelevant for a native client (no browser origin), but relevant if a webview were ever used.
- **House rules** (CLAUDE.md): raise `OnyxError` (not `HTTPException`); new FastAPI endpoints are typed, **no `response_model`**; DB ops only under `backend/onyx/db` / `backend/ee/onyx/db`; alembic migrations written by hand.

### Mobile (`mobile/`) — Expo SDK 56, RN 0.85, React 19.2, Expo Router, TanStack Query v5 + MMKV, Zustand, NativeWind v4, Bun
- **`apiFetch`** `mobile/src/api/client.ts:41-43` **already injects `Authorization: Bearer <token>`** from `getToken()` (auth=true default); base URL from `EXPO_PUBLIC_API_URL` (`mobile/src/api/config.ts:21`, build-time, "runtime URL is future work"); errors normalized to `ApiError` (`mobile/src/api/errors.ts`, `isAuthError()` → 401/402/403).
- **Token store** `mobile/src/api/auth/tokenStore.ts`: `expo-secure-store`, key `onyx.auth.access_token`, `getToken()`/`setToken()`. **Documented TODOs**: clear query cache + persister on logout; identity-scope the cache; encrypt the MMKV query cache (PII).
- **`useCurrentUser`** `mobile/src/hooks/useCurrentUser.ts` → `GET /api/me`, query key `['me']`. `CurrentUser` type minimal (`mobile/src/api/types.ts`).
- **Routing**: `mobile/src/app/_layout.tsx` is a bare `Stack` (`PersistQueryClientProvider`) — **NO auth-gate, no `(auth)` group, no redirect-to-login** yet. `index.tsx` is home.
- **Query client** `mobile/src/query/client.ts`: retry skips 401/402/403. `focus.ts`/`online.ts` bridge `AppState`/NetInfo. MMKV instances (app + query-cache) `mobile/src/state/storage.ts`.
- **`app.json`**: scheme **`onyx`**; bundle `app.onyx.mobile`. Deps present: `expo-secure-store` ~56.0.4, `expo-linking` ~56.0.13, `expo-constants`. **ABSENT**: `expo-auth-session`, `expo-web-browser`, `expo-crypto`.
- Shared `@onyx-ai/shared/native`: design tokens (`varsLight`/`varsDark`), types `Page<T>`/`Result<T>`.

### Desktop (`desktop/`) — reference only, do NOT copy
- A **thin Tauri WebView** that loads `server_url` (default `https://cloud.onyx.app`, user-configurable via `config.json`, `src-tauri/src/main.rs:35,285`). **Zero native auth code** — login happens inside the webview via the web app's cookie session. Its one durable lesson for us: **"configurable server URL" (cloud + self-hosted) is an established product expectation.**

## Industry best practices (web research — honor or consciously deviate)

- **Auth Code + PKCE (S256) is MANDATORY** for public native clients (RFC 8252 "OAuth 2.0 for Native Apps"; RFC 9700 OAuth Security BCP, Jan 2025; OAuth 2.1 drops implicit). Never embed a client secret in the app — the secret-bearing token exchange must run on the backend. — https://www.rfc-editor.org/rfc/rfc8252.html , https://datatracker.ietf.org/doc/rfc9700/
- **System browser only** (ASWebAuthenticationSession iOS / Chrome Custom Tabs Android); **embedded WebViews are forbidden** for OAuth (RFC 8252 §8.12 — host app can keylog). `expo-auth-session` + `expo-web-browser` implement the compliant path. — https://docs.expo.dev/guides/authentication/
- **Bearer in `Authorization` header, not cookies**, for native. **Never put a token in a deep link** — return a short-lived single-use **code** on the deep link and exchange it over TLS. — https://reactnative.dev/docs/security
- **Tokens only in `expo-secure-store`** (iOS Keychain / Android Keystore); never AsyncStorage/unencrypted MMKV (OWASP Mobile **M1** Improper Credential Usage / **M9** Insecure Storage). iOS Keychain **persists across app uninstall** and has **no bulk-clear** → delete explicitly on logout; use `keychainAccessible` `*_THIS_DEVICE_ONLY`. — https://mas.owasp.org/MASVS/ , https://docs.expo.dev/versions/latest/sdk/securestore/
- **Short-lived access tokens (~5–15 min) + refresh-token ROTATION with reuse detection** (revoke the whole token family on replay) is a **MUST for public clients** per RFC 9700 §4.14. Pair with **single-flight** (serialized) refresh + **proactive** pre-expiry refresh (account for clock skew). Logout MUST revoke the refresh token server-side AND delete local secrets. — https://datatracker.ietf.org/doc/html/rfc9700 , https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation
- **SAML has NO native mobile SDK.** Bridge it: open the backend's existing browser SAML/OIDC login in the system browser; on success the backend 302-redirects to the app's deep link with a one-time code the app exchanges for a token. Cheap because Onyx already terminates SAML/OIDC for web. Prefer **SP-initiated** over IdP-initiated. — https://workos.com/docs/integrations/react-native-expo , https://learn.microsoft.com/en-us/entra/identity-platform/scenario-token-exchange-saml-oauth
- **Redirect URIs**: Universal Links (iOS) / App Links (Android) are safer than custom schemes (scheme hijacking) but **require domain ownership** — works for `cloud.onyx.app`, NOT arbitrary self-hosted. For self-hosted, a **custom scheme (`onyx://`) + PKCE + state + single-use short-TTL code + exact redirect-URI matching** is the pragmatic mitigation. Beware ASWebAuthenticationSession `prompt=none` silent-auth hijack — require user consent. — https://evanconnelly.github.io/post/ios-oauth/
- **Expo specifics**: OAuth needs an **EAS Dev Build** (not Expo Go); use `AuthSession.makeRedirectUri()`; re-run `prebuild` after changing `expo.scheme`; register exact redirect URIs per build.
- **Email/password**: never store the password (store only the token); **generic errors** to prevent account enumeration; rate-limit/throttle; optional breached-password check (Pwned Passwords k-anonymity); platform autofill / `textContentType`.
- **App Store Guideline 4.8**: must offer **Sign in with Apple** if any third-party social login (Google) is offered — V1 Google-only is an accepted **rejection risk**.

## Approaches

### Approach A — Simplicity-First: "Bearer-the-Session"
Reuse the existing stateful fastapi-users session token **verbatim** as the mobile Bearer value. Add the minimum: a `POST /auth/login/mobile` that returns the same session token as JSON (instead of Set-Cookie), and a one-time-code branch in `complete_login_flow` that, for `client=mobile`, mints a 60 s single-use Redis code and 302s to `onyx://auth/callback?code=…` (the app exchanges it at `POST /auth/oauth/mobile/exchange`). Refresh/logout reuse the existing `/auth/refresh` + `/auth/logout` (sliding 7-day TTL, server-revocable). On mobile: login screens, an auth-gate around the bare `Stack`, a deep-link handler, and the `tokenStore` hardening TODOs. **No new token type, table, or migration.**
- **Token model**: one opaque 7-day server-side session token = access *and* session; **no separate refresh token, no rotation** in V1 (explicit deviation from RFC 9700, mitigated by server-side revocability + Keychain-only storage + token never in a URL).
- **Effort**: smallest — backend ~150–250 LOC (no migration), mobile ~500–700 LOC, ~2 PRs.
- **Risks**: no rotation/reuse-detection (7-day stolen-token window); one-time-code bridge assumes Redis (`AUTH_BACKEND=jwt` self-hosted has no Redis session — must gate or store the code in Postgres); multi-tenant login must run in the tenant middleware context.

### Approach B — Scalability/Security-First: "Sentinel"
Build a **purpose-built mobile token subsystem**: short-lived (~10 min) opaque access token + **rotating refresh token bound to a per-device token family with reuse detection**, exposed at `/auth/mobile/{token,refresh,revoke,sessions}`. New `mobile_session` table (one row per device → per-device revocation, a device-session list, audit fields: last_ip/UA/last_used_at) + hand-written migration; a `MobileTokenService`; a `BearerTransport`-backed authenticator composed with the existing cookie authenticator. OAuth/SAML/OIDC reuse the existing browser endpoints, swapping only the final "set cookie + 302 to WEB_DOMAIN" step for "mint one-time PKCE-bound code + 302 to the app." Mobile adds single-flight proactive refresh, biometric-gated refresh-token storage, and the auth-gate.
- **Token model**: full RFC 9700 — ~10 min access + rotating refresh family, replay → revoke family + emit anomaly event; instant per-device server-side revocation; access validated O(1) in Redis, refresh durable in Postgres.
- **Effort**: largest — backend ~900–1200 LOC (~5 PRs incl. model/migration/service/bridge/cleanup), mobile ~700–1000 LOC (~3–4 PRs); each later provider ~50–150 LOC.
- **Risks**: reuse-detection false-positives on flaky networks (needs single-flight + server family-lock + grace window); per-refresh Postgres writes need indexing + a Celery cleanup task; biometric enrollment changes can lock users out (needs re-login fallback); most code on a security-critical path.

### Approach C — Flexibility-First: "Mobile Auth Gateway (BFF)"
Introduce **one thin gateway** in front of the existing machinery rather than forking it: a uniform browser-SSO pair `GET /auth/mobile/sso/{start,exchange}` + native bearer endpoints `POST /auth/mobile/{login,refresh,logout}`. Two seams carry all the variation: a backend **`BrowserSSOProvider` registry** (V1 = Google wrapping the existing OAuth logic; SAML/OIDC/Apple = later registry entries) and a one-function **`issue_session_credential(user)` token seam** (V1 wraps the existing stateful token via a mounted `BearerTransport`; a future rotation subsystem drops in behind it with no gateway/mobile change). Mobile gets one `SessionManager` + a `providerRegistry` (each provider = a tiny descriptor) over the existing `apiFetch`/`tokenStore`. Adding a provider later = one backend provider class + one mobile registry row + a button.
- **Token model**: V1 reuses the existing **revocable 7-day stateful token as a Bearer** (consciously *not* shortened, since there's no refresh token yet); rotation is a **documented, deferred seam**, not built.
- **Effort**: medium — backend ~400–600 LOC (~3 PRs: bearer backend + login/refresh/logout, provider registry + SSO start/exchange + code store, hardening), mobile ~600–900 LOC (~3 PRs); later providers well under one PR each.
- **Risks**: a second `AuthenticationBackend` can collide with the cookie backend's route names (must namespace + not re-mount the stock auth router); same multi-tenant + custom-scheme-hijack caveats as A/B; one extra indirection layer for a 2-provider V1.

## Cross-comparison

- **Common to all three** (the decided, non-negotiable core): native screens; `Authorization: Bearer` (reuse `apiFetch`); `expo-secure-store` only; OAuth in the **system browser** (`expo-web-browser`) with a **host-agnostic backend one-time-code + `onyx://` deep-link** return (the only redirect strategy that serves cloud **and** self-hosted); add an auth-gate + `(auth)` route group; add `expo-auth-session`/`expo-web-browser`/`expo-crypto`; resolve the `tokenStore` logout/cache TODOs; needs an EAS Dev Build.
- **The real fork is the credential model + how much structure to add**:
  - **A** ships fastest and is simplest to reason about, but deviates from RFC 9700 (no rotation) and hardcodes the two V1 flows (later providers re-open OAuth code).
  - **B** is the security/scale end-state (rotation, reuse-detection, per-device revocation, audit) but is the most new security-critical code + DB state for a 2-provider launch.
  - **C** keeps the proven revocable token for V1 but formalizes a provider-registry + token-issuance seam, so SAML/OIDC/Apple and the rotation upgrade land later as config/one-function swaps rather than rewrites. It is the middle on effort and the best on future-change cost.
- **All three converge to the same end-state** (B's rotating-family token reachable via A's "upgrade later" note or C's `issue_session_credential` seam) — they differ mainly in whether that security is built now (B) or seamed-for-later (A/C), and in how provider-extensibility is structured (ad-hoc in A, registry in C, generic-bridge in B).

## Chosen approach

**Approach C — Mobile Auth Gateway (BFF) with a Provider Registry + Token-Issuance Seam.**

Rationale: the user's two stated futures — (1) more providers (SAML/OIDC/Apple) and (2) cloud + self-hosted both first-class — are exactly the changes C makes config-shaped (provider registry rows + runtime base URL), while reusing Onyx's existing, battle-tested auth core and keeping B's security as a clean upgrade path behind `issue_session_credential`.

V1 credential decision: **reuse the existing revocable stateful session token, presented as a Bearer** (the seam keeps rotation deferrable). Rotation/reuse-detection (Approach B's subsystem) is explicitly **deferred**, not built — it lands later behind the `issue_session_credential` seam and a new `/auth/mobile/refresh` body, with no gateway or mobile rework.
