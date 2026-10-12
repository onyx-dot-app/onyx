# Craft Webapp Proxy

> Lets a user watch the web app their Craft session is building, live, inside
> Onyx. It proxies HTTP and one websocket into the sandbox's Next.js dev
> server, and it is the trust boundary between the sandbox and the viewer's
> browser.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** craft
**Edition:** CE (Craft ships in both editions; no EE-specific code in this path)
**Owns:**
`backend/onyx/server/features/build/webapp_proxy.py`,
`backend/onyx/server/features/build/sandbox/nextjs_dev.py`,
`web/src/app/craft/components/output-panel/`,
`web/src/app/craft/components/OutputPanel.tsx`

**Read first:** `docs/craft/lazy-webapp-provisioning.md`. It is the design
plan for on-demand dev-server startup and the tamper-hardened bootstrap
script this document's provisioning section maps to code.

---

## 1. What the user experiences

A user asks Craft to build a web app. The dev server starts when the agent first needs it.
Opening Apps from the plus menu lists registered session apps.
Background webapp discovery does not disable reload for a serving app. Browser reload follows the iframe document load, not discovery polling. The loading cover blocks interaction until the document load completes. Only user-requested reloads show the reload spinner.
Each tile opens its registered session app. A tooltip shows its URL.
The current backend supplies one app registration per session; the UI accepts a list without inventing additional servers.
A serving app fills its Browser tab through the authorized session proxy route.
Source edits use the existing dev server and HMR path. The managed Next.js scaffold disables the development React debug channel, keeping hydration data in the document instead of waiting for a WebSocket. Startup migrates the old managed empty-config declaration without replacing custom settings.

User actions open Browser tabs. During a task, a newly discovered app can also open after readiness succeeds.
The task selection lock prevents automatic selection after the user navigates or dismisses the panel. Passive inventory reads do not select resources.
When no tabs are open, a heading and three compact, stacked Outputs, All Files, and Apps tiles offer the plus menu actions.
Folders in Outputs show an unread marker while any descendant output has an unseen revision.
Mark all viewed acknowledges the currently loaded session-wide revisions, independent of the folder or type filter.
The action stays disabled while saving or when no loaded outputs are unread. Failed saves retain markers and show an error.
The Outputs page has no turn picker. Chat overflow links can scope it to one turn; All outputs clears that scope.
Each Browser tab keeps its own selected app and stable resource identity.
The panel retains app frames across tab switches, reorder, and medium/full/closed transitions.
A transient discovery failure preserves the accepted frame while showing an unavailable state.
A replacement URL reaches the frame only when that app reports readiness.
Switching sessions releases the previous session's frames.
Closing a tab or panel does not terminate its server.
Panel preferences persist independently of file caches; see [[craft-sessions]] §1.
Invalid preferences use defaults. Session deletion clears its preferences.

Only the session owner can discover apps, because `get_webapp_info` verifies ownership.
The proxy also admits any authenticated tenant user who
knows the proxy URL when the sharing scope is `PUBLIC_ORG`. A logged-in viewer
without access gets a 404, not a broken frame.
A logged-out viewer is redirected to `/auth/login`.

---

## 2. Surfaces

### HTTP and websocket endpoints (router prefix `/build`, `webapp_proxy.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/build/sessions/{session_id}/webapp` and `/build/sessions/{session_id}/webapp/{path:path}` | `get_webapp` | Proxies to the session's Next.js dev server. Public endpoint spec (exempt from the global auth middleware); auth is enforced inside the handler. |
| WS | `/build/sessions/{session_id}/webapp/_next/{hmr_endpoint}` | `websocket_webapp_hmr` | Proxies `hmr` and `webpack-hmr` through the same authenticated handler. |

`backend/onyx/server/features/build/session/api.py:get_webapp_info` (GET
`/build/sessions/{session_id}/webapp-info`) is a separate, authenticated
endpoint that reports `has_webapp`, `webapp_url`, and `ready`; the frontend
reads it to populate Browser home and select the authorized iframe URL
(`web/src/app/craft/components/OutputPanel.tsx`).

