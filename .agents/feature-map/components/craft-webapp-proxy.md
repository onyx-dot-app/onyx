# Craft Webapp Proxy

> Lets a user see, inside Onyx, the web app that their Craft session builds and
> the static HTML files it writes; it is the trust boundary between code that an
> LLM wrote and the viewer's browser.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

A user asks Craft to build a web app. The agent starts the dev server the first
time it needs it. The app opens in a Browser tab of the output panel and
updates when the agent edits its source. The user can share the session with
the organization. Then any signed-in user in the same tenant who has the
preview URL can open the live app, but not the transcript.

A static `.html` file under `outputs/` also opens as a live page. Its relative
CSS, images, scripts and JSON load. Root-relative URLs (`/style.css`) do not
load, because the preview does not rewrite them. Forms, pop-ups and top-level
navigation do not work.

When it fails:
- a dev server that is down or not reachable shows an "offline" page, not a raw
  gateway error;
- a signed-in viewer without access gets a 404;
- a signed-out viewer goes to the login page;
- a crashed dev server stays down until the agent starts it again, usually
  after it reads `nextjs.log` and fixes the code.

---

## Scope

This component owns the HTTP and hot-reload (HMR) websocket proxy into the
sandbox's Next.js dev server, the preview access check, static HTML preview
capabilities, the dev-server base path, and the scripts that start the dev
server and start it again after a restore.

Neighbours own the rest:
- [[craft-sessions]]: the `BuildSession` row, its `sharing_scope` and its
  `nextjs_port`, and `get_webapp_info`, which the panel polls for readiness.
- [[craft-sandboxes]]: the pod, the port range, the session workspace, and
  how a `(sandbox, port)` pair becomes a URL (`get_webapp_url`).
- [[craft-frontend]]: the output panel, Browser tabs, and file viewers.
- [[auth-and-identity]]: the optional cookie user and the websocket cookie
  user.

---

## Architecture

```
browser iframe  GET /api/build/sessions/{id}/webapp/{path}
  webapp_proxy.py:get_webapp                 public route, auth inside the handler
    _check_webapp_access                     cached grant, else DB scope check
    _proxy_request                           GET only, headers filtered
      _get_sandbox_url                       cached URL, else get_webapp_target_async
        SandboxManager.get_webapp_url        in-cluster address of the pod
  WS /api/build/sessions/{id}/webapp/_next/{hmr|webpack-hmr}
    websocket_webapp_hmr                     cookie user, same access check
```

**One base path on both ends.**
`server/features/build/sandbox/nextjs_dev.py:webapp_base_path` is
`/api/build/sessions/{id}/webapp`. The dev server runs with that base path, so
the proxy passes responses through with no URL rewriting or script injection.

**Lazy dev server.** Session setup writes `start-webapp.sh` (read-only) from
`build_webapp_bootstrap_script`. The agent runs it when it builds an app,
usually through the `webapp` tool
(`server/features/build/sandbox/image/opencode-plugins/webapp.ts`), which can
also report status, show logs and restart the server. The script copies the
template if the app has no `package.json`, installs dependencies, and
starts `bun run dev` on the session's port under `flock`, so two runs cannot
start two servers. On snapshot restore, `build_webapp_restore_script` writes
the script again with the new port and starts the server in the background
only if the app exists.

**Port lifecycle.** Each session that can show a preview holds a port, unique
per user (`server/features/build/db/build_session.py:reserve_nextjs_port__no_commit`).
Sleep clears all of a user's ports (`clear_nextjs_ports_for_user`).
`server/features/build/session/session_ready.py:ensure_session_ready` reserves
a port for any session that has none when it rebuilds the session workspace,
whatever the session's origin. Session creation skips the port for
non-interactive origins (`SessionManager.create_session`) and for `headless`
requests. Such a session gets a port only when a later rebuild reserves one.
Until then its preview shows the offline page, because `_get_sandbox_url`
returns 503 for a session with no port.

