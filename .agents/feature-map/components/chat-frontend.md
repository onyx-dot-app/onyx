# Chat Frontend

> The web chat at `/app`: it sends a turn, reads the packet stream, keeps each
> session's message tree in a client store, and renders timeline steps and the
> answer. It also drives the actions that change the saved conversation, and
> owns the development proxy that forwards `/api` to the backend.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

- **A new user meets first-run onboarding** on the chat page. A user with no
  name gives one. An admin also connects an LLM provider, then sees optional
  setup cards and a final step. The chat input stays locked until the optional
  setup step. An admin who leaves part way resumes at the saved step, or at the
  optional setup step when the required steps are done. Finishing or hiding
  the steps, or sending a message, ends onboarding in that browser.
- **A user sends a message** and watches it work: reasoning, search and other
  tool steps appear as a timeline, then the answer streams with citation chips.
  The user can stop at any time. The partial answer stays, marked as stopped.
- **A user types while an answer streams.** The message joins a short queue
  and sends by itself when the answer has finished drawing on screen.
- **A user edits or regenerates** an earlier message. A switcher then moves
  between the versions, and the rest of the chat follows the chosen one. A
  reload shows the same version.
- **A user sends one message to several models** and sees the answers side by
  side. They can pick one. If they send a follow-up without a pick, the chat
  continues from the answer they were looking at.
- **A user attaches files** by drag and drop, paste or the input bar. If the
  active model has no vision support, an upload that contains an image is
  refused with a message, and none of its files attach.
- **A user reloads during an answer.** With one model, the answer keeps
  streaming from where the server is. With several models, each answer shows
  its saved placeholder text until the user reloads after the run ends.
- **A user rates, copies or shares an answer.** Copy turns markdown tables into
  tab-separated text so a spreadsheet keeps the columns. A share link opens a
  read-only copy. The page needs a session, so a visitor with none goes to
  sign-in.
- **A user in incognito** cannot turn incognito on or off once the session
  exists, and answers show no rating buttons. Leaving the chat or closing the
  tab ends it. If an explicit exit fails, an error shows and the user stays in
  the chat to retry.
- **When a send fails**, an error message replaces the answer. A usage limit
  shows a banner with the reset time and no retry
  ([[rate-and-usage-limits]]).
