> Status: active · Task: mobile-auth · Source plan: 04-implementation-plan.md

# Mobile Authentication — PR Roadmap

Five review-sized PRs, split by coherent vertical slice. Two independent tracks off a shared backend base: **email/password** (PR1→PR2→PR3, shippable after PR3) and **Google** (PR1→PR4→PR5). Backend edits are additive/guarded; mobile auth stays dormant until PR3 flips the gate. (Mobile is pre-release "Foundations," so no end-user feature flag is needed — dormancy = the gate simply isn't wired until PR3.)

## Overview

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 1 | `feat(auth): mobile bearer gateway for email/password` | ~300–400 | — | Native client can log in/refresh/logout via Bearer; web untouched |
| 2 | `feat(mobile): auth foundation — runtime server URL, secure session, SessionManager` | ~350–450 | PR 1 | Dormant client auth plumbing + hardened token/cache storage |
| 3 | `feat(mobile): email/password login + auth gate` | ~300–400 | PR 1, 2 | **Email/password sign-in works end-to-end (cloud + self-hosted)** |
| 4 | `feat(auth): mobile Google SSO bridge with PKCE` | ~300–400 | PR 1 | Backend one-time-code + PKCE deep-link bridge over existing OAuth callback |
| 5 | `feat(mobile): Google sign-in via system browser` | ~300–450 | PR 3, 4 | **Google sign-in works end-to-end** |

## Sequence

```
            ┌────────────────────────── PR 1 (backend bearer gateway) ──────────────────────────┐
            │                                                                                     │
   email/pw track:   PR 2 (mobile foundation) ──► PR 3 (email/pw login + gate)  ◄── ships email/pw
            │                                              │
   google track:     PR 4 (backend Google SSO bridge) ────┴──► PR 5 (mobile Google sign-in) ◄── ships Google
```

- **PR 1** unlocks everything. **PR 2 and PR 4 can be built in parallel** (both depend only on PR 1).
- **Email/password is fully shippable after PR 3** — Google can follow whenever.
- **PR 5** needs both the login screen (PR 3) and the backend bridge (PR 4).

---

## PR 1 — `feat(auth): mobile bearer gateway for email/password`
- **Goal:** Give a native client a way to obtain/refresh/revoke the existing session token as a Bearer, with zero change to the web cookie flow.
- **Scope (in):** `BearerTransport` + second `mobile-bearer` `AuthenticationBackend` (same `get_strategy`) added to the `fastapi_users` list; `issue_session_credential` seam (`tokens.py`, used by SSO later but introduced here); mobile gateway router mounting the bearer backend's `/auth/mobile/{login,refresh,logout}`; registration in `main.py`; minimal config.
- **Out of scope:** All OAuth/SSO (PR 4); the one-time code store (PR 4); any mobile code.
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `backend/onyx/auth/users.py` | modified | `bearer_transport`; `mobile_auth_backend`; append to `fastapi_users` list (`:1326`, `:1547-1560`, `:1684`) |
  | `backend/onyx/auth/mobile_sso/__init__.py` | new | package marker |
  | `backend/onyx/auth/mobile_sso/tokens.py` | new | `issue_session_credential(user, strategy)` seam |
  | `backend/onyx/server/auth/mobile.py` | new | mount bearer login/refresh/logout under `/auth/mobile` |
  | `backend/onyx/main.py` | modified | register gateway via `include_auth_router_with_prefix` (`:572-690`) |
  | `backend/tests/external_dependency_unit/auth/...` | new | bearer-login/refresh/logout + `/me`-via-Bearer + web-regression tests |
- **Est. size:** ~300–400 LOC incl. tests.
- **Depends on:** —
- **Feature-flag state:** N/A — additive, gated on existing `AUTH_TYPE`; harmless until a client calls it.
- **Tests on merge:** External-dependency unit — `/auth/mobile/login` returns Bearer JSON (not Set-Cookie); a minted token authenticates `GET /me`; `/refresh` extends; `/logout` revokes (subsequent `/me` 401). Integration happy-path + **web cookie-login regression guard** (mandatory).
- **Drift checkpoint:** Confirm `AUTH_BACKEND` target (redis/postgres vs jwt) and that the second-backend approach is acceptable vs a hand-rolled bearer endpoint. Re-confirm the multi-backend route-naming (`auth:mobile-bearer.*`) doesn't collide in the current fastapi-users version.

## PR 2 — `feat(mobile): auth foundation — runtime server URL, secure session, SessionManager`
- **Goal:** Land all client-side auth plumbing (no user-facing screens yet), so PR 3 is just UI + wiring.
- **Scope (in):** runtime base URL (`config.ts` reads `appStorage`, dev fallback to `EXPO_PUBLIC_API_URL`); `state/session.ts` (Zustand); `tokenStore.ts` hardening (`THIS_DEVICE_ONLY` + logout purge); `storage.ts` query-cache `encryptionKey` (or PII-dehydrate exclusion); `SessionManager` (`login/logout/getValidToken` single-flight); `useAuthConfig`/`useEmailLogin`/`useLogout`/`useSessionRefresh`; `providers.ts` (password row only); add no new deps.
- **Out of scope:** Screens, the auth gate wiring, Google/browser SSO (PR 3 / PR 5).
- **Files:** `mobile/src/api/config.ts` (mod), `mobile/src/state/session.ts` (new), `mobile/src/state/storage.ts` (mod), `mobile/src/api/auth/tokenStore.ts` (mod), `sessionManager.ts` / `providers.ts` / `useAuthConfig.ts` / `useEmailLogin.ts` / `useLogout.ts` / `useSessionRefresh.ts` (new), `mobile/src/api/query-keys.ts` (mod). Tests: `mobile/src/api/auth/__tests__/*` (getValidToken single-flight, logout purge).
- **Est. size:** ~350–450 LOC incl. tests.
- **Depends on:** PR 1 (endpoints exist to type against).
- **Feature-flag state:** Dormant — `_layout.tsx` not yet gated; app behaves as today.
- **Tests on merge:** Mobile unit (Jest + RTL, mocked `apiFetch`/`expo-secure-store`): single-flight refresh collapses concurrent callers; logout clears token + query cache + persister.
- **Drift checkpoint:** Confirm the runtime-URL UX (does Connect store one URL, or support switching instances?) and the query-cache encryption choice (`encryptionKey` vs PII exclusion) — both touch `01/03`'s security TODOs.

## PR 3 — `feat(mobile): email/password login + auth gate`
- **Goal:** Complete email/password sign-in end-to-end and turn auth on.
- **Scope (in):** `AuthGate` (redirect on `isAuthError`/no-token); wrap `<Stack>` in `_layout.tsx`; `(auth)/_layout.tsx`; `(auth)/connect.tsx` (cloud default / self-hosted URL, validated via `GET /auth/type`); `(auth)/login.tsx` (email/password with autofill + generic errors; provider buttons driven by the registry — only `password` visible until PR 5).
- **Out of scope:** Google button/flow (PR 5).
- **Files:** `mobile/src/components/auth/AuthGate.tsx` (new), `mobile/src/app/_layout.tsx` (mod), `mobile/src/app/(auth)/{_layout,connect,login}.tsx` (new). Tests: `AuthGate` redirect-decision unit tests.
- **Est. size:** ~300–400 LOC incl. tests.
- **Depends on:** PR 1 (login endpoint), PR 2 (foundation).
- **Feature-flag state:** Gate flips **on** here — auth now required on mobile.
- **Tests on merge:** Mobile unit (AuthGate routing: loading → splash, no-token → connect/login, authed → app). Manual: email/password login against a local backend (cloud + self-hosted base URLs).
- **Drift checkpoint:** Re-confirm login-screen scope (signup? forgot-password? email-verification UX — all exist server-side but may be out of V1 mobile scope). Confirm Connect-screen reachability check uses `GET /auth/type`.

## PR 4 — `feat(auth): mobile Google SSO bridge with PKCE`
- **Goal:** Backend host-agnostic SSO return: a PKCE-bound one-time code over the deep link, reusing the existing registered Google callback.
- **Scope (in):** `mobile_sso/code_store.py` (store/consume, atomic `GETDEL` + S256 verify); `mobile_sso/sso_completion.py` (`complete_mobile_sso` — require challenge, allowlist, mint via `issue_session_credential`, 302 to deep link); guarded `mobile_redirect_uri`/`app_state`/`app_code_challenge` params on `/auth/oauth/authorize` (`users.py:2251`); `client=="mobile"` branch in `complete_login_flow` (`users.py:2573`); `POST /auth/mobile/sso/exchange {code, code_verifier}` in the gateway router; `MOBILE_SSO_CODE_TTL_SECONDS` + `MOBILE_ALLOWED_REDIRECT_URIS` config.
- **Out of scope:** OIDC/SAML/Apple branches (later); any mobile code.
- **Files:** `backend/onyx/auth/mobile_sso/{code_store,sso_completion}.py` (new), `backend/onyx/auth/users.py` (mod — authorize params + callback branch), `backend/onyx/server/auth/mobile.py` (mod — add `/sso/exchange`), `backend/onyx/configs/app_configs.py` (mod). Tests: external-dependency unit.
- **Est. size:** ~300–400 LOC incl. tests.
- **Depends on:** PR 1 (gateway + `issue_session_credential`).
- **Feature-flag state:** N/A — additive; the web OAuth path is unchanged when the mobile params/marker are absent.
- **Tests on merge:** External-dependency unit — code store single-use + TTL + **PKCE pass/fail**; `complete_mobile_sso` allowlist + reject-missing-challenge + 302 shape; `/sso/exchange` valid vs expired/replayed/mismatch (generic 401). **Web OAuth regression guard** (callback web branch unchanged) — mandatory (highest blast radius).
- **Drift checkpoint:** Re-confirm the `MOBILE_ALLOWED_REDIRECT_URIS` default + that reusing the registered callback (vs a new path) still holds; verify tenant context on the SSO-exchange path for multi-tenant cloud.

## PR 5 — `feat(mobile): Google sign-in via system browser`
- **Goal:** Complete Google sign-in end-to-end via the system browser + PKCE deep-link exchange.
- **Scope (in):** `browserSso.ts` (PKCE pair via `expo-crypto`; open authorize in `expo-web-browser`; capture/validate `onyx://auth/callback`; return `{code, codeVerifier}`; exchange at `/sso/exchange`); deep-link listener in `_layout.tsx`; `providers.ts` google row; Google button in `(auth)/login.tsx`; add deps `expo-auth-session`, `expo-web-browser`, `expo-crypto`; confirm `app.json` scheme `onyx`.
- **Out of scope:** OIDC/SAML/Apple rows (later, cheap adds).
- **Files:** `mobile/src/api/auth/browserSso.ts` (new), `mobile/src/api/auth/providers.ts` (mod), `mobile/src/app/_layout.tsx` (mod — deep-link listener), `mobile/src/app/(auth)/login.tsx` (mod — Google button), `mobile/package.json` + `mobile/app.json` (mod). Tests: mobile unit + documented manual smoke.
- **Est. size:** ~300–450 LOC incl. tests.
- **Depends on:** PR 3 (login screen), PR 4 (backend bridge).
- **Feature-flag state:** N/A — Google button appears only when `/auth/type` reports it enabled.
- **Tests on merge:** Mobile unit — `browserSso` rejects state mismatch; `code_verifier` never placed in the deep link (only the TLS exchange). **Manual smoke (required):** full Google flow on an **EAS Dev Build** against cloud + a self-hosted instance (deep-link return + PKCE exchange). Document the dev-build setup.
- **Drift checkpoint:** Confirm EAS Dev Build is available in CI/dev; re-confirm the `onyx://auth/callback` scheme/path and that `sso/start` is **browser-opened, not fetched** (CSRF correctness). Decide whether Apple Sign In must land with this PR for App Store submission (Guideline 4.8) or is a separate follow-up.