### Cache keys (`webapp_proxy.py`)

| Key | TTL | Meaning |
|---|---|---|
| `craft:webapp:url:{session_id}` | 60 s | Cached sandbox base URL, so a hot proxy path skips a DB round trip. |
| `craft:webapp:access:{session_id}:{user_id}` | 30 s | Cached "this user may view this session's webapp" grant. Only grants are cached; a 404 or 401 always re-checks. |

Both live in the configured `CacheBackend` (`get_cache_backend`: Redis, or
PostgreSQL when `CACHE_BACKEND=postgres`). They are shared by all API server
replicas, so the cache is consistent across them.

---

## 3. Data model

This component reads but does not own session state. `[[craft-sessions]]`
owns the `BuildSession` row this proxy resolves through
(`get_webapp_target_async`, `get_webapp_access_async` in
`onyx/server/features/build/db/build_session.py`): the session's
`sharing_scope`, owner id, sandbox id, and allocated `nextjs_port`.

`[[craft-sandboxes]]` owns the sandbox itself and the port allocation
(`SANDBOX_NEXTJS_PORT_START`/`_END`, `reserve_nextjs_port__no_commit`).

---

## 4. How it works

### 4.1 Resolving the target

`_get_sandbox_url` (`webapp_proxy.py`) resolves a session to a base URL:

1. Check the cache backend (`craft:webapp:url:{session_id}`).
2. On a miss, load `(sandbox_id, nextjs_port)` via
   `get_webapp_target_async`. Missing session, unallocated port, or missing
   sandbox each raise a distinct HTTP error (404, 503, 404).
3. Call `get_sandbox_manager().get_webapp_url(sandbox_id, nextjs_port)`.
   On Kubernetes this returns an in-cluster service URL,
   `http://{pod_name}.{namespace}.svc.cluster.local:{port}`
   (`kubernetes_sandbox_manager.py:_get_nextjs_url`, called from
   `get_webapp_url`). The URL is never reachable from outside the cluster
   except through this proxy.
4. Cache the resolved URL for 60 seconds.

### 4.2 Authorizing the viewer

`_check_webapp_access` (`webapp_proxy.py`) runs before every proxied request
and before the websocket is accepted:

1. If the viewer has a cached grant for this session, allow immediately.
2. Otherwise load `(sharing_scope, owner_id)` via `get_webapp_access_async`.
   Missing session: 404. No authenticated user: 401 on the HTTP path (the
   route handler turns that into a redirect to `/auth/login`, since a
   preview iframe or top-level navigation should not just render a bare
   401 page); the websocket path raises `WebSocketException(code=1008)`
   directly, since a websocket handshake has no redirect.
3. `SharingScope` has two values. `PRIVATE` (the column default) admits only
   the owner. `PUBLIC_ORG` (the "Organization" option in `ShareButton.tsx`)
   admits any authenticated user in the tenant, by design. The DB session and
   the cache are both tenant-scoped, so no grant crosses tenants.
4. A grant is cached for 30 seconds so a burst of asset requests for one
   page load does not re-hit the database per file. The cache key is per
   viewer, so `set_build_session_sharing_scope` does not evict it: a viewer
   who already loaded a `PUBLIC_ORG` preview keeps access for up to 30
   seconds after the owner sets it back to `PRIVATE`.

**The security answer:** a preview is reachable by the session owner,
or by any other authenticated tenant user while the sharing scope is not
`PRIVATE`. A cached grant can stay valid for up to 30 seconds after the scope
changes back to `PRIVATE`. There is no separate "preview link" credential. `PUBLIC_ORG`
grants access to the live app only. Transcript and session routes still
require session ownership (`db/build_session.py:get_build_session`). A
logged-in viewer without the right sharing scope gets a 404. An authenticated non-owner
cannot distinguish "session does not exist" from "session exists but is
private." An unauthenticated viewer can: a missing session returns 404, and
an existing session returns a redirect to `/auth/login`.

### 4.3 Proxying a request

