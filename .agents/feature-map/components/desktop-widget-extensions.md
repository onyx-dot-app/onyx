# Desktop, Widget, and Chrome Extension

> Three thin client surfaces that deliver Onyx outside the main web app: a
> Tauri desktop shell, an embeddable chat widget for third-party sites, and a
> Chrome extension. None of the three runs its own product logic. Each one
> loads or calls the same chat backend that [[chat-frontend]] uses.

**Domain:** client-surfaces
**Edition:** CE
**Owns:**
`desktop/` (`package.json`, `src/index.html`, `src/titlebar.js`, `src-tauri/`),
`widget/` (`package.json`, `vite.config.ts`, `index.html`, `src/`),
`extensions/chrome/` (`manifest.json`, `service_worker.js`, `src/`, `public/`)

**Read first:** `desktop/README.md`, `widget/README.md`,
`extensions/chrome/README.md`. Each is the design rationale for its surface.
This document maps all three to code and adds verification guidance.

---

## 1. What the user experiences

**Desktop.** A native macOS/Windows/Linux app window (`desktop/README.md`)
that looks and feels like a small native shell around Onyx: a custom
traffic-light titlebar, a settings panel for the server URL on first launch,
global keyboard shortcuts (new chat, new window, reload, back/forward, open
config), and a system tray/menu-bar summon shortcut. Once configured, the
window shows the exact same web app a browser would (`web/`), plus platform
polish: window-state memory, vibrancy (macOS), and links that open in the
user's regular browser instead of a second app window.

**Widget.** A customer visiting a third party's website sees a floating chat
launcher button (or an inline chat box embedded in the page) that they did
not get from onyx.app. It streams answers the same way the main chat UI
does: reasoning, then an answer, optionally with markdown formatting. There
is no login screen. The widget is pre-authorized by the site owner, who
embedded a key when they added the widget to their page.

**Chrome extension.** A user installs it from the Chrome Web Store, sees a
welcome page on first install (`extensions/chrome/src/pages/welcome.html`),
and gets: a side panel that renders the full Onyx web app in an iframe, a
"select text on any page, click a small icon, ask Onyx about it" flow, an
omnibox keyword (`onyx <query>`) that jumps straight to a chat, and an
optional new-tab-page override. Because the side panel is just an iframe to
the user's own Onyx domain, this user is logged in exactly as they would be
in a browser tab; the extension carries no credentials of its own.

---

## 2. Surfaces

| Surface | Entry point | Build command | Output artifact | Onyx endpoints called |
|---|---|---|---|---|
| Desktop | `desktop/src-tauri/src/main.rs:main`, webview loads the configured `server_url` (`desktop/src-tauri/src/config.rs:DEFAULT_SERVER_URL`) | `bun run build` (`desktop/package.json`, wraps `tauri build`) | Platform bundle: `.dmg`/`.app` (macOS), `.msi`/`.exe` (Windows, via `bun run build:windows`), `.deb`/`.rpm` (Linux) in `src-tauri/target/release/bundle/` | None directly. The webview loads the full web app, which calls the normal `/api/*` surface; the Rust side only calls `GET {server_url}/api/version` (`desktop/src-tauri/src/main.rs:fetch_server_version`) and does an unauthenticated `HEAD` reachability check (`desktop/src-tauri/src/commands.rs:check_server_reachable`) |
| Widget | `widget/src/index.ts` (registers the `<onyx-chat-widget>` custom element from `widget/src/widget.ts`) | `bun run build:cloud` or `bun run build:self-hosted` (`widget/package.json`, Vite library mode, `widget/vite.config.ts`) | `dist/onyx-widget.js`, a single ES module (~100-150kb gzipped per `widget/README.md`) | `POST {backend-url}/chat/create-chat-session` and `POST {backend-url}/chat/send-chat-message` (`widget/src/services/api-service.ts:createChatSession`, `streamMessage`) |
| Chrome extension | `extensions/chrome/manifest.json` (`background.service_worker`, `action.default_popup`, `side_panel.default_path`); no bundler, files are loaded unpacked | None. `extensions/chrome/README.md` says "load unpacked ... refresh extension in Chrome" | The `extensions/chrome/` directory itself, zipped for the Chrome Web Store | None directly from extension JS. `extensions/chrome/src/pages/panel.js` points an `<iframe>` at `{onyx-domain}/nrf/side-panel` (`extensions/chrome/src/utils/constants.js:SIDE_PANEL_PATH`); every backend call happens inside that iframe, through the normal web app, under the user's cookie session |

