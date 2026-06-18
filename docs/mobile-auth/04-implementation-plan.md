> Status: active · Task: mobile-auth

# Mobile Authentication — Implementation Plan

> Approach C — Mobile Auth Gateway (BFF). V1 = email/password + Google, cloud + self-hosted, native Bearer auth with Leg-2 PKCE. Full design in `02-high-level-design.md` / `03-detailed-design.md`.

## Issues to Address

The Onyx mobile app (`mobile/`) has no authentication. It ships an HTTP client that injects `Authorization: Bearer <token>` (`mobile/src/api/client.ts:40-43`), a `useCurrentUser` → `/api/me` hook, and an `expo-secure-store` token seam (`mobile/src/api/auth/tokenStore.ts`) — but there is no way to obtain a token, no login UI, and no auth-gated routing (`mobile/src/app/_layout.tsx` is a bare `Stack`). The backend only issues its session token as an HttpOnly cookie (`CookieTransport`, `backend/onyx/auth/users.py:1326`), which a native client can't use cleanly.

Outcome: a user can sign in to the mobile app with **email/password or Google**, against **Onyx Cloud or a self-hosted instance**, receive the existing revocable session token as a **Bearer**, stay signed in (proactive refresh), and log out (server revocation + local wipe). The design adds two seams (`issue_session_credential`, a provider registry) so SAML/OIDC/Apple and token-rotation land later as small additions, not rewrites. All web/desktop behavior is unchanged; backend edits are additive and guarded.

## Important Notes