`_proxy_request` builds the upstream path with `_webapp_next_path`, which
prefixes every request with the session's base path,
`webapp_base_path(session_id)` = `/api/build/sessions/{session_id}/webapp`
(`sandbox/nextjs_dev.py:webapp_base_path`). Next.js's dev server is started
configured with that same base path (`ONYX_WEBAPP_BASE_PATH`, see §4.5), so
responses pass through unmodified: no URL rewriting, no HTML injection to
patch relative links.

Request headers are filtered through `EXCLUDED_REQUEST_HEADERS`
(`webapp_proxy.py`) before forwarding: the viewer's Onyx cookie,
`Authorization`, CSRF tokens, and the explicitly listed client-identity
headers (`forwarded`, named `x-forwarded-*` headers, `x-real-ip`,
`cf-connecting-ip`, and the IDP user and email headers) are stripped. The
filter also drops every `x-onyx-*` and `sec-fetch-*` header by prefix. A
header that is in neither list reaches the sandbox. The sandbox runs LLM-generated code; it must never see the
viewer's Onyx credentials. Response headers are filtered through
`EXCLUDED_HEADERS`: hop-by-hop headers are dropped, and `set-cookie` is
stripped so app code running in the sandbox cannot set a cookie on the
parent Onyx domain.

On a proxy-level failure (502/503/504), the handler evicts the cached
sandbox URL (it may point at a dead or recreated pod) and returns a
friendly offline page (`templates/webapp_offline.html`) instead of a raw
gateway error.

### 4.4 Proxying the HMR websocket

The managed Next.js scaffold disables the development React debug channel, keeping hydration data in the document.
Startup migrates the old managed empty-config declaration without replacing custom settings.

`websocket_webapp_hmr` requires an authenticated user
(`current_user_from_websocket_cookie`, `onyx/auth/users.py`). That dependency
checks the websocket origin and reads the session cookie. On multi-tenant
deployments it resolves the tenant from the session token in Redis and sets
the tenant context before it loads the user. It also requires
`Permission.BASIC_ACCESS`. The handler then runs the same access check, then
`_proxy_webapp_hmr_websocket` opens a second websocket to the sandbox's
`/_next/hmr` or `/_next/webpack-hmr` endpoint requested by the client and pumps messages both directions
(`_pump_webapp_to_upstream`, `_pump_upstream_to_webapp`) until either side
closes.

### 4.5 Lazy provisioning

The dev server does not start at session setup. `session_workspace.py`
writes a self-contained, `chmod 444` script, `start-webapp.sh`, built by
`build_webapp_bootstrap_script` (`sandbox/nextjs_dev.py`). The agent (via
the opencode `webapp` tool) or a documented `bash start-webapp.sh` fallback
runs it the first time a web app is actually being built:

1. Scaffold `outputs/web` from the template if `outputs/web/package.json`
   is missing, then `bun install`.
2. `build_nextjs_start_script` writes the port to `.nextjs-port`, exports
   `ONYX_WEBAPP_PORT`, `ONYX_WEBAPP_BASE_PATH`, and
   `ONYX_WEBAPP_ALLOWED_DEV_ORIGINS` (`allowed_dev_origins`, derived from
   `WEB_DOMAIN`, satisfies Next 16's `allowedDevOrigins` cross-origin
   check), then starts `bun run dev` under `flock` so a concurrent replay
   cannot spawn a second server for the same session
   (`sandbox/nextjs_dev.py:build_nextjs_start_script`).
3. On snapshot restore, `build_webapp_restore_script` rewrites the script
   with the re-allocated port and auto-starts it only if the restored
   snapshot's `outputs/web/package.json` exists
   (`kubernetes_sandbox_manager.py` `restore_snapshot`).

Port allocation is per-user and per-session: `reserve_nextjs_port__no_commit`
(`db/build_session.py`) allocates one port from
`[SANDBOX_NEXTJS_PORT_START, SANDBOX_NEXTJS_PORT_END)` for
`SessionOrigin.INTERACTIVE` sessions only, persisted on
`build_session.nextjs_port`. Headless sessions (scheduled-task fires; see
`[[craft-scheduled-tasks]]`) get `nextjs_port=None` and skip webapp
provisioning entirely, since nothing will view them live.

