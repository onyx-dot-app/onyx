# Desktop, Widget and Chrome Extension

> Thin clients that bring Onyx outside the main web app: a Tauri desktop
> shell, a chat widget that a site embeds, and a Chrome extension. None runs
> product logic, and only the widget calls the chat endpoints itself.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE. JWT passthrough for the widget works on single-tenant
deployments only.

---

## User experience

- **A desktop user** installs the app for macOS, Windows or Linux. On first
  launch it asks for the server URL (default `https://cloud.onyx.app`), then
  shows the normal web app in a native window with global shortcuts and a
  summon shortcut. On macOS the window has a custom titlebar. Links from a
  chat open in the system browser. A server that cannot be reached shows the
  settings page again.
- **A visitor to a customer's site** sees a chat launcher or an inline chat
  box. Answers stream as in the main app. There is no login screen. The site
  owner either puts a scoped API key in the page, or gives the widget a
  `tokenProvider` function that returns the visitor's own IdP token, so each
  visitor acts as their own Onyx user. The transcript survives a reload in the
  same tab for 24 hours. The admin guide is
  `documentation/deployment/configuration/website_widget.mdx`.
- **A Chrome user** gets a side panel with the full web app, a "select text
  and ask Onyx" icon on every page, the `onyx <query>` omnibox keyword, and an
  optional new-tab page. The user is signed in as in a browser tab, because the
  panel is an iframe of their Onyx domain. An enterprise admin can set the
  domain and the new-tab default by Chrome policy. SSO sign-in inside the panel
  opens the IdP in a new tab, and the panel picks up the session when the user
  returns.