### Configuration

| Surface | Setting | Where | Effect |
|---|---|---|---|
| Desktop | `server_url` | `~/Library/Application Support/app.onyx.desktop/config.json` (macOS path; see `desktop/README.md` for Linux/Windows), read by `desktop/src-tauri/src/config.rs:load_config` | The only server this instance talks to. Defaults to `https://cloud.onyx.app` (`config.rs:DEFAULT_SERVER_URL`). Self-hosted use is a config edit, not a rebuild. |
| Desktop | `summon_shortcut` | Same config file, `config.rs:default_summon_shortcut` | Global OS shortcut (`Super+Shift+Space` macOS / `Ctrl+Alt+Space` elsewhere) that raises the app from anywhere; can be set to `null` |
| Widget | `backend-url`, `api-key` | HTML attributes on `<onyx-chat-widget>`, or `VITE_WIDGET_BACKEND_URL`/`VITE_WIDGET_API_KEY` baked in at build time for self-hosted builds (`widget/vite.config.ts`, `widget/src/config/config.ts:resolveConfig`) | Which backend the widget calls and the credential it authenticates with. Attributes always win over the baked-in env values. |
| Chrome extension | `onyxExtensionDomain` | `chrome.storage.local`, default `http://localhost:3000` (`extensions/chrome/src/utils/constants.js:DEFAULT_ONYX_DOMAIN`), set via the options page (`extensions/chrome/src/pages/options.js`); `getOnyxDomain` (`storage.js`) trims the value and strips trailing slashes | Which Onyx deployment the side panel, new-tab override, and omnibox all point at |
| Chrome extension | `onyxExtensionDomain`, `onyxExtensionDefaultNewTab` (enterprise policy) | `chrome.storage.managed`, populated by Chrome's extension policy (`extensions/chrome/managed_schema.json`, `extensions/chrome/README.md`'s "Enterprise configuration") | Admin-set values in managed storage take precedence over `chrome.storage.local` and are read-only in the options page; `setUseOnyxAsDefaultNewTab` (`storage.js`) is a no-op when the toggle is managed |

---

## 3. Data model

Mostly not applicable: none of the three owns a database table, and all
three are stateless clients of the same chat backend tables
([[chat-persistence]]).

**Desktop.** The only persisted local state is the config file
(`desktop/src-tauri/src/config.rs:AppConfig`): `server_url`, `window_title`,
`show_menu_bar`, `hide_window_decorations`, `summon_shortcut`,
`summon_opens_new_chat`. No credential is stored here; the app holds no
session of its own; whatever cookie the webview accumulates is the webview's
own storage, managed by the OS webview engine, not by Tauri code.

**Widget.** `sessionStorage`, one JSON blob per browser tab
(`widget/src/utils/storage.ts:SESSION_KEY`, TTL 24h), holding
`{ sessionId, messages, timestamp }`. This is the chat session ID and message
history, not a credential. **The API key itself is not stored by the widget
code**; it lives only in the customer page's HTML (an attribute on
`<onyx-chat-widget>`) or, for self-hosted builds, gets compiled directly into
the published `dist/onyx-widget.js` (`widget/vite.config.ts`'s `define`
block). Either way it is plain text, readable by anyone who views the
embedding page's source or the shipped bundle.

