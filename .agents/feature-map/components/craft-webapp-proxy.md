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
Opening Apps from the plus menu shows compact, stacked local-app tiles with the same shared home layout as the empty panel.
The local app tile reads "Preview Your App". The home heading reads "Apps".
The Apps home URL bar reads "Webapps on your sandbox".
Background webapp discovery does not disable reload for a serving app. Browser reload follows the iframe document load, not discovery polling. The loading cover blocks interaction until the document load completes. Only user-requested reloads show the reload spinner.
Each tile opens its registered session app. A tooltip shows its URL.
The current backend supplies one app registration per session; the UI accepts a list without inventing additional servers.
A serving app fills its Browser tab through the authorized session proxy route.
Source edits use the existing dev server and HMR path.

Browser tabs open only through user actions. Passive discoveries cannot reopen a closed panel or change its selection.
When no tabs are open, a heading and three compact, stacked Outputs, All Files, and Apps tiles offer the plus menu actions.
Each Browser tab keeps its own selected app and stable resource identity.
The panel retains app frames across tab switches, reorder, and medium/full/closed transitions.
A transient discovery failure preserves the accepted frame while showing an unavailable state.
A replacement URL reaches the frame only when that app reports readiness.
Switching sessions releases the previous session's frames.
Closing a tab or panel does not terminate its server.
Closing the active tab selects the most recently viewed tab that remains open.
Closing an inactive tab does not change selection. Drag order does not change viewing history.
History contains each open, viewed tab once. Older preferences without history use the adjacent tab as a fallback.
Panel mode, ordered tabs, selected tab, viewing history, and split width survive hard reloads in the same browser tab.
These preferences use session-scoped browser session storage. They exclude transcripts, file contents, and runtime state.
Invalid saved preferences fall back to defaults. Deleting a session clears its saved preferences. Successful logout clears all saved panel preferences.

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

### Artifact preview refresh

`OutputPanel.tsx` reads each file's revision from the session inventory and passes
it through `FilePreviewContent.tsx` to the selected viewer. File activation in Files opens the same resource tab.
These production callers make revision-based cache reuse active; explicit reload counters change independently of file revisions.
Idle session entry and focus reconcile metadata without selecting files.
The store validates output inventory after idle filesystem writes; streaming owns discovery during tasks.
The Outputs view requests validation when activated or when a task ends, without mirroring inventory state.

Output subscriptions select only runtime and inventory fields, excluding conversation and panel layout changes.
Retained file viewers skip unrelated tab updates. Markdown and CSV content skip visibility-only renders.
Each retained file viewer owns a private SWR cache with one current payload.
`web/src/lib/build/hooks.ts:useFilePreview` owns payload replacement through one request identity: file key, revision, and reload counter.
Activation validates that identity against the accepted cached result.
File revisions and explicit reloads replace that payload. A retained viewer with an unchanged
revision reuses its data and DOM across tab switches. Files without revisions
revalidate on activation while keeping their current content visible. Closing or evicting a viewer
releases its cache; reopening fetches fresh bytes. SWR retries failed requests and
rejects superseded responses. Transient failures retain accepted content.
Viewers show errors only for the current request identity. Cache misses and reloads bypass the
browser cache when fetching artifacts. Unversioned PDF activation reads compare bytes
with the displayed PDF. Identical bytes reuse its Blob and PDF.js document.
Changed bytes replace the displayed PDF. React-PDF owns PDF.js loading tasks and releases them with the viewer.
Fit modes use the measured content area, which already excludes viewport padding.

The output panel retains Outputs, All Files, and Browser bodies, plus five recently visited file viewers, including PDFs.
PDF viewers stay mounted to preserve page, zoom, and thumbnail state.
Rendered thumbnail canvases remain mounted while inactive; hidden thumbnails do not start rendering.
Inactive bodies keep their layout but stay invisible, inert, and hidden from assistive technology.
Stable DOM order prevents app iframe reloads when tabs switch or reorder.
Closing the panel keeps retained bodies. Closing a file tab, changing sessions, or evicting a viewer releases its payload cache.
Directory listings remain in shared SWR independently of tab mounts.
Terminal access and not-found errors replace accepted listings with cached failure results, preventing stored snapshots from returning.
Closing a tab also clears its local refresh, export, slide, and scroll state.
Hidden file viewers retain their accepted revision and payload.
Hidden viewers defer new reads and retries; reopening retries missing or failed previews even with a known revision.
Terminal access and not-found responses replace retained bytes with cached failure results. Later transient failures cannot restore them.
Presentation viewers retain accepted slides and sidebar state during background conversion.
Transient failures show a warning; conversion and error screens appear only without accepted slides.
Failure warnings reserve space above retained content.
Activation loads the latest revision once; intermediate hidden edits do not trigger conversions.
Webapp iframes stay mounted across panel size transitions.
A frame beneath an unavailable-app overlay is inert and hidden from assistive technology.