On failure: the widget shows the error text in the chat when the send fails,
for example on a stream line that is not valid JSON, a backend `error` packet,
or a missing credential. A send that fails before the server accepts it
removes the message and puts the text back in the input. Send stays disabled
until the server confirms that the conversation is idle
([[#widget-send-waits-for-idle]]). The extension shows its own timeout dialog when the
iframe does not report that it loaded.

---

## Scope

This component holds the desktop shell, the widget, the Chrome extension, and
the framed pages and framed sign-in path in the web app that only these clients
need. Each client has a README with its build and design notes.

It does not own the chat UI that the desktop shell and the side panel load
([[chat-frontend]]), the chat endpoints ([[core-chat-loop]]), API keys and JWT
verification ([[auth-and-identity]]), or the acting-user rules for the widget
(CROSS-CUTTING.md). [[mobile-app]] is a separate, native client.

---

## Architecture

**Desktop.** `desktop/src-tauri/src/main.rs:main` loads the config
(`desktop/src-tauri/src/config.rs:load_config`), builds the window, and
registers shortcuts, the tray and a navigation plugin. `desktop/src/index.html`
is the fallback page for a missing or unreachable server. It calls the Tauri
commands `get_bootstrap_state`, `check_server_reachable` and `set_server_url`
(`desktop/src-tauri/src/commands.rs`), then sends the webview to the server. On
macOS, `desktop/src-tauri/src/window.rs:eval_titlebar_script` injects
`desktop/src/titlebar.js` on every page load. The Rust side calls the server
only for `/api/version` and a reachability check. The webview holds the cookie
session.

**Widget.**
```
<onyx-chat-widget backend-url=... api-key=...>      widget/src/widget.ts
  └─ resolveConfig (attributes win over VITE_* build values)  config/config.ts
send → ApiService                                   services/api-service.ts
  ├─ waitForSessionIdle  (existing session) → GET /chat/chat-session/{id}/status
  ├─ createChatSession   (first message only)
  ├─ streamMessage → POST /chat/send-chat-message, origin "widget"
  │    └─ parseSSEStream (NDJSON lines) → stream-parser.ts:processPacket
  │         └─ saveSession to sessionStorage, scoped by credential identity
  └─ finally: waitForSessionIdle again, then enable Send
```
`widget/src/config/config.ts:resolveAuthToken` picks the credential for each
request: the `tokenProvider` result, else the API key, else it throws. The
widget reads a `tokenProvider` at request time because the host page often
sets it after the element mounts. In passthrough mode the backend verifies the
JWT (RS256) in `backend/onyx/auth/jwt.py:verify_jwt_token`.

**Chrome extension.** The extension has no bundler. Chrome loads the files as
they are. `extensions/chrome/src/pages/panel.js` points an iframe at
`{domain}/nrf/side-panel`. The selection icon
(`extensions/chrome/src/utils/selection-icon.js`, a content script on every
page) sends an `OPEN_SIDE_PANEL_WITH_INPUT` message to the service worker,
which opens the panel with a `user-prompt` URL. The keyboard command takes the
same route through `extensions/chrome/service_worker.js:sendToOnyx`. When tab
reading is on, the service worker sends the URL of the active tab to the
panel, which passes it to the iframe. `extensions/chrome/src/utils/storage.js`
reads `chrome.storage.managed` (policy) before `chrome.storage.local`.

**Framed sign-in.** In an iframe,
`web/src/app/auth/login/ProviderSignInButton.tsx:openIdpTab` opens the IdP in a
new tab, because IdPs refuse to load in a frame.
`web/src/app/nrf/NRFPage.tsx` calls `refreshUser` on `visibilitychange`, so the
panel picks up the new session when the user returns.

---

## Contracts and traps

1. `desktop-capabilities-reach-every-server` **Every desktop capability
   applies to every server the user enters.**
   `desktop/src-tauri/capabilities/main.json` grants window dragging,
   double-click maximize and `shell:default` to the remote pattern
   `http://*:*` and `https://*:*`, because the server URL is user-set. A new
   permission reaches any page that any configured server serves. Add one
   only for a native feature the webview calls. The same holds for each app
   command in the `generate_handler!` list in
   `desktop/src-tauri/src/main.rs`: `desktop/src-tauri/build.rs` declares no
   app manifest, so Tauri allows every registered command, and a page from
   any server can invoke it.
2. `os-opener-scheme-allowlist` **Only `http`, `https`, `mailto` and `tel`
   reach the OS opener.**
   `desktop/src-tauri/src/window.rs:is_externally_openable` gates popups and
   the `open_in_browser` command, and
   `desktop/src-tauri/src/window.rs:should_open_in_external_browser` has its
   own scheme match for in-page navigation. Change both together. A `file:` or
   custom scheme would let a link on a hostile page open local files or apps.
3. `external-nav-only-from-chat` **In-page navigation leaves the app only from
   a chat.** `should_open_in_external_browser` returns true only when the
   current URL is a chat session (`is_chat_session_url`: `/app` with a
   `chatId`), and then only for `mailto`, `tel` or an `http(s)` link to another
   origin. This keeps the settings and login flows inside the app. Popups
   (`window.open`, `target="_blank"`) go to the browser from every page.
4. `widget-credential-public` **A widget credential is visible to anyone who
   can read the page.** The API key sits in an HTML attribute, or, for a
   self-hosted build, in the bundle (`widget/vite.config.ts` `define`). The
   widget keeps it in memory and never writes it to `sessionStorage`. Keep it
   that way, and tell integrators to use a scoped key.
5. `widget-transcript-scoped-by-identity` **The stored widget transcript is
   scoped by credential identity.**
   `widget/src/config/config.ts:deriveCredentialIdentity` uses the JWT `sub` or
   `email`, else a shared value. `widget/src/utils/storage.ts:loadSession`
   drops a session for another identity. A JWT with neither claim falls back
   to the shared value, so a second such visitor in the same tab can restore
   the transcript of the first.
6. `widget-reset-cancels-send` **`resetConversation` must cancel a send at
   every stage.** The admin guide tells host pages to call it on sign-out or an
   account change, so a send that survives a reset shows the previous user's
   response to the next user in the same tab.
   `widget/src/widget.ts:OnyxChatWidget.sendMessage` creates its
   `AbortController` before the first await, and checks for an abort after
   each await and for each packet. Its `finally` clears shared state only when
   `this.abortController` is still its own controller, so a stale send cannot
   clear the state of a newer send. Keep all three when you add an await or a
   new step to a send.
7. `widget-ignores-unknown-packets` **The widget stream fails only on a
   malformed line or an `error` packet.**
   `widget/src/services/api-service.ts:parseSSEStream` throws on a line that
   does not parse. `widget/src/services/stream-parser.ts:processPacket` throws
   on a packet with no `obj` or no `type`, and on an `error` packet. It
   ignores an unknown packet type. A new backend packet therefore does not
   break the widget, but it shows nothing until `processPacket` handles it.
8. `widget-bundle-outlives-backend` **A deployed widget bundle outlives the
   backend version it was built for.** Customer sites keep the old widget
   bundle. A change to the request shape of `create-chat-session` or
   `send-chat-message`, or to an existing packet, breaks those embeds with no
   version check. Treat the attributes on `<onyx-chat-widget>` as a public API
   for the same reason.
9. `widget-passthrough-single-tenant` **Widget passthrough needs a
   single-tenant deployment.** On cloud the tenant comes from the credential
   (`ee/onyx/server/middleware/tenant_tracking.py:_get_tenant_id_from_request`),
   and an external IdP token carries none.
10. `extension-postmessage-origin-locked` **Extension `postMessage` channels
   are origin-locked both ways.**
   `extensions/chrome/src/pages/panel.js:handleMessage` accepts a message only
   from the window of its own iframe and from `getIframeOrigin()`.
   `extensions/chrome/src/pages/onyx_home.js` checks `getOnyxOrigin`. Neither
   falls back to `"*"`. The new-tab messages `PREFERENCES_UPDATED` and
   `LOAD_NEW_PAGE` have no sender in the web app, so the origin check is their
   only guard. A failed check must reject the message.
11. `widget-send-waits-for-idle` **The end of the stream does not enable
    Send.** `widget/src/widget.ts:OnyxChatWidget.sendMessage` polls
    `widget/src/services/api-service.ts:ApiService.waitForSessionIdle` before a
    send to an existing session and after every send, because the server can
    still save the turn after the stream ends. Failed polls retry and keep
    Send disabled; there is no overall deadline. A 403 or 404, a 405, or three
    401s in a row end the wait with an error, and none counts as idle. A
    backend without the status route answers 404, so a new bundle on an older
    server shows "no longer available" after the first answer
    ([[#widget-bundle-outlives-backend]]).
12. `test-panel-signin-before-narrowing-hosts` **Test sign-in in the side panel
    before you narrow `<all_urls>`.** `extensions/chrome/manifest.json`
    requests `<all_urls>` host access and injects the selection icon on every
    page. The host grant may also be what lets the panel iframe send its
    auth cookie (Known issues).

---

## Known issues

- **The extension has no tests, build, type check or lint.** The widget tests
  cover only session readiness and failed drafts.
- **`<all_urls>` is broader than the features need.** Only the selection icon
  and tab reading need page access. Open question: the host grant may also be
  what lets the panel iframe send its `SameSite=Lax` auth cookie, because
  Chrome treats a request from an extension page to a permitted origin as
  same-site. Nobody has tested this. A possible replacement is
  `optional_host_permissions` with a `chrome.permissions.request` for the one
  Onyx origin.
- **API-key widgets have no key rotation.** The key is whatever the site owner
  pasted. Passthrough leaves expiry to the host page.

---

## Dependencies

- [[chat-frontend]]: the desktop shell and the side panel load it as it is.
- [[core-chat-loop]]: the widget calls the chat endpoints directly.
- [[streaming-protocol]]: the widget parses the packet stream itself.
- [[auth-and-identity]]: API keys and JWT verification for the widget, and the cookie session for the other two clients. The send endpoint sets the origin to `api` for an API key or PAT caller, so only passthrough requests keep `widget`.
- [[multi-tenancy]]: tenant resolution blocks passthrough on cloud.

---

## Recipes

- `widget-packet-type` **Handle a packet type in the widget.** Copy the `citation_info` case in
  `widget/src/services/stream-parser.ts:processPacket`, and add a field to the
  message model. List the handled types with
  `grep -n 'case "' widget/src/services/stream-parser.ts`. Old bundles on
  customer sites ignore the new type ([[#widget-bundle-outlives-backend]]).
- `desktop-native-feature` **Add a desktop native feature.** Copy the `check_server_reachable` command
  in `desktop/src-tauri/src/commands.rs`, and register it in the
  `generate_handler!` list in `desktop/src-tauri/src/main.rs`. Add the
  narrowest permission to `desktop/src-tauri/capabilities/main.json`
  ([[#desktop-capabilities-reach-every-server]]). Validate the input in the
  command, because any server page can call it. Add a Rust unit test next to
  the code.
- `run-widget-local` **Run the widget against a local backend.** `cd widget && bun run dev`, with
  a `backend-url` attribute and a scoped API key. `widget/README.md` covers
  the build modes and the "Security Note".
- `run-extension-local` **Run the extension against a local app.** Load `extensions/chrome/`
  unpacked, set the domain to `http://localhost:3000`, and open the side
  panel. `extensions/chrome/README.md` covers the policy settings.
- `investigate-panel-timeout` **Investigate a side panel that shows the
  timeout dialog.** The iframe did
  not post its loaded message to the panel page. Check that the domain is right and
  that the user can sign in at `{domain}/nrf/side-panel` in a tab. Then check
  the origin match in `handleMessage`
  ([[#extension-postmessage-origin-locked]]).

---

## Verification

- Desktop: `cd desktop/src-tauri && cargo test && cargo clippy`. Tests sit in
  `#[cfg(test)]` modules next to the code. The clippy config warns on
  `unwrap`, `expect` and `panic`.
- Widget: `cd widget && bun run type-check && bun run test` (tests in
  `widget/tests/`, also run by `.github/workflows/pr-quality-checks.yml`). By hand, send a message, reload,
  and confirm the transcript returns.
- Extension: by hand, select text on a page and confirm the panel opens with
  it as the prompt. Try `onyx <query>` in the address bar.