**Chrome extension.** `chrome.storage.local` holds only UI preferences:
`onyxExtensionDomain`, `onyxExtensionDefaultNewTab`, `onyxExtensionTheme`,
background image URLs, and an onboarding-complete flag
(`extensions/chrome/src/utils/constants.js:CHROME_SPECIFIC_STORAGE_KEYS`).
`chrome.storage.session` holds a short-lived `pendingInput` (selected text
plus target URL, 5-second TTL, cleared after use,
`extensions/chrome/service_worker.js:sendToOnyx`) and a `tabReadingEnabled`
flag. No credential is stored; auth is the cookie session inside the iframe.
`chrome.storage.managed` (enterprise policy, `managed_schema.json`) can set
`onyxExtensionDomain` and `onyxExtensionDefaultNewTab`; `getOnyxDomain` and
`getUseOnyxAsDefaultNewTab` (`storage.js`) read managed storage first and
fall back to `chrome.storage.local` only when policy has not set the key.

---

## 4. How it works

### 4.1 Desktop: first launch to a loaded chat

```
main()                                          src-tauri/src/main.rs
  ├─ config::load_config()                      reads config.json or returns defaults
  ├─ Builder::default().setup(setup_app)        src-tauri/src/main.rs:setup_app
  │    ├─ window::build_main_window(app)        builds the "create": false window from tauri.conf.json
  │    ├─ shortcuts::setup_global_shortcuts     registers summon_shortcut
  │    ├─ menu::setup_app_menu / setup_tray_icon
  │    ├─ apply_vibrancy (macOS)
  │    └─ window::inject_titlebar(window)       src-tauri/src/window.rs, evals titlebar.js on a retry schedule
  └─ on_page_load: eval_titlebar_script + inject_console_capture (debug mode)
```

`src/index.html` is the **fallback page** (`desktop/README.md`'s "Project
Structure"), shown only when no `server_url` is configured yet or the
configured server is unreachable
(`commands.rs:check_server_reachable`). It calls
`invoke("get_bootstrap_state")` and `invoke("set_server_url")`
(`commands.rs:get_bootstrap_state`, `set_server_url`) then redirects
`window.location.href` to the real server. Once redirected, the webview is
just the web app; `titlebar.js` is re-injected on every page load
(`window.rs:eval_titlebar_script`) to draw the draggable native-feeling
titlebar over it, and CSS custom properties reserve space at the top of
`<html>` so the web app's own `100vh`/`100dvh` layouts do not draw under it.

### 4.2 Widget: embed to first answer

```
customer HTML: <onyx-chat-widget backend-url=... api-key=...>
  └─ OnyxChatWidget.connectedCallback()          widget/src/widget.ts
       ├─ resolveConfig(...)                     widget/src/config/config.ts (attrs win over VITE_* env)
       ├─ new ApiService(backendUrl, apiKey)      widget/src/services/api-service.ts
       └─ loadSession() from sessionStorage       widget/src/utils/storage.ts
user sends a message
  ├─ ApiService.createChatSession()  → POST /chat/create-chat-session   (first message only)
  └─ ApiService.streamMessage()      → POST /chat/send-chat-message, origin="widget"
       └─ parseSSEStream(response)                api-service.ts, newline-delimited JSON
            └─ processPacket(...)                 widget/src/services/stream-parser.ts
                 └─ widget.ts re-renders messages, saveSession() after each update
```

Every request carries `Authorization: Bearer {api-key}`
(`api-service.ts:getHeaders`) straight from the browser to `backend-url`.
`origin: "widget"` on the send-message body maps to
`MessageOrigin.WIDGET` (`backend/onyx/server/query_and_chat/models.py:MessageOrigin`),
which the backend uses for telemetry only.

### 4.3 Chrome extension: side panel to answer

```
user clicks the toolbar icon or presses the "openSidePanel" command
  └─ chrome.sidePanel.open()                      service_worker.js:openSidePanel
       └─ panel.html loads panel.js
            ├─ loadOnyxDomain()                    reads onyxExtensionDomain from storage
            └─ iframe.src = {domain}/nrf/side-panel
user selects text on any page and clicks the injected icon
  └─ selection-icon.js posts {action: OPEN_SIDE_PANEL_WITH_INPUT, selectionText}
       └─ service_worker.js:sendToOnyx builds a /nrf/side-panel?user-prompt=... URL,
          opens the side panel, and relays it to panel.js
```

The extension never talks to `/chat/*` itself. The iframe loads the real
Onyx web app at the user's configured domain, and that page (running the
same code as [[chat-frontend]]) does everything a normal browser session
would, including cookie-based auth. `panel.js:handleMessage` only accepts
`postMessage` events whose `event.source` is the iframe's own
`contentWindow` and whose `event.origin` matches `getIframeOrigin()`, so a
page that later navigates the iframe cross-origin cannot send it privileged
messages such as `TAB_READING_ENABLED`.