**Static previews.** `server/features/build/static_preview.py:create_static_preview`
checks session ownership, reads the output inventory, and stores a grant in
the shared cache for one hour. The grant names the tenant, the owner, the
session, the folder, and each allowed file with its size and revision.
`read_static_preview` needs no cookie. It loads the grant by token, sets the
tenant from it, checks that the owner is still active and has Craft, and
serves only listed files at the granted revision. Asset bytes are cached by
tenant, session, path and revision.

---

## Contracts and traps

1. `preview-access-model` **The preview access model.** The owner can always
   open the preview. While `sharing_scope` is `PUBLIC_ORG`, any authenticated
   user in the tenant can too
   (`server/features/build/webapp_proxy.py:_check_webapp_access`). There is no
   separate preview-link credential. The transcript and session routes still
   require ownership. Three consequences:
   - a grant is cached per viewer for 30 seconds, so a viewer keeps access for
     up to 30 seconds after the owner sets the scope back to `PRIVATE`;
   - a signed-in viewer without access gets 404, so they cannot tell a missing
     session from a private one;
   - a signed-out viewer can tell: a missing session gives 404, and an existing
     one redirects to `/auth/login`.
2. `public-router-checks-access` **Every route on `public_build_router` must
   call `_check_webapp_access` first.** The webapp GET paths are in
   `backend/onyx/server/auth_check.py:PUBLIC_ENDPOINT_SPECS`, so the startup check
   (`check_router_auth`) accepts them with only `optional_user`, and the
   handler can redirect signed-out browsers. No middleware checks auth on these
   paths: the handler is the only check. A new handler without
   `_check_webapp_access` exposes the sandbox. A new HTTP path that uses
   `optional_user` must also go into that list, or the API server fails at
   startup. The static preview read route is also in the list, but it is on
   its own router and its token is the credential
   ([[#static-preview-bearer-token]]).
3. `strip-viewer-credentials` **The sandbox must never see the viewer's
   credentials.**
   `server/features/build/webapp_proxy.py:EXCLUDED_REQUEST_HEADERS` strips cookies, `Authorization`,
   CSRF tokens, `Origin` and client-identity headers, and the filter drops
   every `x-onyx-*` and `sec-fetch-*` header. A header that is in neither list
   reaches the sandbox. Add new sensitive headers there.
4. `strip-set-cookie` **`set-cookie` from the sandbox never reaches the
   browser.** `server/features/build/webapp_proxy.py:EXCLUDED_HEADERS` strips it, so app code cannot set a cookie on
   the Onyx domain. Check this filter and the cache-control rule together.
5. `immutable-only-static-media` **Only paths under `/_next/static/media/` are
   cached as immutable.** Those files have content hashes. Dev JS chunks and
   CSS keep the same URL while the agent edits them. Caching them would serve
   stale code after an edit (`server/features/build/webapp_proxy.py:_proxy_request`).
6. `base-path-three-places` **The base path must match in three places:**
   `server/features/build/sandbox/nextjs_dev.py:webapp_base_path`, the start
   script's `ONYX_WEBAPP_BASE_PATH`
   (`server/features/build/sandbox/nextjs_dev.py:build_nextjs_start_script`), and the
   template's
   `server/features/build/sandbox/image/templates/outputs/web/next.config.ts`.
   A change to one breaks every asset URL.
7. `managed-port-routing` **The managed port is the routing contract.** The
   start script
   (`server/features/build/sandbox/nextjs_dev.py:build_nextjs_start_script`) never moves the server to another port, and nothing restarts a
   crashed server automatically. Only the agent restarts it, through the
   `webapp` tool or the script. The proxy cannot reach a server on any other
   port. The start script writes the port to `.nextjs-port`, so a hand-run
   `bun run dev` with the template's `dev` script still binds it.
8. `static-preview-bearer-token` **A static preview token is a bearer
   credential.**
   `server/features/build/static_preview.py:read_static_preview` serves it.
   Anyone with the URL can read the listed files until the grant
   expires. Each read still checks that the owner is active, has Craft, and
   owns the session. The response CSP allows scripts but no same-origin
   access, and limits `fetch` to the capability's own URLs.
9. `start-script-protection` **`start-webapp.sh` is protected only by its mode
   and the agent config.** It is `chmod 444`, so a rewrite must unlink it
   first. `server/features/build/sandbox/util/opencode_config.py` denies agent
   edits to it and allows only `bash start-webapp.sh`.
10. `url-cache-cleared-on-gateway-error` **The upstream URL cache is cleared
    only on a gateway error.**
    `server/features/build/webapp_proxy.py:_get_sandbox_url` caches the pod URL for
    `_SANDBOX_URL_TTL` seconds. Sleep and wake can move the session to a new
    port or pod, so the cached URL can name a dead target.
    `server/features/build/webapp_proxy.py:get_webapp` deletes
    the cache key when `_proxy_request` raises 502, 503 or 504, then serves the
    offline page, so the next request resolves again. The HMR websocket handler
    does not clear the key. A new proxied route or a change to this error
    handling must keep the delete, or the preview stays offline until the
    entry expires.
11. `hmr-paths-both` **The HMR websocket accepts both Next.js paths,
    `/_next/hmr` and `/_next/webpack-hmr`.** The path differs by Next.js
    version. `server/features/build/webapp_proxy.py:websocket_webapp_hmr` and
    the rewrite in `web/next.config.js` must accept the same set.

---

## Known issues

- **The HTTP proxy forwards GET only.** A generated app that posts a form or
  calls a non-GET API route in the preview fails.
- **Initial render and hot reload need different things.** The managed
  scaffold sets `experimental.reactDebugChannel` to false, so first render
  does not need the HMR websocket. Live updates still do. An app with a custom
  config that turns the channel on can hang on hydration when the websocket
  fails.

---

## Dependencies

- [[craft-sessions]]: session ownership, `sharing_scope`, `nextjs_port`, and
  readiness through `get_webapp_info`.
- [[craft-sandboxes]]: the pod address, the port range, and the setup and
  restore code that runs the scripts.
- [[auth-and-identity]]: `optional_user` and
  `current_user_from_websocket_cookie`. The websocket has no tenant
  middleware, so that dependency sets the tenant from the session token.

---

## Recipes

- `new-preview-route` **A new route on the preview router.** Copy `get_webapp` in
  `server/features/build/webapp_proxy.py`. List the routes with
  `git grep -n '@public_build_router' backend/onyx/server/features/build/`.
  Add the path to `backend/onyx/server/auth_check.py:PUBLIC_ENDPOINT_SPECS`. Call
  `_check_webapp_access` first ([[#public-router-checks-access]]), turn a 401
  into the login redirect, and keep the URL cache delete on gateway errors
  ([[#url-cache-cleared-on-gateway-error]]).
- `new-static-preview-type` **A new file type for static preview.** Add the extension to
  `server/features/build/static_preview.py:STATIC_EXTENSIONS`, next to `.css`.
  Keep the grant's file list and revision check, and keep the CSP
  ([[#static-preview-bearer-token]]).
- `investigate-preview-offline` **Investigate a preview that stays offline.** Read
  `GET http://localhost:3000/api/build/sessions/<id>/webapp-info` as the
  owner. `has_webapp` null means the sandbox is not `RUNNING`. `has_webapp`
  false means the agent has not built an app. `has_webapp`
  true with a null `webapp_url` means no port is reserved: a non-interactive
  or headless session waits for a rebuild. `ready` false with a URL means the
  dev server is down: read `nextjs.log` in the session workspace. If the
  server is ready but the preview is offline, look for a stale URL cache entry after sleep and wake
  ([[#url-cache-cleared-on-gateway-error]]).

---

## Verification

- Unit: `backend/tests/unit/onyx/server/features/craft/` (header stripping,
  static preview, the dev-server scripts).
- External dependency: `backend/tests/external_dependency_unit/craft/` (HMR
  websocket auth).
- Integration: `backend/tests/integration/tests/craft/`, including the
  `k8s/` preview suite.
- By hand: open the preview as a second user and as a signed-out window. The
  first must get 404 and the second the login page. Ask the agent to change a
  CSS class, and confirm that the page shows the change without a dev server
  restart.