---

### Output viewers and caches

`OutputPanel.tsx` owns resource tabs and passes inventory revisions to `FilePreviewContent.tsx`.
Outputs and All Files open the same file tabs. [[craft-streaming]] owns inventory refresh and automatic selection rules.
Tab paths use sandbox POSIX separators and preserve literal backslashes in filenames.
The panel retains Outputs, All Files, Apps, and five recently visited file viewers.
Hidden bodies remain mounted but invisible, inert, and hidden from assistive technology.
Stable body order preserves app frames through tab reorder and layout changes.
Closing or evicting a file tab releases its payload and local navigation state. Switching sessions releases retained viewers.
Callbacks from retired viewer instances cannot update their replacements.

`web/src/lib/build/hooks.ts:useFilePreview` owns one accepted payload per viewer.
Its request identity combines file path, inventory revision, and explicit reload counter.
Unchanged revisions reuse content across activation. Unversioned files revalidate on activation without hiding accepted content.
Hidden viewers defer new reads and retries. Superseded responses cannot replace current content.
Transient failures retain accepted content and show a warning. Authorization and not-found errors discard it, including stored fallback data.
Cache misses and explicit reloads bypass the browser cache.

PDF.js renders PDFs through React-PDF with text selection, links, page navigation, zoom, and fit controls.
PDF and PowerPoint share document navigation and pointer/keyboard-resizable thumbnail sidebars.
Hidden thumbnails do not start rendering. Unchanged PDF bytes retain the existing document; React-PDF releases replaced documents.
PowerPoint retains accepted slides during conversion. Successful conversion assigns fresh image tokens and clamps the selected slide.
Document keyboard navigation only handles events in the active viewer toolbar.
`web/tools/prepare-pdf-assets.cjs` copies versioned PDF.js support files before development and production builds, including Docker.
These assets use the same origin. Downloads remain in the address row.
Images use a neutral contrast background without changing downloaded bytes.
Unsupported or oversized previews offer Download beside the explanation.
Unknown files up to 10 MiB can preview as text when strict UTF-8 decoding finds no binary control characters.

### Workspace files

All Files uses shared SWR listings keyed by authenticated user, session, and directory.
One browser stays mounted for the selected workspace, even when its tab or panel closes.
Root and expanded-directory requests run independently, with ten-second deadlines and 30-second freshness.
Opening fresh folders reuses listings; stale activation refreshes while retaining rows.
Collapsing a folder, entering search, or leaving the workspace cancels obsolete reads.
Restoration pauses resource reads, then invalidates directories and previews when the filesystem is ready.
Saved expansion remains authoritative, including an explicitly collapsed tree.
Only successful current-generation listings can prune missing folders.
Loading, empty, failed, and incomplete results remain distinct. Each pending folder replaces its icon with a spinner.
Manual reload waits for pending visible directories. Successful uploads and deletes invalidate their original workspace after navigation.

`workspaceFiles.ts` searches names and session-relative paths through bounded directory batches.
A scan visits at most 128 directories and 10,000 entries, and starts no new batches after ten seconds.
Incomplete results preserve prior hits only beneath failed directories; successful reads remove deleted hits.
Fresh results take priority when retained hits would exceed the search inventory limit.
Clearing search returns to the retained tree. Expansion and scroll belong to session UI state; listings do not.
`WorkspaceUploadButton.tsx` owns the hidden picker and upload state.
Download actions support hover, keyboard focus, and touch without opening files or toggling folders.

### Outputs and persistent previews

Outputs shows immediate files and folders under `outputs/`, using compact folder cards and a responsive file-preview grid.
Breadcrumbs navigate folders. Search and extension filters include descendants; Folders shows immediate directories.
Folder browsing shows filenames, while recursive results show relative paths.
The shared inventory supplies files without a second scan on tab activation.
Cached cards remain visible during refresh, with separate incomplete and failed states.
`OutputTile.tsx` loads previews for visible eligible tiles and exposes Download.
Images and safe-rendered text use lightweight previews; PDF and PowerPoint use the shared first-page JPEG endpoint.
Unsupported, oversized, or failed thumbnails use file icons. Cached previews appear without a mount animation.