**SSO inside the embedded panel and new-tab page.** An identity provider
refuses to render its own login page inside a frame, so
`ProviderSignInButton` (`web/src/app/auth/login/ProviderSignInButton.tsx`)
detects that it is framed (`isFramed`, `window.top !== window.self`) and
opens the IdP in a new browser tab instead of navigating the iframe
(`openIdpTab`/`navigateToIdp`), falling back to the top-level window if the
popup is blocked. `NRFPage` (`web/src/app/nrf/NRFPage.tsx`) re-checks the
session (`refreshUser`) on `visibilitychange`/`focus` while unauthenticated,
so the panel or new-tab page picks up the completed sign-in when the user
returns to it, since the IdP redirect landed in the other tab, not this
frame.

---

## 5. Contracts and invariants

1. **The desktop shell must not grant the webview more native capability than
   it uses.** `desktop/src-tauri/capabilities/main.json` currently grants
   exactly three permissions: `core:window:allow-start-dragging`,
   `core:window:allow-internal-toggle-maximize`, and `shell:default` (for
   `target="_blank"` links), scoped `"remote": {"urls": ["http://*:*",
   "https://*:*"]}` because the server is user-configurable. Any addition
   here (filesystem, clipboard, process spawn, etc.) widens what a
   compromised or malicious remote page can do, since the same grant applies
   to every origin the webview loads.
2. **Only `http`, `https`, `mailto`, `tel` may reach the OS opener.**
   `desktop/src-tauri/src/window.rs:is_externally_openable` is the single
   gate for both `window.open`/`target="_blank"` (`open_new_window_externally`)
   and the external-navigation handler in `main.rs`. Loosening it (adding
   `file:` or a custom scheme) turns a link click on a compromised page into
   local code or file execution.
3. **External navigation only redirects away from an active chat
   session.** `window.rs:should_open_in_external_browser` only fires when
   `is_chat_session_url` matches (`/app` path plus a `chatId` query param);
   this scoping is deliberate so the settings/login flow is not redirected
   out to the OS browser.