Files owns workspace state. Directory and search listings use the shared SWR cache keyed by session and path.
Fresh listings survive session switches and Files tab closure; stale listings refresh with previous rows visible.
`web/src/app/craft/services/workspaceDirectorySnapshots.ts` saves directory metadata in user-and-session-scoped browser session storage.
Snapshots expire after 24 hours and are bounded to 32 directories and 256,000 characters per session.
Hard reload uses validated snapshots as stale SWR fallback data, then reconciles with the server.
Authorization and missing-session errors clear these snapshots. File contents and runtime state are not stored.
A stable logical workspace identity preserves panel search and viewer state through welcome provisioning and claim.
Backend requests and data caches retain the actual session identity.
`DirectoryTree.tsx` renders folders and manages each expanded directory's cancellable request. Requests have a ten-second deadline;
a stalled directory cannot block another directory. Successful directory and search reads stay fresh for 30 seconds.
Quick reopen and folder expansion reuse fresh listings. Stale activation refreshes in the background.
Directory and file-preview reads pause while the sandbox restores. Restore completion invalidates directory listings and file previews.
Only active, successful current-generation listings can reconcile expansion or consume initial folder expansion.
Missing or invalidated directory data is pending before its fetch effect starts.
Manual reload and file-change signals bypass freshness while retaining existing rows.
Collapsing a directory, entering search, or leaving its workspace aborts its request. Tab and panel closure keep directory reads running. Cancellations stay silent.
Loading replaces the folder icon with a spinner; file rows appear as soon as they arrive.
Failed folder reads show an error icon and message. Failed refreshes of cached empty directories also show the error.
Complete empty folders display a concise empty state.
Root loading and failed reads have separate messages; failures can retain the last successful rows.
The Files reload control shows pending directory work and remains disabled until visible reads finish.
`web/src/app/craft/services/workspaceFiles.ts` loads the workspace search inventory in bounded directory batches.
The Files address row provides workspace search. Search matches names and session-relative paths case-insensitively.
It reads accessible directory listings with bounded work and reports partial or failed discovery separately.
Partial refreshes preserve previous hits only beneath failed directories; successful reads remove deleted hits.
Clearing search returns to the retained tree. File activation opens a resource tab.
Folder expansion and saved scroll stay in session UI state; directory responses do not.
The Files toolbar places Upload beside workspace search, matching the file Download action.
`WorkspaceUploadButton.tsx` owns the hidden picker and upload state; Files owns directory and search state.
Rows reveal Download with the shared hover fade; keyboard focus and touch also expose it.
Folder chevrons follow Download. Download does not toggle the folder or open a file.
The Files tree has no attach-to-chat action. Names use regular-weight secondary text. Empty-directory messages align with the file-row icons at their depth.
A batch upload refreshes listings after any successful upload, even if a later file fails.
Completed uploads and deletes invalidate their original session even after navigation changes the composer.
Scroll saves on hiding or unmounting, without store writes for each scroll event.
Outputs is the default resource tab when users first open the panel. Its equal compact cards show only files under `outputs/`, including nested files. The grid uses two columns in narrow panels and three in wider panels, with cards filling the available width up to a 768-pixel content area. Previews grow with the cards; fallback icons grow on wide panels. Folders use compact outlined cards above the file-preview grid. Folder browsing shows filenames; recursive search and type filters show relative paths. Home views align near the top. Full-panel unsupported previews use the same home layout, title styling, and centered download action. All Files browses the full sandbox. Both views open the same file resource tabs.
`OutputsTab.tsx` uses the shared output inventory and home layout.
The root user context supplies the cache owner outside private SWR scopes.
Cache ownership changes after React commits; render and hydration do not write shared state.
In-flight preview validation coalesces repeated activation for the same request identity.
Retries require the current committed identity and an active viewer.
Each directory owns its folder row and loading status. A hook tracks pending directory paths and exposes aggregate loading to Files.
Directory, search, and webapp cache keys include the authenticated user ID.
Partial search responses merge accepted cached entries at the fetch boundary.
 It restores user-and-session-scoped metadata snapshots as display hints while sandbox discovery and inventory validation run. Snapshots expire after 24 hours and hold at most 2000 files or 256000 characters. Cached hints never enter the store or establish task baselines. Complete inventories replace snapshots; transient failures retain hints, while terminal errors clear them. A live result always replaces the hint, including an empty inventory. Preview fetching waits for live inventory revisions. `OutputTile.tsx` owns lightweight image and text previews plus hover downloads. Visible eligible tiles fetch previews; large files and unsupported formats use file icons. PDF and PowerPoint cards use the shared first-page thumbnail endpoint. Markdown uses the same safe renderer as file previews, scaled into a clipped paper thumbnail. Image backdrops improve transparent-image contrast. Pending thumbnails keep a quiet placeholder; cached images display without a mount animation. Failed previews fall back to file icons. PDF and PowerPoint use shared navigation controls and thumbnail sidebars.
