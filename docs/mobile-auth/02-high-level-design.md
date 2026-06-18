> Status: active · Task: mobile-auth · Approach: C — Mobile Auth Gateway (BFF) with a Provider Registry + Token-Issuance Seam

# Mobile Authentication — High-Level Design

## What it does

Lets a person sign in to the Onyx mobile app (Expo / React Native) with **email + password** or **Google**, against **either Onyx Cloud or their own self-hosted Onyx server**, and stay signed in securely. It is the first auth the mobile app has ever had: today the app has a token-injecting HTTP client and a `/api/me` hook but no way to *get* a token and no login screen. SAML, OIDC, and Sign in with Apple are designed to slot in later as small additions, not rewrites.

## How it works (end-to-end walkthrough)

The mobile app is a **native** client (not a webview). It authenticates by obtaining a **Bearer token** from the backend and sending it in the `Authorization` header on every request — the app's HTTP client (`mobile/src/api/client.ts`) already does this injection; it just never had a token to inject. The token it gets is the **same stateful, server-side, revocable session token Onyx already issues to the web app** — we simply hand it to the mobile client as a Bearer value instead of a browser cookie.

Three things make this work end-to-end:

1. **A second "transport" on the existing backend auth.** Onyx's auth (fastapi-users) currently returns its session token only as a `Set-Cookie` (a "cookie transport"). We add a parallel **Bearer transport** that returns the *same* token as JSON (`{access_token, token_type}`). This gives the mobile app three endpoints essentially for free — `POST /auth/mobile/login` (email/password → token JSON), `POST /auth/mobile/refresh` (extend the session), `POST /auth/mobile/logout` (revoke it) — because the backend's auth framework already knows how to build these routers for any transport. The token itself is unchanged, so the rest of the backend keeps authenticating requests exactly as before.