4. **The widget must never expose the API key back to the embedding page.**
   The widget only ever *reads* the `api-key` attribute the page owner set
   (`widget/src/widget.ts`'s `@property({attribute: "api-key"})`) and sends
   it as a request header (`api-service.ts:getHeaders`); it does not persist
   it, echo it into the DOM beyond the attribute the page itself wrote, or
   put it in `sessionStorage`. The unavoidable exposure is structural, not a
   widget bug: **any credential placed in an HTML attribute or a shipped JS
   bundle is visible to that page's own script and to anyone who views
   source.** `widget/README.md`'s "Security Note" states this and tells
   integrators to use a scoped key, not a full-access one.
5. **The Chrome extension must request the narrowest permissions and host
   permissions that work.** Today it requests
   `["sidePanel", "storage", "activeTab", "tabs"]` plus
   `"host_permissions": ["<all_urls>"]` and a content script matching
   `<all_urls>` (`extensions/chrome/manifest.json`). See §9: this is broader
   than the visible feature set needs.
6. **All three consume the same chat backend contract.** None of them
   re-implements chat logic; the desktop shell loads the web app verbatim,
   the widget calls `/chat/create-chat-session` and `/chat/send-chat-message`
   directly, and the extension's side panel is the web app in an iframe. A
   backend contract change to those two endpoints, or to the streaming
   packet shape, reaches all three simultaneously.
7. **The extension pages' `postMessage` channels are origin-locked in both
   directions.** `panel.js` computes `getIframeOrigin()` from `iframe.src`,
   and the new tab page (`onyx_home.js`) does the same with
   `getOnyxOrigin(iframe)`. Neither falls back to `"*"`. A `postMessage`
   failure here must fail closed (reject the message), not silently widen to
   any origin. Some new tab handlers (`PREFERENCES_UPDATED`, `LOAD_NEW_PAGE`)
   have no sender in the web app, so the origin check is their only guard.

---

## 6. Relationships

**Depends on**
- [[core-chat-loop]] and [[streaming-protocol]]: the widget parses the same
  NDJSON packet stream `run_llm_loop` emits; the desktop and extension
  surfaces consume it indirectly, through the embedded/loaded web app.
- [[chat-frontend]]: the desktop shell and the extension's side panel both
  load this app wholesale rather than reimplementing any UI.
- [[auth-and-identity]]: the widget authenticates as a non-human caller
  through the API-key path (`backend/onyx/auth/api_key.py`); the desktop
  webview and the extension's iframe authenticate as the logged-in human,
  through the normal cookie session that [[auth-and-identity]] documents.
  Several `/chat/*` endpoints also allow `allow_anonymous=True`
  (`backend/onyx/server/query_and_chat/chat_backend.py`), but the widget's
  own contract is API-key auth, not anonymous access; a widget deployed
  without a key would rely on that anonymous path if the backend allows it,
  which is unverified from this repository alone.
- [[onyx-api]]: the widget's two-endpoint integration is a narrow, unofficial
  slice of the same public HTTP surface.
- [[whitelabelling-and-theme]]: the widget's color attributes
  (`primary-color`, `background-color`, `text-color`, `logo`) are a
  per-embed equivalent of the enterprise branding settings that component
  owns; they are not the same mechanism and are not read from the backend.

**Depended on by**
- Nothing in the codebase depends on these three; they are leaf clients.

**Related, not dependent**
- [[mobile-app]]: a fourth "Onyx outside the web app" surface, but a native
  React Native app rather than a thin wrapper or embed; it is out of scope
  for this document.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| changes `/chat/send-chat-message` or `/chat/create-chat-session`'s request/response shape | the widget's `ApiService` (`widget/src/services/api-service.ts`) breaks immediately; the desktop shell and extension are unaffected directly (they load the web app, which is versioned together), but any deployed *old* widget bundle against a *new* backend breaks silently for every site that embedded it |
| changes the NDJSON packet vocabulary ([[streaming-protocol]]) | `widget/src/services/stream-parser.ts:processPacket` needs the new packet type or it is silently dropped; there is no server-side version negotiation, so an old cached widget bundle on a customer's site keeps parsing the old shape |
| changes chat auth (cookie shape, session mechanics, or the API-key check in `backend/onyx/auth/api_key.py`) | the widget's Bearer-token flow breaks first, since it is the only one of the three that authenticates directly rather than through a full browser session; the desktop webview and extension iframe ride the normal cookie flow and are unaffected unless cookie/session behavior itself changes |
| changes `desktop/src-tauri/capabilities/main.json` | re-derive from zero: does the new permission match a concrete native feature the webview invokes; a broadened `remote.urls` scope widens what a malicious `server_url` (or a compromised legitimate one) can do |
| changes `extensions/chrome/manifest.json`'s `permissions`/`host_permissions` | re-justify each one against the visible feature list (§9); a Chrome Web Store review will also flag unused broad permissions |
| changes the widget's public HTML-attribute contract (`widget/src/widget.ts`'s `@property` list) | `widget/README.md`'s configuration tables go stale; every existing customer embed snippet is a compatibility surface, so removing or renaming an attribute is a breaking change for every site that already embedded the old snippet |
| changes `SIDE_PANEL_PATH` or the `postMessage` message types (`extensions/chrome/src/utils/constants.js`) | `panel.js`'s `handleMessage` and the corresponding web app code that posts `ONYX_APP_LOADED`/`AUTH_REQUIRED`/etc. must change together; a mismatch shows the extension's own timeout error modal (`extensions/chrome/src/utils/error-modal.js`), not a backend error |