PDF callbacks reject results from retired document sources. Image load state belongs to its source; contrast selection remains independent.
PDF.js renders PDFs through React-PDF with selectable text, links, page arrows, a page count, zoom presets, and fit-width/fit-page controls.
Thumbnail rendering is limited to nearby visible pages. Both sidebars support pointer and keyboard resizing, bounded to preserve document space.
`web/tools/prepare-pdf-assets.cjs` copies versioned PDF.js assets before dev and production builds, including Docker builds.
PDF assets are served from the same origin. Downloads remain in the URL bar. Width stays while the viewer remains mounted. Full image previews default to a neutral contrast backdrop; a toggle restores the normal panel background. Downloads preserve the original image. Thumbnails share a session-and-path SWR cache separate from full-file viewers. The cache retains at most 128 entries and 16 Mi characters of preview content, evicting the oldest updated entries. Matching revisions reuse cached payloads across tile remounts; changed revisions refresh them. Browser reload restores up to 64 user-scoped thumbnail payloads within 2 Mi characters and a 30-minute age limit. Metadata-only SWR updates do not write storage. Terminal errors and accepted inventory changes invalidate saved previews, including late responses. Partial scans invalidate changed revisions without deleting unseen files. The address row searches output names and paths. Breadcrumbs show output folders; extension filters and search match descendants of the current folder. The filter offers All, Folders, and the extensions present in that folder tree. Folders shows immediate directories. The default view shows immediate files and folders. It keeps cached cards visible during refresh and shows partial or failed reads separately. Session loading and manual reloads never open file tabs automatically. Opening Outputs reuses the session inventory.
During a task, newly created previewable outputs open file tabs. The first output is selected once per task, unless the user has changed the selection. A complete baseline prevents existing files from opening as new outputs.

PowerPoint previews use LibreOffice and PDF rasterization to produce slide images.
Docker and Kubernetes deploy the converter and office helper as normal files in a content-versioned managed directory.
They reuse a complete bundle and verify deployment before running its `preview.py` entry point.
Deployment uses `push_to_sandbox` and its shared retry and result handling.
Converter installation does not replace agent-managed skills or enter session snapshots.
Conversion helpers raise typed failures; the CLI boundary emits the status and a safe diagnostic.
Docker and Kubernetes share a strict converter response parser.
It requires a known status and nonempty page paths confined to the session workspace.
Each successful conversion response assigns a fresh slide image token.
A vertical thumbnail column supports click and keyboard navigation, marks the
selected slide, and scrolls it into view. Thumbnail images load lazily.
Keyboard navigation only handles events within the slide toolbar.
Inactive presentations ignore keyboard navigation. Closed output panels are inert,
so their controls cannot receive focus or keyboard input.
Updated decks clamp the current slide to their new bounds.
The saved slide initializes the viewer; parent updates do not reset local navigation.
Each slide image owns its loading state and releases it when its source changes.

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
3. Open the session app preview. Confirm the app renders and its controls respond.
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

Unsupported and oversized file previews show a Download action beside their explanation.

### Resource and inventory ownership

Each open tab owns one local record for reload, loading, export, and viewer position.
Closing and reopening a file or Outputs collection starts a new viewer lifetime, including batched changes.
All Files retains one browser for the selected workspace, including while its tab is closed.
Callbacks from retired tab instances cannot update their replacements.
Inventory request loading is separate from accepted scan completeness.
Cancellation releases request loading without changing accepted metadata or completeness.
Each mounted Outputs collection owns a distinct SWR provider identity over the retained thumbnail cache.
A functional cache factory keeps its Map private; storage I/O and revision acceptance stay separate from cache ownership.
Unmounting one collection cannot remove another collection’s SWR subscriptions.
Session activation restores thumbnail revision and deletion checks in the same committed lifecycle.
Pending preview callbacks cannot write before those checks return.