Browser session storage contains user-and-session-scoped display snapshots, not authoritative inventories or task baselines.
Live results replace these hints, including complete empty results. Preview requests wait for live revisions.
Terminal errors clear stored hints; transient failures retain them.
Oversized directory replacements discard that directory’s old hint. Failed storage writes discard the session’s directory hints.

| Snapshot owner | Limit | Expiration |
|---|---|---|
| `workspaceDirectorySnapshots.ts` | 32 directories; 256,000 characters per session | 24 hours |
| `outputInventorySnapshots.ts` | 2,000 files; 256,000 characters | 24 hours |
| `outputThumbnailCache.ts` | 64 user-scoped payloads; 2 Mi characters | 30 minutes |

The thumbnail cache is separate from full-file viewers and retains at most 128 entries and 16 Mi characters in memory.
Matching revisions reuse previews across tile mounts. Changed revisions and terminal errors invalidate saved payloads and late responses.
Partial scans invalidate changed revisions without deleting unseen entries.
Each Outputs collection owns its SWR provider lifecycle; shared retained payloads do not share subscription ownership.
Cache ownership and revision acceptance change after React commits, before pending callbacks may write.
Successful logout retires retained writes and clears Craft snapshots and preferences.

PowerPoint conversion and PDF thumbnails use the managed converter bundle described in [[craft-sandboxes]].
Installation does not replace agent-managed skills or enter session snapshots.

## 5. Contracts and invariants

1. **A preview must only be reachable by someone entitled to that session.**
   `_check_webapp_access` must run before every proxied HTTP request and
   before the HMR websocket is accepted. A new route added to this router
   without that check is a direct information leak into a user's sandbox.
2. **The sandbox must never receive the viewer's Onyx credentials.**
   `EXCLUDED_REQUEST_HEADERS` strips cookies, `Authorization`, CSRF tokens,
   and the listed identity headers before every forwarded request. A new header the
   sandbox should not see must be added there, not assumed absent.
3. **The proxy must not cache content-volatile dev assets.** Only
   `_next/static/media/*` is content-hashed and safe to cache immutably;
   everything else, including JS chunks and CSS, is stable-URL-but-mutable
   in dev and must pass through uncached (`_proxy_request`, §9).
4. **`set-cookie` from the sandbox must never reach the viewer's browser
   under the Onyx origin.** Stripped unconditionally in `EXCLUDED_HEADERS`.
5. **The base path must match on both ends.** `webapp_base_path(session_id)`
   is used by the proxy's upstream path construction, the start script's
   `ONYX_WEBAPP_BASE_PATH`, and the template `next.config.ts`. A change to
   one without the others breaks every asset URL Next.js emits.

---

## 6. Relationships

**Depends on**
- [[craft-sessions]]: session ownership, sharing scope, and the
  `nextjs_port` field this proxy resolves through.
- [[craft-sandboxes]]: the sandbox manager that turns a `(sandbox_id, port)`
  pair into a reachable URL, and that runs the bootstrap/restore scripts.
- [[auth-and-identity]]: `optional_user`, `current_user_from_websocket_cookie`.
- [[multi-tenancy]]: sessions and sandboxes are tenant-scoped. The HTTP path
  gets its tenant from the request middleware. The websocket path has no
  such middleware, so `current_user_from_websocket_cookie` sets the tenant
  context itself from the session token.

**Depended on by**
- [[craft-external-apps]]: unrelated egress path, but shares the theme of
  "the sandbox is untrusted and must be firewalled from Onyx credentials."
- [[craft-scheduled-tasks]]: scheduled (headless) sessions deliberately skip
  this component; `nextjs_port` stays `None` for them.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new proxied path or method | `EXCLUDED_REQUEST_HEADERS`/`EXCLUDED_HEADERS` still apply; `_check_webapp_access` still runs first |