---

## 8. How to verify a change

### Tests

**Desktop** has real unit tests, in Rust, colocated with the code:
```bash
cd desktop/src-tauri && cargo test
```
Covers: URL/origin logic in `window.rs` (`same_origin`, `is_chat_session_url`,
`should_open_in_external_browser`, `is_externally_openable`, `redact_url`),
config serde defaults in `config.rs`, and alt-menu/shortcut logic in
`alt_menu.rs`/`shortcuts.rs`/`debug_log.rs` (see each file's
`#[cfg(test)] mod tests`). Run `cargo clippy` too; `Cargo.toml`'s
`[lints.clippy]` block enables `pedantic`/`nursery`/`unwrap_used`/
`expect_used`/`panic`, so most failure paths are required to return
`Result` rather than panic.

**Widget** has no test files under `widget/` (`find
widget/src -iname '*.test.*' -o -iname '*spec*'` returns nothing). The
closest to a check is `bun run type-check` (`tsc --noEmit`,
`widget/package.json`).

**Chrome extension** has no test files or build tooling at all; it is loaded
unpacked directly from source. There is no `type-check` or lint script in
this directory.

None of the three surfaces has an integration or playwright suite in this
repository. Verification below is manual.

### Manual reproduction

**Desktop**
1. `cd desktop && bun install` (once, from repo root per `desktop/README.md`),
   then `bun run dev`.
2. On first launch, confirm the settings screen (`desktop/src/index.html`)
   appears and rejects a URL without `http(s)://`.
3. Point it at `http://localhost:3000`, confirm it redirects into the real
   web app and the custom titlebar (`titlebar.js`) is drawn above it without
   clipping the app's own header.
4. Test `⌘N` (new chat), `⌘⇧N` (new window), `⌘,` (open config), and confirm
   a `target="_blank"` link opens in the system browser, not a new app
   window.

**Widget**
1. `cd widget && bun install && bun run dev`, opens
   `http://localhost:5173` (`widget/README.md`).
2. Confirm the launcher button appears, and that clicking it opens a working
   chat backed by a real `backend-url`/`api-key` you configure (see
   `widget/.env.example`).
3. Send a message; confirm the SSE stream renders progressively and the
   session persists across a page reload (`sessionStorage`, §3).
4. Open browser devtools and confirm the `api-key` attribute is visible in
   the DOM inspector, demonstrating the credential-exposure contract in §5.4
   is real, not theoretical.

**Chrome extension**
1. Visit `chrome://extensions`, enable Developer Mode, "Load unpacked",
   select `extensions/chrome/`.
2. Set the Onyx domain in the options page to `http://localhost:3000`.
3. Open the side panel (toolbar icon or `Ctrl+O`/`⌘⇧O`) and confirm it loads
   `/nrf/side-panel` and shows a logged-in Onyx session if one exists in that
   browser profile.
4. Select text on any page, click the injected icon, and confirm the side
   panel opens pre-filled with that text as a prompt.
5. Test the omnibox: type `onyx <query>` in the address bar and confirm it
   navigates to `/chat?user-prompt=...`.

### What "working" looks like

- Desktop: the webview shows the identical chat experience a browser tab
  would, with no layout collisions from the injected titlebar.
- Widget: streaming latency and citation rendering match the main chat UI,
  and no network request from the widget carries anything other than the
  configured `backend-url`/`api-key`.