- **Reuse the existing session token as a Bearer — don't build rotation in V1.** Mint via an `issue_session_credential(user, strategy)` seam that today calls `strategy.write_token(user)` (the same opaque, server-revocable token web gets; `users.py:1363-1382`). RFC 9700 refresh-rotation is the deferred end-state behind that seam. (`01-research.md` → RFC 9700.)
- **Second `AuthenticationBackend`, not a fork.** `fastapi_users` takes a list of backends (`users.py:1684`) and namespaces router names by backend name, so a `mobile-bearer` backend (same `get_strategy`, `BearerTransport`) yields `/auth/mobile/{login,refresh,logout}` with no collision against the web `auth:redis.*` routes. The existing per-request authenticator validates the Bearer with zero per-route change (`/me` at `backend/onyx/server/manage/users.py:885-954`).
- **Reuse the already-registered IdP callback.** A guarded optional param on `/auth/oauth/authorize` (`users.py:2251`) plus one branch in `complete_login_flow` before `backend.login` (`users.py:2573`) means self-hosted admins register **no** new Google redirect URI. The secret-bearing Google code exchange stays fully server-side (Leg 1 is a confidential-client flow; PKCE optional/off there).
- **System browser + PKCE-bound one-time code on the deep link (never the token).** RFC 8252: no embedded webview; deep links are interceptable. App generates a PKCE pair (`expo-crypto`), passes `app_code_challenge` to authorize; the backend mints the token, stores it in Redis under a single-use 60s code **bound to the challenge**, and 302s to `onyx://auth/callback?code=…`. Exchange requires `code_verifier` (S256, constant-time). This is the primary mitigation for custom-scheme hijack on self-hosted (no Universal Links there). (`01-research.md` → RFC 8252 / RFC 9700.)
- **Works across all `AUTH_BACKEND`s.** Redis is always available (core infra) so the one-time code store works even for `AUTH_BACKEND=jwt`; `write_token` mints a valid Bearer for redis/postgres/jwt. Caveat: `jwt` tokens aren't server-revocable (logout deletes locally only) — documented limitation.
- **Multi-tenant.** `write_token` resolves/provisions the tenant from the user's email (`users.py:1366-1370`); the mobile login/refresh/SSO-completion paths run inside the same tenant middleware (same app) — verify specifically on the SSO-exchange path.
- **Runtime base URL is in scope.** "Cloud + self-hosted both first-class" requires the user-entered server URL the `config.ts` comment already anticipates (`mobile/src/api/config.ts:1-19`); auth can't ship without it.
- **Security hygiene (`01-research.md`):** token only in `expo-secure-store` `THIS_DEVICE_ONLY`; iOS Keychain survives uninstall + has no bulk-clear → explicit delete on logout; never persist the password; generic auth errors (no enumeration); rely on existing backend rate-limiting; purge the persisted MMKV query cache on logout and give it an `encryptionKey` (or exclude PII queries) — closes the plaintext-PII gap flagged in `tokenStore.ts:10-21`.
- **EAS Dev Build required** for the OAuth/system-browser path (`expo-web-browser` doesn't work in Expo Go). Email/password works without it.
- **App Store 4.8 (accepted risk):** Google without Sign in with Apple risks rejection; the registry makes Apple a cheap later add.
- **House rules (CLAUDE.md):** raise `OnyxError` (not `HTTPException`); new endpoints typed, no `response_model`; DB ops only under `backend/onyx/db` (N/A — no DB in V1); strict typing in Python + TS.

## Implementation Strategy

Backend and mobile tracks are largely independent; within each, steps are ordered so each is a coherent, testable change.

**Backend**

1. **Bearer transport + second backend.** Add `bearer_transport = BearerTransport(tokenUrl="auth/mobile/login")` beside `cookie_transport`; build `mobile_auth_backend` (`name="mobile-bearer"`, same `get_strategy` as the active backend at `users.py:1547-1560`); append it to the `fastapi_users` backend list (`users.py:1684`). (`backend/onyx/auth/users.py`)
2. **Token-issuance seam + one-time PKCE code store + SSO completion.** New `backend/onyx/auth/mobile_sso/` package: `tokens.py` (`issue_session_credential`), `code_store.py` (`store_sso_code(token, code_challenge, tenant_id)` / `consume_sso_code(code, code_verifier)` with atomic `GETDEL` + S256 verify, reusing existing PKCE helpers at `users.py:2279`), `sso_completion.py` (`complete_mobile_sso` — require challenge, validate redirect allowlist, mint, store, 302).
3. **Guarded mobile params + callback branch on the existing OAuth router.** In `users.py` `authorize` (`:2251`) accept optional `mobile_redirect_uri` / `app_state` / `app_code_challenge` and fold them into the signed `state_data`; in `complete_login_flow` (`:2523`) add `if state_data.get("client") == "mobile": return await complete_mobile_sso(...)` before `backend.login` (`:2573`). Additive/guarded — web path unchanged when absent.
4. **Mobile gateway router + registration + config.** New `backend/onyx/server/auth/mobile.py`: mount the bearer backend's auth/refresh/logout routers under `/auth/mobile`, plus `POST /auth/mobile/sso/exchange {code, code_verifier}` → `consume_sso_code` → bearer JSON (generic `OnyxError(UNAUTHENTICATED)` on any failure). Register via `include_auth_router_with_prefix` in `backend/onyx/main.py:572-690` (gated on `AUTH_TYPE`). Add `MOBILE_SSO_CODE_TTL_SECONDS` + `MOBILE_ALLOWED_REDIRECT_URIS` to `backend/onyx/configs/app_configs.py`.

**Mobile**

5. **Runtime base URL + session store.** `getBaseUrl()` reads a runtime server URL from `appStorage` (MMKV) with `EXPO_PUBLIC_API_URL` dev fallback (`mobile/src/api/config.ts`); new `mobile/src/state/session.ts` (Zustand: `status`, `serverUrl`, persisted).
6. **Token + cache hardening.** `tokenStore.ts` — `keychainAccessible: WHEN_UNLOCKED_THIS_DEVICE_ONLY`; resolve the logout TODOs. `mobile/src/state/storage.ts` — `encryptionKey` for the query-cache MMKV (or PII-dehydrate exclusion).
7. **Email/password + config discovery + SessionManager.** `useAuthConfig.ts` (`GET /api/auth/type`), `useEmailLogin.ts` (`POST /api/auth/mobile/login`, form-encoded), `useLogout.ts`, `useSessionRefresh.ts` (single-flight), and `sessionManager.ts` (`login/logout/getValidToken`) + `providers.ts` registry (password + google).
8. **Browser SSO (Google) with Leg-2 PKCE.** `browserSso.ts` — generate PKCE pair (`expo-crypto`), open `…/auth/oauth/authorize?redirect=true&mobile_redirect_uri=onyx://auth/callback&app_state=…&app_code_challenge=…` via `expo-web-browser`, capture/validate the `onyx://auth/callback` deep link, return `{code, codeVerifier}`, exchange at `sso/exchange`. Add deps `expo-auth-session`, `expo-web-browser`, `expo-crypto`; confirm `app.json` scheme `onyx`.
9. **Auth gate + (auth) screens.** `components/auth/AuthGate.tsx` (redirect on `isAuthError`/no-token), wrap `<Stack>` in `_layout.tsx` + mount the deep-link listener; `(auth)/_layout.tsx`, `(auth)/connect.tsx` (server URL), `(auth)/login.tsx` (email/pw + provider buttons from the registry filtered by `/auth/type`).

## Tests

Primary type: **Playwright (E2E) is N/A for a native app**, so the split is:

- **External-dependency unit tests (backend)** — the main coverage. With Postgres/Redis live, call the new paths directly:
  - `issue_session_credential` + `store_sso_code`/`consume_sso_code`: single-use (second consume → `None`), TTL expiry, **PKCE pass/fail** (correct verifier succeeds; wrong verifier → `None`; missing challenge rejected).
  - `complete_mobile_sso`: redirect-allowlist enforcement; rejects absent `app_code_challenge`; 302 target shape.
  - `/auth/mobile/login`: returns Bearer JSON (not Set-Cookie); generic error on bad creds.
  - `/auth/mobile/sso/exchange`: valid code+verifier → token; expired/replayed/mismatch → generic 401.
  - Bearer auth end-to-end: a token from `write_token` authenticates `GET /me` via the mobile-bearer backend.
- **Integration test (backend)** — one happy-path: mobile email/password login → Bearer → authenticated `/me` → refresh → logout (token revoked, subsequent `/me` 401). Asserts the web cookie flow is untouched (regression guard on `complete_login_flow` web branch).
- **Mobile unit tests (Jest + RTL, mocked `apiFetch`/`expo-secure-store`/`expo-web-browser`)** — only the tricky pure logic: `SessionManager.getValidToken` single-flight (concurrent callers → one refresh), `browserSso` state-mismatch rejection + verifier-never-in-deep-link, logout cache purge, `AuthGate` redirect decisions. Avoid over-testing screen markup.
- **Manual smoke (documented, not automated):** the full Google system-browser flow on an EAS Dev Build against cloud + a self-hosted instance (deep-link return, PKCE exchange) — the one path that can't be unit-tested without device/browser.

## Plan Challenge Results

### 1. Extendability & Scalability: PASS
The `issue_session_credential` seam + provider registry + shared `complete_mobile_sso` helper make the two known futures (add SAML/OIDC/Apple; add token rotation) single-point extensions, not rewrites. Scale is the same O(1) Redis session lookup web already does; the one-time code is ephemeral 60s Redis state. No hardcoded limits that break at 10x.

### 2. Fragility: CONCERN (two brittle points, both mitigated — keep as implementation guardrails)
- **Editing the shared `complete_login_flow` (`users.py:2573`)** is the highest-blast-radius change: a regression there could break **web** Google login. Mitigation: the branch is guarded (`client=="mobile"`) and the integration regression test (web cookie flow untouched) must be treated as **mandatory, not optional**.
- **CSRF cookie depends on `sso/start` being browser-opened, not fetched.** If an implementer fetches the authorize URL as JSON then opens it, CSRF silently breaks. Documented in `03` "Important notes" — call it out in the PR description for the SSO phase.
- Note: V1 is *less* fragile than the deferred rotation design — with no refresh-token rotation, there's no reuse-detection false-positive/concurrent-refresh hazard yet; `getValidToken` single-flight is a nicety, not a correctness requirement.

### 3. Industry Standard: VERIFIED (web)
- **System browser + Authorization Code + PKCE, no secret in app** — RFC 8252 (BCP 212), confirmed current: "Public native app clients MUST implement PKCE… use an external user-agent (the system browser)." ([RFC 8252](https://www.rfc-editor.org/rfc/rfc8252.html), [oauth.com](https://www.oauth.com/oauth2-servers/oauth-native-apps/))
- **BFF / token-mediating backend with a one-time code over the deep link, swapped for the real token** — this is a documented, named industry pattern, matching our design almost verbatim: "the BFF returns a code (a unique reference UUID) via deep linking, and the app then makes another API call to the BFF to swap that code for the actual JWT." ([FusionAuth](https://fusionauth.io/blog/backend-for-frontend), [Auth0](https://auth0.com/blog/the-backend-for-frontend-pattern-bff/), [WorkOS](https://workos.com/docs/integrations/react-native-expo))
- **PKCE on the deep-link leg** aligns with RFC 9700's "PKCE required for all public clients, no exceptions." ([RFC 9700](https://datatracker.ietf.org/doc/rfc9700/))

### 4. Fact Check: PASS (one conscious divergence, flagged below)
- RFC 8252 / RFC 9700 / BFF-one-time-code claims: **verified** above. RFC 9700 confirmed published Jan 2025.
- Expo/Keychain claims (secure-store only, `THIS_DEVICE_ONLY`, Keychain survives uninstall, no bulk-clear) were sourced from official Expo + OWASP MASVS docs in `01-research.md`.
- **Divergence (honest):** RFC 9700 states refresh tokens for public clients **MUST** be sender-constrained **or** use refresh-token rotation. V1 reuses the existing long-lived (7-day sliding) server-side token as a Bearer with **no rotation** — a conscious deviation. It is *partially* mitigated (the token is server-revocable, unlike a stateless JWT; never in a URL; Keychain-only) and seamed for a clean later upgrade, but it is a real gap vs the current MUST. See Patch-vs-Fix.

### 5. Maintainability: PASS (one note)
Reuses existing fastapi-users machinery, OnyxError, the auth-router registration pattern, and TanStack hooks; new backend code is one isolated `mobile_sso/` package + a gateway router. The one non-obvious bit is the **second `AuthenticationBackend`** (multi-backend fastapi-users) — add a short code comment / doc pointer so a future reader doesn't miss why `/auth/mobile/*` exists separately from `/auth/*`.

### 6. Patch vs. Fix: PROPER FIX — with one conscious, already-accepted divergence to reaffirm
The root problem (no mobile auth) is solved properly: a clean gateway, real Bearer auth, server-side revocation, RFC-8252-compliant OAuth, PKCE on the interceptable leg. This is **not** a symptom-patch. The **single** standards gap is the deferred refresh-token rotation (RFC 9700 MUST) — chosen deliberately at GATE 1 (Approach C reuses the revocable token; rotation deferred behind `issue_session_credential`). Because it touches a security MUST, it is surfaced for explicit reaffirmation rather than decided silently.