| changes what is cached or its TTL | the cache-eviction-on-502/503/504 path in `get_webapp`, and whether a stale grant could outlive a sharing-scope change |
| changes `webapp_base_path` | `nextjs_dev.py`'s start script, the template `next.config.ts`, and every place `_webapp_next_path` builds an upstream path |
| changes port allocation | `[[craft-sandboxes]]`, and whether headless (scheduled) sessions still correctly skip provisioning |
| touches the HMR websocket proxy | verify live updates through both supported endpoints; check initial interactivity separately with the managed debug channel disabled (§9) |
| changes response header filtering | re-check `set-cookie` stripping and cache-control handling together; a change to one filter can undo the other's intent |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/unit/onyx/server/features/craft/test_webapp_proxy_header_stripping.py
cd backend && uv run pytest tests/unit/onyx/server/features/craft/session/test_webapp_info.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_webapp_hmr_websocket_auth.py
cd backend && uv run pytest tests/integration/tests/craft/test_webapp_proxy.py
cd backend && uv run pytest tests/integration/tests/craft/k8s/test_webapp_preview.py
cd backend && uv run pytest tests/integration/tests/craft/docker_e2e/test_webapp_preview_docker.py
```

Use manual reproduction for the cache and hot-reload behaviour below.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. In a Craft session, ask the agent to scaffold a simple Next.js page.
3. Open Browser and select the session app. Confirm the app renders and its controls respond.
   If `experimental.reactDebugChannel` is false, block the HMR WebSocket and reload; controls should still respond.
   Unblock the WebSocket. Ask the agent to change visible text and confirm hot reload without a manual refresh.
   If edits do not appear, check `/_next/hmr` or `/_next/webpack-hmr` for a failed WebSocket upgrade.
4. Open the same session URL as a second, unrelated user account (or in an
   incognito window with no session). Confirm the second user gets a 404
   and the logged-out window is redirected to `/auth/login`, not rendered.
5. Edit a file that changes a CSS class or a JS chunk's content, then
   reload the preview without restarting the dev server. Confirm the new
   styling/behavior shows immediately, not a stale cached version.

Drive the browser with `claude-in-chrome` against the user's real Chrome.

### What "working" looks like

- An unauthorized logged-in viewer gets a 404 and a logged-out viewer gets a
  redirect to `/auth/login`. Neither sees a rendered frame.
- Hot reload works after a file edit without a manual page reload.
- With the managed debug channel disabled, initial controls work even when the HMR WebSocket is unavailable.
- No stale JS/CSS after an edit, confirmed by a hard content check, not
  just "the page still looks fine."

---

## 9. Footguns

- **Initial hydration and hot reload have different requirements.** The managed
  scaffold disables `experimental.reactDebugChannel`. Initial interactivity should
  not require the HMR WebSocket, but live source updates still require it.
  Older or custom configurations that enable the debug channel can still delay
  hydration when that connection fails. Check the effective configuration before diagnosing unresponsive controls.
- **Next.js HMR paths vary by version.** Newer sandbox apps use `/_next/hmr`;
  older apps use `/_next/webpack-hmr`. Frontend rewrites and backend WebSocket
  routes must preserve the endpoint so source edits update the running app.
- **Only `_next/static/media/*` is safe to cache immutably.** `_proxy_request`
  checks `rel_path.startswith("_next/static/media/")` before setting
  `cache-control: public, max-age=31536000, immutable`; every other path,
  including dev JS chunks and CSS, is passed through with whatever
  cache-control Next.js's dev server itself sets. Dev chunk and CSS URLs
  are stable in shape but their content changes as the agent edits files,
  so caching them would serve stale code after an edit that looks
  unrelated to caching at all.
- **The upstream base URL is an internal cluster address, not a public
  one.** `get_webapp_url` on Kubernetes returns a
  `*.svc.cluster.local` URL. This proxy is the only path a browser can use
  to reach it; there is no direct-to-pod fallback for a viewer.
- **PowerPoint replacements can preserve modification time.** The converter reuses cached slides only when the stored source revision matches device, inode, size, modification time, and change time. Missing or malformed revision records require regeneration. This detects same-size replacements without hashing file contents.