2. **A backend "SSO bridge" for Google (and later SAML/OIDC/Apple).** A native app must run OAuth in the **system browser**, never an embedded webview (this is a hard security rule — RFC 8252). So when the user taps "Continue with Google," the app first generates a **PKCE pair** (a random `code_verifier` it keeps in memory + its SHA-256 `code_challenge`), then opens the system browser at the backend's **existing** Google authorize URL with three extra hints: a return address (`onyx://auth/callback`), a one-time random `state`, and the `code_challenge`. The user signs in with Google entirely in the trusted system browser. Google redirects back to the backend's **existing, already-registered** Google callback — so self-hosted admins don't have to register any new redirect URL. The callback recognizes "this login came from mobile," mints the session token, stores it in Redis behind a **single-use 60-second code bound to that `code_challenge`**, and redirects the browser to `onyx://auth/callback?code=…`. The app catches that deep link, checks the `state` matches, and `POST`s the code **plus its `code_verifier`** (over HTTPS) to exchange them for the real token; the backend recomputes the challenge from the verifier and rejects a mismatch. **The token never travels in the deep link — only an opaque, PKCE-bound, one-time code does** (also a hard rule; deep links can be intercepted). The PKCE binding means that even if a malicious co-installed app hijacks the `onyx://` redirect and steals the code, it cannot exchange it — it doesn't hold the verifier. This is the key protection for the self-hosted custom-scheme case (which can't use domain-verified Universal Links).

   > Two-leg note on PKCE: the **app↔backend** exchange leg uses PKCE as just described. The **backend↔Google** OAuth exchange is a separate, confidential-client flow where the client secret lives server-side (the app never sees Google's code), so PKCE there is optional defense-in-depth and is currently off for Google (`enable_pkce=False`; OIDC can enable it via `OIDC_PKCE_ENABLED`).

3. **A native login UI + an auth gate.** The app gains a `(auth)` route group with a login screen and a "connect to server" step (so cloud and self-hosted are both first-class), plus a gate at the app root that sends signed-out users to login and signed-in users to the app. The token lives only in the device keychain (`expo-secure-store`), and logout both revokes it on the server and wipes it (and the cached `/api/me` data) locally.

The "flexibility" of this approach lives in two small seams: a **token-issuance seam** (`issue_session_credential`) that today returns the existing session token but can later return a short-lived access token + rotating refresh token with no change to the gateway or the app; and a **provider registry** (a tiny list of descriptors) so adding SAML/OIDC/Apple is a registry row + a button, reusing the same browser → one-time-code → exchange machinery.

## Component interaction

```
                         MOBILE APP (Expo / React Native)
  ┌───────────────────────────────────────────────────────────────────────┐
  │  (auth) group: Connect screen → Login screen (email/pw + provider btns) │
  │        │                                   │                            │
  │        ▼                                    ▼                           │
  │  runtime base-URL store            SessionManager  ◄── providerRegistry │
  │  (MMKV appStorage) ── getBaseUrl()    │  login() / logout() / getValidToken()
  │                                       │            │                    │
  │                                       │            ▼                    │
  │                                       │      browserSso runner          │
  │                                       │   (expo-web-browser + expo-      │
  │                                       │    crypto PKCE + expo-linking)  │
  │                                       ▼            │                    │
  │                                  tokenStore        │                    │
  │                              (expo-secure-store)    │                   │
  │                                       │            │                    │
  │   apiFetch (injects Authorization: Bearer) ◄───────┘                    │
  │      │  AuthGate (uses useCurrentUser → /api/me)                        │
  └──────┼──────────────────────────────────────────────────────────────── ┘
         │  HTTPS (base URL = cloud.onyx.app OR self-hosted)        ▲ system browser
         ▼                                                          │ (Google login)
  ┌───────────────────────────── ONYX BACKEND (FastAPI) ───────────────────┐
  │  Mobile Auth Gateway (new):                                             │
  │   • bearer AuthenticationBackend  → /auth/mobile/{login,refresh,logout} │
  │   • POST /auth/mobile/sso/exchange  (code + code_verifier → token JSON) │
  │   • issue_session_credential(user, strategy)   ◄── token-issuance seam  │
  │   • one-time SSO code store (Redis, 60s, single-use, PKCE-bound)        │
  │                                                                         │
  │  Existing auth (reused, tiny guarded additions):                        │
  │   • /auth/oauth/authorize  (+ optional mobile_redirect_uri/app_state)   │
  │   • /auth/oauth/callback → complete_login_flow                          │
  │        └─ if state.client == "mobile": complete_mobile_sso() ───────────┘
  │   • fastapi-users UserManager, redis/postgres session strategy          │
  │   • GET /auth/type (config discovery)   • GET /me (current user)         │
  └─────────────────────────────────────────────────────────────────────────┘
```

## Key components

- **Bearer `AuthenticationBackend`** — second backend on the existing `fastapi_users`, same session strategy, Bearer transport. Yields `/auth/mobile/{login,refresh,logout}`. (new)
- **`issue_session_credential(user, strategy)`** — the token-issuance seam; V1 returns the existing stateful token; future home of access+refresh rotation. (new)
- **One-time SSO code store** — 60-second, single-use Redis entry mapping `code → {token, code_challenge}`, so the deep link carries only a PKCE-bound code. (new)
- **`complete_mobile_sso(...)` branch** — the shared "mobile login finished" path called by the existing OAuth callback (later OIDC/SAML) when the login originated from mobile. (modified — small guarded branch in `complete_login_flow`)
- **Guarded mobile params on `/auth/oauth/authorize`** — optional `mobile_redirect_uri` + `app_state` + `app_code_challenge`, the redirect validated against an allowlist; reuses the already-registered IdP callback. (modified)
- **`POST /auth/mobile/sso/exchange`** — swaps the one-time code **+ `code_verifier`** for the token JSON over HTTPS, after verifying the PKCE challenge. (new)
- **Mobile `SessionManager` + provider registry** — `login(method)/logout()/getValidToken()` with single-flight refresh; registry maps `password|google` (later `saml|oidc|apple`) to descriptors. (new)
- **Browser-SSO runner** — opens the authorize URL in the system browser and captures/validates the `onyx://auth/callback` deep link. (new)
- **Auth gate + `(auth)` route group + Connect screen** — login/redirect UX and the runtime backend-URL entry that makes cloud + self-hosted first-class. (new + modified `_layout.tsx`, `config.ts`)
- **`tokenStore` hardening** — `keychainAccessible` THIS_DEVICE_ONLY; logout clears the token *and* the persisted query cache. (modified)
- **Config discovery** — reuse `GET /auth/type` so the login screen shows the right buttons per backend. (reused)

## End-to-end scenario (primary use case: Google sign-in to a self-hosted server)

1. User opens the app → AuthGate sees no token → routes to the **Connect** screen.
2. User enters `https://onyx.acme.com` (or picks "Onyx Cloud") → stored in the runtime base-URL store; the app calls `GET /api/auth/type` and learns `google_oauth` is enabled → shows email/password + a **Continue with Google** button.
3. User taps **Continue with Google** → the app generates a random `state` and a **PKCE pair** (`code_verifier` kept in memory + `code_challenge` = S256(verifier)), then opens the **system browser** at `https://onyx.acme.com/api/auth/oauth/authorize?redirect=true&mobile_redirect_uri=onyx://auth/callback&app_state=<state>&app_code_challenge=<challenge>`.
4. The backend sets its CSRF cookie in that browser session and redirects to Google. The user authenticates with Google in the trusted browser.
5. Google redirects to the backend's existing `…/api/auth/oauth/callback`. The callback validates CSRF + state, exchanges the Google code (using the **server-side** client secret), and upserts the user — all existing code.
6. Because `state` says `client=mobile`, the callback runs `complete_mobile_sso`: it mints the session token (`issue_session_credential`), stores it in Redis under a single-use 60s **code bound to the `app_code_challenge`**, and redirects the browser to `onyx://auth/callback?code=<code>&state=<state>`.
7. The system browser hands that deep link to the app. The app verifies the returned `state` equals the one it generated, then `POST /api/auth/mobile/sso/exchange {code, code_verifier}` over HTTPS.
8. The backend deletes-on-read the code, **verifies S256(code_verifier) == the stored challenge** (else 401), and returns `{access_token, token_type:"bearer"}`. The app stores the token in the keychain, invalidates `['me']`, and the gate now routes into the app — `/api/me` succeeds because `apiFetch` attaches the Bearer.

(Email/password is steps 1–2, then: user submits credentials → `POST /api/auth/mobile/login` → token JSON → store → in.)

## Sequence of key operations

1. Resolve backend base URL (cloud default or user-entered self-hosted) and discover auth config (`GET /auth/type`).
2. Authenticate: either email/password to `/auth/mobile/login`, or the system-browser Google flow (app-generated PKCE pair) that ends in a PKCE-bound one-time code exchanged with its `code_verifier` at `/auth/mobile/sso/exchange`.
3. Persist the returned Bearer token in `expo-secure-store`; invalidate the `['me']` query.
4. AuthGate re-checks `/api/me`; on success render the app, on 401 route to login.
5. Keep the session alive: single-flight proactive refresh via `/auth/mobile/refresh` (on foreground + before expiry); one reactive retry on a 401.
6. Logout: `/auth/mobile/logout` (server revokes the token) → delete the keychain token → `queryClient.clear()` + purge the persisted cache.

## Key decisions & why

- **Reuse the existing session token as a Bearer, behind an `issue_session_credential` seam — do not build rotation in V1.** The token is already stateful and server-revocable (unlike a stateless JWT), which covers the most important property (real logout / kill-session) for a 2-provider launch. RFC 9700's refresh-token rotation is the correct end-state but is a large security-critical subsystem; the seam lets it land later with no gateway/app rework. (From `01-research.md`: RFC 9700 rotation MUST for public clients, deferred consciously.)
- **System browser + PKCE-bound one-time code on the deep link (never the token).** RFC 8252 forbids embedded webviews for OAuth and deep links are interceptable; returning a single-use, short-TTL, TLS-exchanged code **bound to an app-generated PKCE challenge** is the standard mitigation and is what makes the flow safe on a **custom scheme**, which we need because self-hosted instances can't use domain-verified Universal Links. The PKCE binding ensures a hijacked code is unusable without the verifier the app never transmitted over the deep link. (The separate backend↔Google leg keeps the client secret server-side, so PKCE there is optional and currently off.)
- **Reuse the existing, already-registered IdP callback (don't add a new redirect URL).** A small guarded param on `/auth/oauth/authorize` plus a branch in the existing callback means self-hosted admins change nothing in their Google console — critical for "self-hosted first-class." It also keeps the OAuth code-exchange (which needs the client secret) entirely server-side.
- **Bearer transport as a second backend, not a fork.** fastapi-users namespaces router names by backend, so a second `mobile-bearer` backend gives login/refresh/logout for free with no collision against the web cookie backend, and the existing per-request authenticator validates the Bearer with zero per-route changes.

## What existing behavior changes

- **Web/desktop: none.** The cookie flow, web login, and all existing endpoints are untouched; the only edits to shared code are additive and guarded (a second backend in a list, an optional query param, and a branch that only fires when `client=mobile`).
- **Mobile: net-new.** The app gains login, an auth gate, and a runtime server-URL step. Users will notice the app now requires sign-in (it previously had no auth and `/api/me` always 401'd).
- **Backend ops:** three new mobile endpoints + a tiny amount of Redis state (the 60s one-time codes). No new database table, no migration in V1.
