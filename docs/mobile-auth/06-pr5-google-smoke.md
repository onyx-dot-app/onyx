> Status: active · Task: mobile-auth · PR 5 — Google sign-in via system browser

# PR 5 — Google SSO: architecture, setup, and manual smoke

## How the mobile Google flow routes (and why it differs from web)

Mobile SSO uses a **dedicated** OAuth route on the backend so the IdP redirect comes
back to the **api_server**, never the web frontend:

- Web Google login: `{WEB_DOMAIN}/auth/oauth/callback` → nginx → **web server**
  (`web/.../auth/oauth/callback/route.ts`), which attaches the session cookie and
  redirects into the app.
- **Mobile** Google login: `{WEB_DOMAIN}/api/auth/mobile/oauth/callback` → nginx
  `/api` → **api_server** → `complete_mobile_sso` → `302 onyx://auth/callback?code=…`.

The `/api` prefix is what makes nginx route the mobile callback to the backend instead
of the web app, so **mobile SSO keeps working even if the web server is down**. The web
OAuth router is untouched; the mobile router is a second mount of the same Google client
(`backend/onyx/main.py`, prefix `/auth/mobile/oauth`, route names
`oauth:google.mobile-bearer.*`).

```
app ─► {server}/api/auth/mobile/oauth/authorize?redirect=true
            &mobile_redirect_uri=onyx://auth/callback&app_state=…&app_code_challenge=…
      ─► Google ─► {WEB_DOMAIN}/api/auth/mobile/oauth/callback   (→ api_server, NOT web)
            ─► complete_mobile_sso ─► 302 onyx://auth/callback?code=… ─► app
      ─► POST {server}/api/auth/mobile/sso/exchange {code, code_verifier} ─► bearer token
```

## Prerequisites (one-time)

1. **Register the mobile redirect URI on the Google OAuth client** (Cloud Console →
   Credentials → the OAuth 2.0 Client → Authorized redirect URIs):
   ```
   https://<your-domain>/api/auth/mobile/oauth/callback
   ```
   This is in addition to the existing web one (`…/auth/oauth/callback`). It's derived
   from `WEB_DOMAIN` (like the web/OIDC callbacks), so it tracks your deployment's domain.
2. `onyx://auth/callback` stays allow-listed (`MOBILE_ALLOWED_REDIRECT_URIS`, default ✓).
3. `onyx` scheme registered in `mobile/app.json` ✓ + a real **EAS dev build** (the
   system-browser auth API doesn't work in Expo Go).

## Why an EAS Dev Build (not Expo Go)

`expo-web-browser`'s auth session is native, and the custom `onyx` scheme only registers
after a native build:

```bash
cd mobile
eas build --profile development --platform ios   # or android
# install the dev build, then:
bun run start            # open the dev build, not Expo Go
```

## Steps (run against cloud + a self-hosted instance)

1. Launch signed out → **Connect** screen.
2. Enter the **public domain** (same origin as `WEB_DOMAIN` / the registered redirect
   URI), e.g. `https://cloud.onyx.app`. Keep the default `/api` prefix in prod (only
   local `:8080`-direct uses an empty `EXPO_PUBLIC_API_PREFIX`).
3. The login screen shows **Continue with Google** (only when `/auth/type` reports
   `oauth_enabled` + a Google `auth_type`).
4. Tap it → the **system browser** opens at
   `…/api/auth/mobile/oauth/authorize?…` (not an in-app webview).
5. Complete Google sign-in → the browser auto-dismisses and returns to the app.
6. The app lands authenticated (`/api/me` succeeds).
7. **Cancel path:** dismiss the browser before finishing → app stays on login, **no
   error chrome**.
8. **Logout** → sign back in to confirm the round-trip repeats.

## Verify in the backend log (`*_debug.log`)

- The authorize hit is `/auth/mobile/oauth/authorize` with `app_code_challenge` (S256)
  and `mobile_redirect_uri=onyx://auth/callback`; the verifier is **absent**.
- The callback `/auth/mobile/oauth/callback` 302s to `onyx://auth/callback?code=…&state=…`
  — `code` only, **no token** and **no Set-Cookie**.
- `POST /api/auth/mobile/sso/exchange {code, code_verifier}` → `{access_token, token_type}`;
  replaying the same `code` → generic 401.

## Local-dev gotcha

For local testing, point the app at the **`WEB_DOMAIN` origin** (e.g.
`http://localhost:3000`, `/api` prefix), NOT `:8080` directly — otherwise the authorize
CSRF cookie (set on one origin) is absent at the callback (a different origin). On a
device/emulator use the machine LAN IP / `10.0.2.2`, since `localhost` only resolves from
an iOS simulator.

## Implementation notes (drift from the original PR-5 plan)

- **Dedicated mobile OAuth callback**, not the reused web callback. The plan said "reuse
  the registered web callback," but in production that callback is served by the web app,
  whose wrapper drops the cookie-less mobile deep-link 302. The dedicated `/api`-routed
  callback bypasses web entirely (works if web is down) at the cost of registering one
  extra redirect URI.
- **No global deep-link listener.** `WebBrowser.openAuthSessionAsync(url, "onyx://auth/callback")`
  resolves with the redirect URL, so `browserSso.ts` captures + validates the callback
  inline. `_layout.tsx` untouched.
- **Deps added:** only `expo-web-browser` + `expo-crypto` (`expo-linking` already present;
  `expo-auth-session` not needed — the BFF builds the URL itself).