- **A developer who runs the web server in development** reaches the backend
  at `/api` on the web origin, streams included. A production web server
  answers that route with a 404 and a message that nginx must serve `/api`
  ([[#dev-api-proxy-only]]).

---

## Scope

This component owns:

- the `/app` page and its routes;
- the chat controllers: send, session load, feedback and multi-model;
- the per-session client store and the message tree;
- the client services that call the chat endpoints, and the stream reader;
- packet grouping and the timeline and answer renderers;
- the chat sections: input bar, sidebar, document sidebar and model selector;
- the incognito controls in the app chrome;
- first-run onboarding on the chat page, which uses the provider setup forms
  of [[llm-providers]];
- the development `/api` proxy route.

It shares the file preview renderers with [[craft-frontend]].

Neighbours own the rest. [[streaming-protocol]] owns the packet vocabulary,
the enum mirrors, line framing and heartbeats. [[citations]] owns marker
resolution and the partial-link hiding inside the answer. [[core-chat-loop]]
owns the send, stop and resume endpoints, and [[chat-persistence]] the server
tree and replay. [[agents-personas]] owns `/app/agents`. [[plugins]] owns the
plugins page and the tools popover, and [[mcp-and-custom-tools]] the MCP
connection prompt. [[desktop-widget-extensions]] owns the Chrome extension's
new-tab and side-panel pages and framed sign-in.

---

## Architecture

Component, styling, i18n and data fetching rules for this code are in
`web/AGENTS.md`. This document does not repeat them.

```
AppInputBar -> useChatController.onSubmit           web/src/hooks/useChatController.ts
  implicit multi-model pick (if needed)             PUT set-preferred-response
  optimistic user + assistant nodes in the tree
  updateCurrentMessageFIFO                          app/app/services/currentMessageFIFO.ts
    sendMessage -> handleSSEStream -> withoutHeartbeats   app/app/services/lib.tsx
  drain loop, one store update per animation frame
    updateSessionMessageTree(frozenSessionId, ...)
AgentMessage -> usePacketProcessor -> processPackets   timeline/hooks/packetProcessor.ts
  groups by (turn_index, tab_index); builds citationMap, documentMap, stop state
  tool groups -> timeline steps;  display groups -> answer
  RendererComponent -> findRenderer                 renderMessageComponent.tsx
```

**The store.** `web/src/app/app/stores/useChatSessionStore.ts` holds a `Map`
of session data keyed by session id, plus `currentSessionId`. Each session has
its own message tree, chat state, `streamId`, `AbortController` and message
queue. A stream keeps writing to the session that started it
(`frozenSessionId`), so a user can switch chats while one streams.

**The message tree.** `app/app/services/messageTree.ts` mirrors the server tree:
nodes keyed by `nodeId`, each with `latestChildNodeId`.
`getLatestMessageChain` walks it to get what the page shows. On load,
`app/app/services/lib.tsx:processRawChatHistory` builds the tree from the
session response and its replay packets ([[chat-persistence]]).

**Packet processing.** `processPackets` is incremental. It processes only
packets past `nextPacketIndex` and keeps its state in a ref. It decides each
group's kind from the group's first packet: a tool packet (`isToolPacket`)
makes a timeline step, and `MESSAGE_START` or `IMAGE_GENERATION_TOOL_START`
makes an answer group. `buildGroupsFromKeys` drops a group with no packet in
`CONTENT_PACKET_TYPES_SET`. Citation and stop packets update state instead of
making their own step. A group that mixes answer text and generated images
renders through `MixedContentHandler`.

**Resume.** `web/src/hooks/useChatSessionController.ts` loads the session.
When the response has `current_stream` and that id is an assistant node,
`resumeInFlightRun` replays the stream buffer from cursor 0, flushes at most
every 100 ms, then refetches the session to settle text and citations. It
skips lines with no `obj` ([[streaming-protocol]]).

**First-run onboarding.** `AppPage` renders
`web/src/lib/onboarding/components/OnboardingFlow.tsx`, and
`web/src/lib/onboarding/hooks.ts:useShowOnboarding` decides whether it shows.
The step order is in `web/src/lib/onboarding/constants.ts:STEP_CONFIG`.
Dismissal and an admin's saved step live in `localStorage`, keyed by user id,
so another browser starts again. The input lock is a comparison against
`STEP_CONFIG[OnboardingStep.OptionalSetup].index` in the input bar's
`disabled` prop in `AppPage`; a change to the step order must keep it.

**Forced tools.** At send time `onSubmit` filters the forced tool through
`web/src/lib/plugins/chat.ts:effectiveChatForcedToolId`. The stored per-chat
choice does not change. [[plugins]] owns the rule.

**The development `/api` proxy.**
`web/src/app/api/[...path]/route.ts` forwards every method under `/api` to
`INTERNAL_URL` with the `/api` prefix removed. It passes the request body as a
stream, forwards each `set-cookie` header, and returns redirects to the
browser. For a streamed response it turns off caching and proxy buffering, so
packets reach the client as they arrive. In development, `DEBUG_AUTH_COOKIE`
adds an auth cookie so a local web server can call a remote backend. More
specific routes under `web/src/app/api/` take precedence over this one.

---

## Contracts and traps

1. `packet-list-append-only` **A message's packet list is append-only.**
   `app/app/message/messageComponents/timeline/hooks/packetProcessor.ts:processPackets`
   resets only when the list gets shorter. Otherwise it
   processes only the packets past `nextPacketIndex`, so a list replaced with
   one of the same or greater length keeps the state built from the old
   packets. `app/app/message/messageComponents/AgentMessage.tsx:AgentMessage`
   memoizes on `packetCount`, not on the array. Update both together, as
   `web/src/hooks/useChatSessionController.ts:resumeInFlightRun` does.
2. `packet-type-web-sets` **A new packet type needs more than an enum entry.**
   [[streaming-protocol]] lists the hand-mirrored places, including
   `findRenderer`. The web client keeps more hand-written sets that switch on
   `PacketType`, such as `app/app/services/packetUtils.ts:isToolPacket` and
   `app/app/message/messageComponents/timeline/hooks/packetProcessor.ts:CONTENT_PACKET_TYPES_SET`.
   To find all of them, run
   `git grep -l 'PacketType.FILE_READER_START' web/src`. Run it again for a
   type that behaves like the new one. Add the new type where a similar type
   appears. If an entry is missing, the packet renders as
   nothing, or as a generic step, and nothing logs an error
   (`RendererComponent` returns an empty block).
3. `background-keeps-current-session` **Only the active view may move
   `currentSessionId`.** `updateSessionAndMessageTree` in
   `web/src/app/app/stores/useChatSessionStore.ts` sets `currentSessionId`.
   Code that runs in the background, such as a resume tail, must check that
   its session is still current or use `updateSessionMessageTree`. Otherwise
   it takes over the chat the user moved to, and their next send goes to the
   wrong session.
4. `stop-does-not-abort-fetch` **Stop does not abort the fetch.**
   `stopGenerating` calls `POST /chat/stop-chat-session/{id}` with the
   session's `streamId` and sets the chat state to `input`. The stream ends
   when the backend sends its stop packet. `streamId` is the assistant message
   id, or the user message id for a multi-model turn. The session's
   `AbortController` fires only when the route changes (the cleanup effect in
   `web/src/hooks/useChatController.ts`).
5. `fifo-abort-records-error` **The FIFO's own abort records an error.** In
   `app/app/services/currentMessageFIFO.ts:updateCurrentMessageFIFO`, the loop
   throws `new Error("AbortError")` when the signal is set. Its `name` is
   `"Error"`, so it lands in `stack.error` and the controller renders an error
   node. Only the `DOMException` from an aborted `fetch` is a clean stop.
6. `queue-needs-two-flags` **The queue needs two flags.**
   `sections/input/AppInputBar.tsx:AppInputBar` sends
   the next queued message when the chat state is `input` and
   `latestMessageRenderComplete` is true. A path that ends a stream without
   the text renderer finishing, such as stop or an error, must set
   `latestMessageRenderComplete` itself. If it does not, the queue stalls with
   no error.
7. `branch-switch-reaches-server` **A branch switch must reach the server.**
   `web/src/hooks/useChatSessionController.ts:onMessageSelection` updates the
   local tree and calls `app/app/services/lib.tsx:patchMessageToBeLatest`. The
   backend accepts a send only when its parent is on the server's active branch
   ([[chat-persistence#send-parent-on-active-branch]]), and a reload shows the
   server's branch. A UI path that changes `latestChildNodeId` without the PUT
   breaks both.
8. `implicit-pick-revertible` **An implicit model pick must be revertible.** A
   follow-up to an unpicked multi-model turn picks the most visible answer,
   applies it locally and PUTs it. If the PUT fails, the local pick is
   reverted, unless a newer explicit pick replaced it. Keep that guard in
   `web/src/hooks/useChatController.ts:onSubmit`.
9. `usage-limit-is-packet` **A 429 usage limit is a packet, not a throw.**
   `app/app/services/lib.tsx:sendMessage` turns it into a `StreamingError` with
   `is_retryable: false`, so the banner renders through the normal error path. The response shape is
   owned by [[rate-and-usage-limits]].
10. `incognito-toggle-locks` **The incognito toggle locks once a session id
    exists.** The mode is pinned when the session is created, so an empty
    session that is reused keeps its mode.
    `app/app/services/lib.tsx:createChatSession` throws when an
    incognito create comes back without `incognito: true`, because an old API
    server pod in a rolling deploy does not pin the mode. Leaving an incognito session calls
    `endIncognitoSession`; closing the tab sends a `sendBeacon` on `pagehide`.
    When both fail, the server sweep cleans up ([[chat-persistence]]).
11. `chat-url-drops-ids` **`app/app/services/lib.tsx:buildChatUrl` drops
    `PARAMS_TO_SKIP`.** Chat, agent and project ids are never carried over
    from the old URL. `views/AppPage.tsx:AppPage` removes
    `projectId` when `agentId` is also present, because an agent pick replaces
    project context.
12. `dev-api-proxy-only` **The `/api` route handler serves development only.**
    `handleRequest` in `web/src/app/api/[...path]/route.ts` returns 404 unless
    `NODE_ENV` is `development` or `OVERRIDE_API_PRODUCTION` is `true` (for
    preview environments). In production, nginx strips `/api` and forwards to
    the API server (`deployment/data/nginx/app.conf.template`). A fix to
    streaming, cookies or redirects in this file does not reach production;
    behaviour that works through it in development must also hold behind
    nginx.
13. `group-packets-false-lead` **False lead:
    `app/app/services/packetUtils.ts:groupPacketsByTurnIndex` has no
    production caller.** Grouping happens in `processPackets`
    ([[#packet-list-append-only]]).

---

## Decisions

- **Packets pass through a FIFO and flush once per animation frame.** The
  network delivers many small chunks. A React update per chunk would stall the
  page, so the drain loop in `onSubmit` batches them.
- **Each session has its own store entry.** A stream keeps running while the
  user reads another chat, and its result is there when they return.
- **The page-level `Dropzone` sets `noClick` and `noPaste`.** The input bar
  handles click and paste uploads. Without `noPaste`, one paste attaches the
  file twice.

---

## Known issues

- **Resume covers one model only.** For a multi-model turn, `current_stream`
  is the user message id, so `resumeInFlightRun` skips it. Nothing refetches
  the session, so the reserved rows' placeholder text ("Response was
  terminated prior to completion") shows until the user reloads after the run
  ends.
- **A fast send after a branch switch can race.** `patchMessageToBeLatest` is
  not awaited. A send that reaches the server first can fail with "not on the
  latest mainline". This is inferred from the code, not seen in a test.
- **Auto-naming can run twice.** `handleNewSessionNaming` names a new session
  after its first answer, and the session controller names an untitled session
  with two or more messages on load. A quick reload can trigger both.

---

## Dependencies

- [[core-chat-loop]]: the send, stop and resume endpoints.
- [[streaming-protocol]]: the packets this component parses and renders.
- [[chat-persistence]]: session reads, replay packets, branch and pick
  endpoints, feedback, sharing and incognito teardown.
- [[citations]]: marker resolution inside the answer.
- [[agents-personas]]: the active agent from `agentId`.
- [[projects]]: `ProjectsProvider` and project context.
- [[llm-providers]]: `useLlmManager` and model capabilities.
- [[file-store-and-user-files]]: `beginUpload` and attached files.
- [[voice]]: `VoiceModeProvider` wraps the layout.
- [[plugins]]: the forced-tool rule and the member plugins sent with a turn.
- [[rate-and-usage-limits]]: the 429 usage-limit response shape.

---

## Recipes

- `packet-type-renderer` **A packet type.** Copy how `FILE_READER_START` is
  handled; list the web sets with the `git grep` in
  [[#packet-type-web-sets]]. Add a renderer to `findRenderer`. Cover it with a
  mocked stream ([[#mock-stream-test]]).
- `message-action` **A message action.** Copy regenerate, which routes through `onSubmit`
  with `messageIdToResend`, if the action sends a turn. Otherwise copy
  `patchMessageToBeLatest`; list the client calls in
  `app/app/services/lib.tsx`. Update the tree in the store, and check that a
  reload shows the same result.
- `query-parameter` **A query parameter.** Copy `PROJECT_ID`; list the set in
  `app/app/services/searchParams.ts:SEARCH_PARAM_NAMES`. Add it to
  `PARAMS_TO_SKIP` if it must not survive navigation
  ([[#chat-url-drops-ids]]).
- `mock-stream-test` **Test a renderer with no LLM.** Copy a spec in `web/tests/e2e/chat/` that
  calls `mockChatEndpoint`. `web/tests/e2e/utils/chatMock.ts` builds a stream
  by hand (`buildMockStream`, `buildMockSearchStream`), and
  `web/tests/e2e/utils/chatStream.ts` parses a captured stream for
  assertions.
- `remote-backend` **Run the web app against another backend.** In development, set
  `INTERNAL_URL` to the backend origin. For a backend that needs a session,
  copy the auth cookie value from that site into `DEBUG_AUTH_COOKIE`. The
  proxy adds it to each request ([[#dev-api-proxy-only]]).

---

## Verification

- Playwright: the specs in `web/tests/e2e/chat/`, with the stream mocks in
  `web/tests/e2e/utils/`.
- Jest: the `*.test.ts` and `*.test.tsx` files beside the code in
  `web/src/app/app/`.
- By hand: force a tool call, edit, switch back, stop mid-answer, and reload.
  Citations resolve, the branch holds, and the partial answer stays.
