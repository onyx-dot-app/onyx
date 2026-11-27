# Desktop, Widget and Chrome Extension

> Thin clients that bring Onyx outside the main web app: a Tauri desktop
> shell, a chat widget that a site embeds, and a Chrome extension. None runs
> product logic, and only the widget and the desktop launcher call the chat
> endpoints themselves.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE. JWT passthrough for the widget works on single-tenant
deployments only.

---

## User experience

- **A desktop user** installs the app for macOS, Windows or Linux. On first
  launch it asks for the server URL, signs in natively, then shows the normal
  web app in a native window. A global shortcut opens a launcher panel that
  asks or searches without the main window. Links to other sites open in the
  system browser. A server that cannot be reached shows a bundled offline
  window that reconnects by itself.
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
- **A Chrome user can share tabs with one chat.** The chat's "My Chrome" tab
  asks; the extension opens a consent window (tabs, sites, time limit). The
  chat's browser tools then act in those tabs as the user. The user stops it
  from the chat, the extension popup, or Chrome's debugging bar.

On failure: the widget shows the error text in the chat when the send fails,
for example on a stream line that is not valid JSON or a missing credential.
A server error shows a generic message, not the server text (Known issues). A send that fails before the server accepts it
removes the message and puts the text back in the input. Send stays disabled
until the server confirms that the conversation is idle
([[#widget-send-waits-for-idle]]). The extension shows its own timeout dialog when the
iframe does not report that it loaded.

---

## Scope

This component holds the desktop shell, the widget, the Chrome extension, and
the framed pages and framed sign-in path in the web app that only these clients
need. Each client has a README with its build and design notes.

The desktop app (`desktop/`) is a native Tauri 2 app for macOS, Windows and
Linux. It keeps the earlier web-view shell's bundle ID (`app.onyx.desktop`)
and name. The installers upgrade it in place (the MSI does a major upgrade),
except the Windows setup program (`.exe`): the old per-user copy stays, and
the app retires it at the user's first launch (uninstall entry first, then the
old shortcuts, `onyx.exe` and `uninstall.exe`, and the folder only if it is then
empty; the old uninstaller never runs, because it would delete this app's data
folders). The first launch imports the old server
URL. Version tags release it with
the server, except beta and cloud tags (the `ods release classify` routing). It signs in through
`/api/auth/mobile/login`, hands the token to the remote web UI as the session
cookie, and gives IPC only to its bundled windows. The main window never runs
the web sign-in: a load of `/auth/login`, `/auth/signup`, an `/api/auth/.../authorize`
URL, or an identity provider page whose `redirect_uri` is a server `/auth/` path
makes the app hand the cookie over again, or end the session and show its own
sign-in window. A change to those paths must keep this check. Its launcher panel (global
shortcut) calls the chat endpoints from Rust with the bearer token:
`POST /chat/create-chat-session`, then `POST /chat/send-chat-message`
(`origin "unknown"`), and it reads the streamed packets (text, citations,
`stop`, `tool_approval_request`). It lists agents with `GET /persona` and
creates a new chat with the chosen `persona_id`. It attaches files through
`POST /user/projects/file/upload`, polls `POST /user/projects/file/statuses`
until they are processed, and sends them as `file_descriptors`. A removed
attachment is deleted with `DELETE /user/projects/file/{id}`. It reads
`user_file_max_upload_size_mb` and `disable_default_assistant` from
`GET /settings`. Search mode
calls `POST /search/send-search-message`, with `filters.source_type` for a
source filter. A change to those request or packet shapes must keep the
launcher working. IT can preset the server and lock
some settings with managed policy (MDM profile, Windows registry policy, or a
Linux policy file). The desktop README lists the keys. When the server cannot be
reached, the app shows a bundled offline window that polls `GET /api/version` and
the web UI root `GET /` without a session (a 5xx from either counts as down),
then checks the session with `GET /api/me`, and loads the web UI again when
all answer, so `/api/version` must stay public. Sign-out
retries `POST /api/auth/mobile/logout` in the background while the server
cannot be reached.

It does not own the chat UI that the desktop shell and the side panel load
([[chat-frontend]]), the chat endpoints ([[core-chat-loop]]), API keys and JWT
verification ([[auth-and-identity]]), or the acting-user rules for the widget
(CROSS-CUTTING.md). [[mobile-app]] is a separate, native client.

---

## Architecture

**Desktop.** `desktop/src-tauri/src/main.rs:main` reads the config
(`desktop/src-tauri/src/config.rs:ConfigStore`, after
`desktop/src-tauri/src/migration.rs:import_previous` on a first launch) and the
managed policy (`desktop/src-tauri/src/policy.rs:read`), then
`desktop/src-tauri/src/windows.rs:route` opens onboarding, sign-in or the main
window. The local windows are React pages in `desktop/src/pages/`, built by
Vite; they call the commands in
`desktop/src-tauri/src/commands.rs`. The session token sits in the OS
credential store (`desktop/src-tauri/src/session_store.rs`).
`desktop/src-tauri/src/main_window.rs:open_url` loads the server in the main
window with the token as the session cookie, and
`desktop/src-tauri/src/main_window.rs:classify` decides where each navigation goes.

**Widget.**
```
<onyx-chat-widget backend-url=... api-key=...>      widget/src/widget.ts
  └─ resolveConfig (attributes win over VITE_* build values)  config/config.ts
send → ApiService                                   services/api-service.ts
  ├─ createChatSession   (first message only)
  ├─ waitForSessionIdle → GET /chat/chat-session/{id}/status; the
  │    approvals_version baseline is "" (a chat with no requests) until a
  │    session load, so a new chat whose first read reports another version
  │    loads the session; a latest_response_id the transcript lacks loads
  │    the saved session first, and the question goes under that answer
  ├─ streamMessage → POST /chat/send-chat-message, origin "widget"
  │    └─ parseSSEStream (NDJSON lines) → stream-parser.ts:processPacket
  │         └─ saveSession to sessionStorage, scoped by credential identity
  ├─ stream over → resumeStream({sent}): the one follow path below
  ├─ 409 APPROVAL_PENDING → keep the draft, show the message, resumeStream
  │    from the status with a session load (shows the waiting card), point
  │    at the card
  └─ a root question waits (questions.ts:findPendingWait) → no send: the
       text is a typed answer (below)
decision → POST /chat/approvals/{id}/decision       widget.ts, services/approvals.ts
  card (services/approval-card.ts): Approve once, Reject, and "Approve for
    this command" (approve_command) when can_approve_for_command, else
    "Approve for this chat" unless can_approve_for_chat is false
answers  → POST /chat/question-requests/{id}/answers   widget.ts, services/questions.ts
  card: one question per page (Back/Next, page in widget.ts questionPages);
    per question, one option or "Other" with a typed answer in place of an
    option (user_note, empty option_labels), also for a multi_select
    question; the record lists every chosen option; Submit on the last page
  typed: {message} answers every waiting question of the response; the
    input clears and the card record shows the text; 409
    APPROVAL_PENDING or another error (a query hook's refusal shows its
    detail) keeps the draft
  404 or a 409 conflict → "No longer waiting"; resumeStream from the status
  decisions and answers share followReply:
  no follow runs:
  ├─ continuation set → resumeStream from cursor 0 of continuation.stream_id
  ├─ 404/409 → card shows "No longer waiting"; resumeStream from the status,
  │    and the saved session shows the outcome
  ├─ continuation null, background agent request → resumeStream from the
  │    status (agents polled, below)
  ├─ continuation null, "Approve for this chat" → resumeStream from the
  │    current stream with a session load: the server also approved the
  │    chat's other requests for the tool, which only the load shows
  ├─ continuation null, nothing else waits for the user → resumeStream from
  │    the current stream, then each stream the status reports, then the
  │    saved session
  └─ continuation null, other root requests or questions wait → nothing
       starts
  a follow runs: a continuation is stored, and the follow takes it before it
    ends (never a stream it just read); with none, the follow reads the
    status once more before it ends
  a reset or another chat opened during the request → the result changes
    nothing in the open chat
restore / sent stream / decision / 409 → resumeStream    widget.ts
  ├─ GET /chat/chat-session/{id}/resume-stream (no stream_id: the current
  │    stream; cursor lines track stream_id and next_cursor; only a 404 stops
  │    requests for that stream)
  ├─ stop with "awaiting_user" → a continuation a decision named during
  │    the stream, else one status read: a new stream whose response_ids
  │    include the response → follow from 0; else stop following
  ├─ a replayed user_message whose question the transcript lacks inserts it
  │    before the answer (ids from the response-ID packet)
  ├─ ended before its stop → wait 1s, waitForSessionIdle reports current_stream:
  │    same stream → reattach from the last cursor; new stream → from 0
  ├─ after its stop (a transport failure after the stop counts; an error
  │    packet ends the follow with its error) → waitForSessionIdle, then
  │    enable Send; a new stream id → follow from 0
  └─ idle with a response unfinished or waiting for decisions, a sent
       answer or a status read's latest_response_id not shown, a question
       with no answer after it, or a changed approvals_version (restore and
       409 count as changed) → GET /chat/get-chat-session/{id} (every
       branch); walk the selected branch from the root along
       latest_child_message and replay its saved answers (by parent_message
       for questions; a question with none is removed; a version change
       replays answers with approval or question requests and answers the
       transcript lacks); the transcript takes the branch order; the load's
       approvals_version becomes the baseline; on failure the response stays
       unfinished and the version change stays pending for the next load
  replay_end and a resolution sent again (replay, then live) change nothing
any status read with has_active_subagents (a decided agent that waits to
  resume counts) or has_startable_input (queued input or an agent's unread
  result can start a turn) → read the status every 1s until both are false;
  each approvals_version change or unseen latest_response_id loads the
  session again; a new stream is followed; Send stays enabled, and a send
  ends the poll (its own follow polls on)
card status = the server's tool_approval_resolved or tool_question_resolved
  outcome ("cancelled" → "No longer waiting"), else this widget's decision or
  answer until the outcome arrives; no stop changes a card
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

**Chat browser control.** `extensions/chrome/src/browser/relay.js` keeps one
websocket to `/api/chat/browser/extension/ws` (a single-use token from a
cookie POST; pings every 20 s; an alarm reconnects). It answers the chat
browser methods with `extensions/chrome/src/browser/driver.js`, which drives the shared tabs over
`chrome.debugger` (CDP): an accessibility-tree snapshot with refs, trusted
input, dialogs, and an origin check on every call. The grant lives in
`chrome.storage.session`. `src/pages/browser-consent.*` is the consent
window. The backend half is `backend/onyx/browser_extension/relay.py` and
`backend/onyx/server/query_and_chat/chrome_browser.py`.

**Framed sign-in.** In an iframe,
`web/src/app/auth/login/ProviderSignInButton.tsx:openIdpTab` opens the IdP in a
new tab, because IdPs refuse to load in a frame.
`web/src/app/nrf/NRFPage.tsx` calls `refreshUser` on `visibilitychange`, so the
panel picks up the new session when the user returns.

---

## Contracts and traps

1. `desktop-ipc-local-windows-only` **Only the bundled windows get IPC.**
   Each file in `desktop/src-tauri/capabilities/` sets `"local": true` and
   names its window. Remote server pages in the main window and popups get
   only window dragging and title-bar zoom, and only on the configured server
   origin (`desktop/src-tauri/src/main_window.rs:allow_window_dragging`). A new
   command that a server page can call would reach every page of any server
   that a user enters. Keep commands for the local windows.
2. `os-opener-scheme-allowlist` **Only `http`, `https`, `mailto` and `tel`
   reach the OS opener.** `desktop/src-tauri/src/main_window.rs:classify`
   blocks every other scheme, and `classify_popup` and the navigation handlers
   use it. A `file:` or custom scheme would let a link on a hostile page open
   local files or apps.
3. `desktop-main-window-server-origin` **The main window shows only the
   configured server.** `classify` allows a same-origin `http(s)` or `blob:`
   URL and `about:blank`/`about:srcdoc`; another site opens in the system
   browser. Popups (`classify_popup`) may also show other HTTPS sites, for
   OAuth consent and identity providers.
4. `desktop-oauth-handoff-legacy` **The `.desktop` OAuth handoff serves the
   old desktop app only.** `web/src/proxy.ts` serves `.desktop` state
   callbacks from `/oauth/desktop-handoff`, and
   `web/src/lib/oauth/desktopCallback.ts` holds the path allowlist. The earlier
   desktop app (before this native app) opened these callbacks through
   `onyx://oauth-callback`. Installs of it stay in use until users upgrade, so
   keep the handoff page working for them.
5. `widget-credential-public` **A widget credential is visible to anyone who
   can read the page.** The API key sits in an HTML attribute, or, for a
   self-hosted build, in the bundle (`widget/vite.config.ts` `define`). The
   widget keeps it in memory and never writes it to `sessionStorage`. Keep it
   that way, and tell integrators to use a scoped key.
6. `widget-transcript-scoped-by-identity` **The stored widget transcript is
   scoped by credential identity.**
   `widget/src/config/config.ts:deriveCredentialIdentity` uses the JWT `sub` or
   `email`, else a shared value. `widget/src/utils/storage.ts:loadSession`
   drops a session for another identity. A JWT with neither claim falls back
   to the shared value, so a second such visitor in the same tab can restore
   the transcript of the first. `saveSession` leaves out the approval cards
   of VM command app requests (`expires_at` set): they show the request's path
   and body, and scripts of the host page can read `sessionStorage`.
7. `widget-reset-cancels-send` **`resetConversation` must cancel a send at
   every stage.** The admin guide tells host pages to call it on sign-out or an
   account change, so a send that survives a reset shows the previous user's
   response to the next user in the same tab.
   `widget/src/widget.ts:OnyxChatWidget.sendMessage` creates its
   `AbortController` before the first await, and checks for an abort after
   each await and for each packet. Its `finally` clears shared state only when
   `this.abortController` is still its own controller, so a stale send cannot
   clear the state of a newer send. Keep all three when you add an await or a
   new step to a send.
8. `widget-ignores-unknown-packets` **The widget stream fails only on a
   malformed line, a line with no `obj`, or an `error` packet.**
   `widget/src/services/api-service.ts:parseSSEStream` throws on a line that
   does not parse. `widget/src/services/stream-parser.ts:processPacket` throws
   on a packet with no `obj` or no `type`, and on an `error` packet. It
   ignores an unknown packet type. A new backend packet therefore does not
   break the widget, but it shows nothing until `processPacket` handles it.
   A new line shape without `obj`, or a new use of the `error` packet, ends
   the send.
9. `widget-bundle-outlives-backend` **A deployed widget bundle outlives the
   backend version it was built for.** Customer sites keep the old widget
   bundle. A change to the request shape of `create-chat-session` or
   `send-chat-message`, or to an existing packet, breaks those embeds with no
   version check. Treat the attributes on `<onyx-chat-widget>` as a public API
   for the same reason.
10. `widget-passthrough-single-tenant` **Widget passthrough needs a
   single-tenant deployment.** On cloud the tenant comes from the credential
   (`ee/onyx/server/middleware/tenant_tracking.py:_get_tenant_id_from_request`),
   and an external IdP token carries none.
11. `extension-postmessage-origin-locked` **Extension `postMessage` channels
   are origin-locked both ways.**
   `extensions/chrome/src/pages/panel.js:handleMessage` accepts a message only
   from the window of its own iframe and from `getIframeOrigin()`.
   `extensions/chrome/src/pages/onyx_home.js` checks `getOnyxOrigin`. Neither
   falls back to `"*"`. The new-tab messages `PREFERENCES_UPDATED` and
   `LOAD_NEW_PAGE` have no sender in the web app, so the origin check is their
   only guard. A failed check must reject the message.
12. `widget-send-waits-for-idle` **The end of the stream does not enable
    Send.** `widget/src/widget.ts:OnyxChatWidget.sendMessage` polls
    `widget/src/services/api-service.ts:ApiService.waitForSessionIdle` before a
    send to an existing session. After every send, `OnyxChatWidget.resumeStream`
    polls it again when the stream stops, because the server can still save the
    turn after the stream ends. A stop for decisions or answers
    (`awaiting_user`) is the exception: the response is suspended, and the
    server refuses a send with 409 `APPROVAL_PENDING`. While a question
    waits, the widget posts the text to the answers route instead. Failed polls retry and keep
    Send disabled; there is no overall deadline. A 403 or 404, a 405, or three
    401s in a row end the wait with an error, and none counts as idle. A
    backend without the status route answers 404, so a new bundle on an older
    server shows "no longer available" after the first answer
    ([[#widget-bundle-outlives-backend]]).
13. `test-panel-signin-before-narrowing-hosts` **Test sign-in in the side panel
    before you narrow `<all_urls>`.** `extensions/chrome/manifest.json`
    requests `<all_urls>` host access and injects the selection icon on every
    page. The host grant may also be what lets the panel iframe send its
    auth cookie (Known issues).
14. `chrome-input-waits-on-dialogs` **CDP input blocks while a page dialog
    is open.** `extensions/chrome/src/browser/driver.js:input` also ends when a dialog opens; otherwise a
    click that opens `confirm()` holds the command queue until its deadline.
15. `desktop-window-commands-async` **A desktop command that can open a window
    must be `async`.** Tauri runs a sync command on the main thread inside the
    WebView2 message handler. A window built there deadlocks on Windows: the
    new window stays blank and the app stops. macOS and Linux do not show it.
    `desktop/src-tauri/src/commands.rs:commands_that_open_windows_are_async`
    fails for a sync command that calls a window-opening helper. Add a new
    helper of that kind to its `OPENS_WINDOWS` list.

---

## Known issues

- **The extension has no tests, build, type check or lint.** The widget tests
  cover session readiness, failed drafts, tool approvals and questions.
- **`<all_urls>` is broader than the features need.** Only the selection icon
  and tab reading need page access. Open question: the host grant may also be
  what lets the panel iframe send its `SameSite=Lax` auth cookie, because
  Chrome treats a request from an extension page to a permitted origin as
  same-site. Nobody has tested this. A possible replacement is
  `optional_host_permissions` with a `chrome.permissions.request` for the one
  Onyx origin.
- **The widget treats every server error as fatal and hides its text.** A
  turn-level failure (for example a busy session or a save error) arrives as a
  root `StreamingError` line with no `obj`, so `processPacket` shows
  "Received malformed packet" instead of the server text. A tool failure
  inside a turn arrives as a placed `error` packet
  (`backend/onyx/chat/renderer.py:ToolRenderer.complete`, from tools that set
  `emit_error_packet`, such as image generation). The server continues the
  turn and saves the answer, but the widget stops at that packet with
  "Stream error: undefined", because `exception` is not serialized. A reload
  does not restore the answer, because the widget saves only what it rendered.
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
- `desktop-native-feature` **Add a desktop native feature.** Copy the
  `get_prefs` command in `desktop/src-tauri/src/commands.rs`, and register it
  in the `generate_handler!` list in `desktop/src-tauri/src/main.rs` and in
  `COMMANDS` in `desktop/src-tauri/build.rs`, which generates its
  `allow-<command>` permission. Grant it only to the local window that needs it, in
  `desktop/src-tauri/capabilities/<window>.json`
  ([[#desktop-ipc-local-windows-only]]). A command that opens a window must be
  `async` ([[#desktop-window-commands-async]]). Add a Rust unit test next to
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

- Desktop, from the repository root: `mkdir -p desktop/dist`, then
  `(cd desktop/src-tauri && cargo test --locked && cargo clippy --all-targets --locked -- -D warnings)`
  and `(cd desktop && bun run typecheck)`. Tests sit in `#[cfg(test)]` modules
  next to the code. `.github/workflows/desktop.yml` runs the same checks on
  macOS, Windows and Linux and builds unsigned installers. On macOS,
  `desktop/README.md` describes the QA harness (`desktop/src-tauri/src/qa.rs`).
- Widget: `cd widget && bun run type-check && bun run test` (tests in
  `widget/tests/`, also run by `.github/workflows/pr-quality-checks.yml`). By hand, send a message, reload,
  and confirm the transcript returns.
- Extension: by hand, select text on a page and confirm the panel opens with
  it as the prompt. Try `onyx <query>` in the address bar.