- Extension: the side panel iframe reaches `ONYX_APP_LOADED` within the
  panel's 2.5s timeout (`panel.js:startIframeLoadTimeout`), or the auth/error
  modal appears instead of a blank panel.

---

## 9. Footguns

- **The desktop capability grant is broad by necessity, not by oversight,
  but it is still broad.** `remote.urls: ["http://*:*", "https://*:*"]`
  (`capabilities/main.json`) means *any* server the user points the app at
  gets the same `shell:default` and window-dragging grants as the official
  cloud server. This is a materially different risk profile from a browser
  tab: a browser scopes its own capability per origin via web platform APIs
  and extension permissions, while this grant is not re-evaluated per
  `server_url` change. Whether this is exploitable depends on what
  `shell:default` allows beyond opening URLs in the default browser; this
  document does not verify the full transitive capability of the `shell`
  plugin beyond what `main.json`'s own description states, and that is worth
  treating as an open question rather than a settled one.
- **The Chrome extension's host permissions and content-script match pattern
  are `<all_urls>`, but only two features plausibly need page access:** the
  text-selection icon (`selection-icon.js`, injected via the
  `content_scripts` block) and the tab-URL-reading feature gated behind
  `tabReadingEnabled` (`service_worker.js`'s `tabs.onActivated`/`onUpdated`
  listeners). Everything else (side panel, omnibox, new-tab override,
  options) works through `chrome.tabs`/`chrome.sidePanel`/`chrome.storage`
  APIs that do not require host permissions at all. `<all_urls>` is a Chrome
  Web Store review flag and a bigger blast radius than the feature set
  implies; narrowing it would need per-origin activation (e.g.
  `activeTab`-only for selection, explicit opt-in for tab reading) rather
  than a standing broad grant. Before you remove the host permission, check
  that the embedded Onyx iframe still sends its `SameSite=Lax` auth cookie.
  Chrome treats a request from an extension page to an origin the extension
  has host permission for as same-site, and the Onyx domain is user-set, so
  the likely replacement is `optional_host_permissions` plus a
  `chrome.permissions.request` for that one origin when the user saves it.
- **The widget's own README states the exposure explicitly**
  (`widget/README.md`'s "Security Note"): the API key is visible client-side
  by construction, so a full-access key embedded in a widget is a live
  credential leak, not a hypothetical one. There is no rotation or
  short-lived-token mechanism visible in this codebase; the key is whatever
  the site owner pasted into the HTML.
- **Self-hosted widget builds bake the API key into the published JS file**
  (`widget/vite.config.ts`'s `define` block under `isSelfHosted`). Anyone who
  downloads `dist/onyx-widget.js` from the customer's CDN gets the key in
  plaintext; `terserOptions.compress.drop_console` strips `console.*` calls
  but does nothing to the embedded string literal.
- **The desktop app's external-navigation allowlist is narrower than it
  looks.** `should_open_in_external_browser` only redirects away from a
  `/app?chatId=...` URL (`window.rs:is_chat_session_url`); a link clicked
  from the settings page, a non-chat route, or a `window.open` popup from
  those routes stays inside the app webview instead of going to the system
  browser, which can surprise a user expecting every external link to leave
  the app.
- **The widget's SSE parser fails hard on any malformed line**
  (`api-service.ts:parseSSEStream` deliberately throws rather than skipping
  a bad packet, per its own comment "Fail fast ... don't hide backend
  issues"). A backend change that emits one packet type the widget doesn't
  recognize as `Packet`-shaped will end the entire stream for every widget
  user, not just log a warning.
- **There is no test coverage at all for the widget or the extension.** A
  regression in either is only caught by the manual steps in §8, and the
  extension has no type-checking step either, since it ships plain
  unbundled JavaScript.

---

Cross-links: [[chat-frontend]], [[core-chat-loop]], [[streaming-protocol]],
[[auth-and-identity]], [[onyx-api]], [[whitelabelling-and-theme]],
[[mobile-app]]
