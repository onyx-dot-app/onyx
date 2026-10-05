# Chat Frontend

> The chat user interface. It takes the packet stream the [[core-chat-loop]]
> emits and turns it into a scrollable conversation: routes, the streaming
> client, packet-to-component rendering, state, message actions, uploads, and
> the agent/model pickers.

**Domain:** core-loop
**Edition:** CE
**Owns:**
`web/src/app/app/` (`page.tsx`, `layout.tsx`, `agents/`, `shared/[chatId]/`, `settings/`,
`services/`, `stores/`, `message/`, `components/`), `web/src/views/AppPage.tsx`,
`web/src/hooks/useChatController.ts`, `useChatSessionController.ts`,
`useFeedbackController.ts`, `useChatSessions.ts`, `useMultiModelChat.ts`,
`web/src/lib/search/streamingUtils.ts`, `web/src/sections/sidebar/`, `sections/input/`,
`sections/model-selector/`, `sections/document-sidebar/`, `sections/modals/`

**Read first:** `web/AGENTS.md`. Its component rules gate every PR in this component,
and §5 below restates them.

---

## 1. What the user experiences

The user lands on `/app` and either sees a welcome screen, an ongoing conversation, or a
project view, depending on what is in the URL. They type a message, watch the assistant
think, search, and answer with live-updating text and citations, and can stop generation
at any time. They can edit or regenerate a past message, branch between alternate
answers, copy a response, and like or dislike it. They can send one message to two or
three models at once and pick a favorite. They can drag a file onto the page or paste an
image to attach it, pick a different agent or model before sending, and share a
conversation as a public read-only link. If they reload mid-answer, the answer keeps
streaming instead of restarting.

---

## 2. Surfaces

### Routes (`web/src/app/app/`)

| Route | File | Notes |
|---|---|---|
| `/app` | `page.tsx` → `AppPage.tsx` (`views/AppPage.tsx:AppPage`) | The single chat surface. Renders the welcome screen, a conversation, or a project view depending on client state and query params, not separate routes. `page.tsx` reads `firstMessage` from the search params and redirects via `defaultAgentRedirectTarget` (`lib/app/utils`) before rendering. |
| `/app/agents`, `/app/agents/create`, `/app/agents/edit/[id]` | `agents/page.tsx`, `agents/create/`, `agents/edit/[id]/` | Agent management. See [[agents-personas]]. |
| `/app/shared/[chatId]` | `shared/[chatId]/page.tsx` → `SharedChatDisplay.tsx` | Public, read-only. Server-fetches with `fetchSS("/chat/get-chat-session/{id}?is_shared=True")` (`shared/[chatId]/page.tsx:getSharedChat`) and renders `SharedChatDisplay`. Still requires `requireAuth()`; "shared" means shareable, not unauthenticated. |
| `/app/settings/*` | `settings/{accounts-access,chat-preferences,connectors,general,llm-gateway,usage}/` | Per-user settings pages, not part of the turn loop. |

`layout.tsx` (`app/app/layout.tsx:Layout`) wraps every `/app/*` route with `ProjectsProvider`,
`VoiceModeProvider`, `AppSidebar`, and `AppChrome`, and calls `requireAuth()` server-side.

### Query params (`services/searchParams.ts:SEARCH_PARAM_NAMES`)

`chatId`, `searchId`, `agentId`, `projectId`, `allMyDocuments`, plus per-send overrides
(`temperature`, `model-version`, `system-prompt`, `structured-model`), message seeding
(`user-prompt`, `submit-on-load`, `title`, `files`, `seeded`, `send-on-load`), and
`skip-reload` (suppresses a page reload right after the first message in a new session).
`buildChatUrl` (`services/lib.tsx:buildChatUrl`) is the single place that assembles a
chat URL; it drops `chatId`/`agentId`/`projectId`/`submit-on-load`/`user-prompt`/`title`
from whatever params already exist (`PARAMS_TO_SKIP`) so they are never accidentally
carried over from the previous URL. `agentId` and `projectId` are mutually exclusive: if
both appear, `AppPage` strips `projectId` (`views/AppPage.tsx`, the effect that calls
`router.replace` when both params are present).

### The dev proxy (`web/src/app/api/[...path]/route.ts`)

`handleRequest` forwards every method to `${INTERNAL_URL}/${path}` and pipes the response
back, including SSE bodies (it disables buffering and forwards `Transfer-Encoding` when
the response is chunked or `Content-Type` contains `stream`). It refuses to run unless
`NODE_ENV === "development"` or `OVERRIDE_API_PRODUCTION === "true"`
(`route.ts:handleRequest`). In production, `/api/...` is served by something else (for
example nginx); this file is not on that path.

### HTTP endpoints this component calls (owned by [[core-chat-loop]] and [[chat-persistence]])

| Endpoint | Called from |
|---|---|
| `POST /api/chat/send-chat-message` | `services/lib.tsx:sendMessage` |
| `GET /api/chat/chat-session/{id}/resume-stream?cursor=N` | `services/lib.tsx:resumeStream`, from `useChatSessionController.ts` |
| `POST /api/chat/stop-chat-session/{id}` | `hooks/useChatController.ts:stopChatSession` |
| `POST /api/chat/create-chat-session` | `services/lib.tsx:createChatSession` |
| `PUT /api/chat/rename-chat-session` | `services/lib.tsx:renameChatSession`, `nameChatSession` |
| `DELETE /api/chat/delete-chat-session/{id}`, `/api/chat/delete-all-chat-sessions` | `services/lib.tsx` |
| `PUT /api/chat/set-message-as-latest` | `services/lib.tsx:patchMessageToBeLatest` |
| `PUT /api/chat/set-preferred-response` | `services/lib.tsx:setPreferredResponse` |
| `POST/DELETE /api/chat/create-chat-message-feedback`, `/api/chat/remove-chat-message-feedback` | `services/lib.tsx:handleChatFeedback`, `removeChatFeedback` via `hooks/useFeedbackController.ts` |
| `PATCH /api/chat/chat-session/{id}` (`sharing_status`) | `sections/modals/ShareChatSessionModal.tsx` |
| `POST /api/chat/end-incognito-session/{id}` | `services/lib.tsx:endIncognitoSession`, from `views/AppPage.tsx` |
| `POST /api/chat/seed-chat-session-from-slack` | `hooks/useChatController.ts` |
| `POST /api/user/projects/file/upload` | `lib/projects/providers.tsx:beginUpload`, see [[file-store-and-user-files]] |

---

## 3. Data model

No database tables here; the state is client-side. [[chat-persistence]] owns the rows
this component reads and writes to over HTTP.

### The Zustand store (`stores/useChatSessionStore.ts`)

`useChatSessionStore` holds a `Map<string, ChatSessionData>` keyed by chat session id,
plus `currentSessionId`. `ChatSessionData` (`useChatSessionStore.ts`) carries, per
session: `messageTree`, `chatState` (`"input" | "uploading" | "streaming" | ...`),
`regenerationState`, `abortController`, `canContinue`, `queuedMessages`,
`selectedNodeIdForDocDisplay`, `documentSidebarVisible`, `chatSessionSharedStatus`,
`incognito`, `latestMessageRenderComplete`, `isStreamDraining`, and loading/error flags
(`isFetchingChatMessages`, `uncaughtError`, `loadingError`, `isReady`). The store exports
many selector hooks (`useCurrentChatState`, `useCurrentMessageTree`,
`useCurrentMessageHistory`, `useIsReady`, `useDocumentSidebarVisible`,
`useCurrentIsStreamDraining`, ...) so components subscribe to one field instead of the
whole session. Every session starts from `createInitialSessionData`
(`useChatSessionStore.ts`), which seeds `messageTree` as an empty `Map` and `chatState`
as `"input"`.

### The message tree (`services/messageTree.ts`)

`MessageTreeState = Map<number, Message>`, keyed by `nodeId` (`messageTree.ts`). Each
`Message` (`app/app/interfaces.ts`) carries `parentNodeId`, `childrenNodeIds`,
`latestChildNodeId`, and its own `packets: Packet[]`. `getLatestMessageChain`
(`messageTree.ts:getLatestMessageChain`) walks `latestChildNodeId` from the root to
produce the linear history the UI renders; editing or regenerating a message creates a
sibling node and repoints `latestChildNodeId`, so branch switching
(`patchMessageToBeLatest`, `messageTree.ts:setMessageAsLatest`) is a pure client-side
walk of the existing tree, no refetch. `upsertMessages` merges new or updated nodes into
the tree immutably.

### The packet FIFO (`services/currentMessageFIFO.ts`)

`CurrentMessageFIFO` is a plain array-backed queue (`push`/`nextPacket`/`isEmpty`) plus
`isComplete` and `error` flags. `updateCurrentMessageFIFO` drives `sendMessage` and
pushes every yielded packet onto the queue, so the consumer (`useChatController.ts`) can
drain it on its own animation cadence instead of reacting to every network chunk
directly. An `AbortError` is treated as a clean stop; any other thrown error is recorded
in `stack.error`.

### Packets (`services/streamingModels.ts`)

`Packet = { placement: Placement; obj: ObjTypes }`. `PacketType` (`streamingModels.ts`)
enumerates every wire type; `ObjTypes` is the discriminated union of every packet body.
This enum **must** match the Python `PacketType` the backend emits; see §5.

---

## 4. How it works

### 4.1 Sending a message

```
AppInputBar (sections/input/)
  └─ useChatController.onSubmit          hooks/useChatController.ts
      ├─ createChatSession (if new)      services/lib.tsx
      ├─ updateCurrentMessageFIFO        services/currentMessageFIFO.ts
      │   └─ sendMessage (async generator) services/lib.tsx
      │       └─ handleSSEStream         lib/search/streamingUtils.ts
      └─ drain loop → useChatSessionStore.updateSessionAndMessageTree
```

`sendMessage` (`services/lib.tsx:sendMessage`) POSTs the turn payload to
`/api/chat/send-chat-message` and yields packets from the response body. A 429 with
`error_code === RATE_LIMITED_ERROR_CODE` is converted into a synthetic `StreamingError`
packet instead of a thrown error, so the UI renders the usage-limit banner through the
normal packet path (`services/lib.tsx:sendMessage`, the `response.status === 429` branch).
`withoutHeartbeats` (`services/lib.tsx`) filters `chat_heartbeat` packets before they
reach the FIFO.

### 4.2 Parsing the stream (`lib/search/streamingUtils.ts:handleSSEStream`)

Reads the response body with a `ReadableStreamDefaultReader`, decodes it, and splits the
buffer on `\n`. Each line is `JSON.parse`d individually. If a line fails to parse, a
regex fallback (`/\{[^{}]*\}/g`) extracts and parses any complete `{...}` object
substrings out of that line (`streamingUtils.ts:handleSSEStream`). This is a best-effort
recovery for a line that arrived split across two chunks; it is not a full NDJSON parser
and can silently drop or mis-parse a malformed line. See §9.

### 4.3 Resuming a stream

`useChatSessionController.ts` calls `resumeStream(chatSessionId, cursor)`
(`services/lib.tsx:resumeStream`) against `GET /chat/chat-session/{id}/resume-stream`,
which replays the durable buffer from `cursor` and then tails the live stream (owned by
[[core-chat-loop]], §4.6 of that document). A 404 means nothing to resume; the caller
falls back to the persisted session state instead of throwing.

### 4.4 Rendering: packets to components

`RendererComponent` (`message/messageComponents/renderMessageComponent.tsx`) is the
top-level switch. Packets are grouped by `(turn_index, tab_index)` first
(`services/packetUtils.ts:groupPacketsByTurnIndex`), then each group is handed to
`findRenderer` (`renderMessageComponent.tsx:findRenderer`), which inspects the packet
types present and returns one renderer:

| Packet family | Renderer |
|---|---|
| `message_start`/`message_delta`/`message_end` | `MessageTextRenderer` (`messageComponents/renderers/MessageTextRenderer.tsx`) |
| `deep_research_plan_start`/`_delta` | `DeepResearchPlanRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/deepresearch/`) |
| `research_agent_start`, `intermediate_report_*` | `ResearchAgentRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/deepresearch/`) |
| Coding-agent and bash-tool packets (`isCodingAgentPackets`, `timeline/packetHelpers.ts`) | `CodingAgentRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/code/`) |
| `search_tool_start` with `is_internet_search: true` | `WebSearchToolRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/search/`) |
| `search_tool_start` with `is_internet_search` falsy | `InternalSearchToolRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/search/`) |
| `image_generation_start` | `ImageToolRenderer` (`messageComponents/renderers/ImageToolRenderer.tsx`) |
| `python_tool_start`, or `tool_call_argument_delta` for a code-interpreter tool type | `PythonToolRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/code/`) |
| `file_reader_start` | `FileReaderToolRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/filereader/`) |
| `custom_tool_start` | `CustomToolRenderer` (`messageComponents/renderers/CustomToolRenderer.tsx`) |
| `open_url_start` | `FetchToolRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/fetch/`) |
| `memory_tool_start`/`memory_tool_no_access` | `MemoryToolRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/memory/`) |
| `reasoning_start`/`_delta`, or a bare `section_end`/`error` | `ReasoningRenderer` (`web/src/app/app/message/messageComponents/timeline/renderers/reasoning/`) |
| `citation_info`, `stop` | **No renderer.** See below. |

`findRenderer` checks in a fixed order (chat text, then deep research, then research
agent, then coding agent, then the remaining tools, then reasoning last), because a group
can contain more than one packet family (for example a deep-research group mixes plan,
reasoning, and fetch packets) and the first true predicate wins
(`renderMessageComponent.tsx:findRenderer`). `RendererComponent` special-cases a group
that mixes chat text and image-generation packets via `MixedContentHandler`, which
renders `MessageTextRenderer` and `ImageToolRenderer` together so a text-then-image
answer is not split into two blocks.

Citation packets carry no renderer of their own: `getCitations`
(`services/packetUtils.ts:getCitations`) folds every `citation_info` packet in a message
into a `citation_num → document_id` map, which `MemoizedAnchor` resolves at render time
(§4.5). `stop` packets are not rendered either; they are threaded through renderer props
as `stopPacketSeen: boolean` and `stopReason?: StopReason`
(`renderMessageComponent.tsx:RendererComponentProps`) so a renderer can show "stopped by
user" without a dedicated component.

Packets are grouped into timeline blocks by `usePacketProcessor` /
`packetProcessor` (`message/messageComponents/timeline/hooks/usePacketProcessor.ts`,
`packetProcessor.ts`), upstream of `RendererComponent`.

### 4.5 Citations and markdown

`MemoizedAnchor` (`message/MemoizedTextComponents.tsx:MemoizedAnchor`) is the
`react-markdown` anchor renderer. For a link whose text matches `[D<n>]` or `[Q<n>]`, it
looks up `citations[n]` to get a `document_id`, then finds that document in the `docs`
array passed down from `FullChatState`. If no document (or sub-question) resolves, it
renders `<></>`, nothing, rather than the raw markdown link
(`MemoizedTextComponents.tsx:MemoizedAnchor`, the "Citation not resolved yet" branch).
This is deliberate: during streaming, a citation number can arrive before its
`citation_info` packet.

`processContent` (`message/messageComponents/markdownUtils.tsx:processContent`) runs
before every markdown render and strips trailing incomplete citation markup
(`/\[\[\d+\]\]\([^)]*$/` and a lone `[[`/`[[N`/`[[N]` at the end) so a citation link never
flashes half-formed while its closing `)` is still in flight. It also escapes an
unclosed trailing `$$` so `remark-math` does not choke on a LaTeX block mid-stream.

### 4.6 Session lifecycle

`createChatSession`, `renameChatSession`, `nameChatSession`, `deleteChatSession`,
`deleteAllChatSessions` all live in `services/lib.tsx`. Auto-naming
(`nameChatSession(chatSessionId)` with `name: null`, which asks the backend to name the
session from the conversation) is triggered from two places:
`useChatController.ts:handleNewSessionNaming` after a brand-new session's first exchange
(with a 200 ms delay to give the backend time to persist the session row), and
`useChatSessionController.ts` on load, if the loaded session has no `description` yet.
Both call `refreshChatSessions()` afterward. See §9 for the double-fire footgun.

Sharing: `ShareChatSessionModal.tsx` calls `PATCH /api/chat/chat-session/{id}` with
`{ sharing_status: "public" | "private" }`. The shareable link is
`${window.location.origin}/app/shared/{id}`.

Incognito: `AppPage.tsx` calls `endIncognitoSession(sessionId)`
(`services/lib.tsx:endIncognitoSession`) whenever `currentChatSessionId` changes away
from a live incognito session, and again on `pagehide` via
`navigator.sendBeacon(`/api/chat/end-incognito-session/${sessionId}`)` since `fetch`
would be cancelled by the unload (`views/AppPage.tsx`, the `pagehide` effect). The
incognito toggle locks (`setIncognitoLocked`) once a session has any message or exists at
all, because the mode is pinned at session creation and cannot be changed mid-session.

### 4.7 Message actions

- **Regenerate and edit** both route through `onSubmit` in `useChatController.ts`: edit
  passes `messageIdToResend` with the new text, regenerate passes a
  `regenerationRequest` that reuses the existing user node and only creates a new
  assistant node (`useChatController.ts`, the `onSubmit` branches on
  `regenerationRequest`).
- **Stop** calls `stopChatSession` (`useChatController.ts:stopChatSession`, `POST
  /api/chat/stop-chat-session/{id}`) **and** aborts the session's local
  `AbortController` (`abortController.abort()` in the store). Both must fire: the server
  call stops the backend turn (see [[core-chat-loop]] §4.6); the local abort stops the
  fetch reader so the UI does not keep waiting on a connection the server may not close
  immediately.
- **Feedback** goes through `useFeedbackController.ts:handleFeedbackChange`: it
  optimistically calls `updateCurrentMessageFeedback` before the request, and rolls back
  to the previous feedback value if the request fails or throws.
- **Copy** is client-only: `getTextContent` (`services/packetUtils.ts:getTextContent`)
  concatenates `message_start`/`message_delta` content, and `copyingUtils.tsx:handleCopy`
  / `copyAll` write it to the clipboard, converting markdown tables to TSV
  (`copyingUtils.tsx:convertMarkdownTablesToTsv`) so a paste into a spreadsheet keeps
  columns.
- **Branch switching** is a pure client-side tree walk:
  `patchMessageToBeLatest` (`services/lib.tsx`) persists the choice server-side via `PUT
  /api/chat/set-message-as-latest`, and `messageTree.ts:setMessageAsLatest` updates the
  local tree's `latestChildNodeId` chain immediately so the UI does not wait on the
  round-trip.
- **`setPreferredResponse`** (`services/lib.tsx:setPreferredResponse`, `PUT
  /api/chat/set-preferred-response`) records which multi-model answer the user picked as
  the winner.

### 4.8 Uploads

`AppPage.tsx` wraps the whole `/app` content area in a `react-dropzone` `<Dropzone>` with
`noClick noPaste` (`views/AppPage.tsx`, around the main content grid). `onDrop` calls
`handleMessageSpecificFileUpload` (`hooks/useChatController.ts`), which checks the
dropped files against the current model's image support
(`modelSupportsImageInput`, `lib/llm/utils`) before uploading, rejecting image files with
a toast if the active model has no vision support. It then calls `beginUpload`
(`lib/projects/providers.tsx:beginUpload`, `POST /api/user/projects/file/upload`, see
[[file-store-and-user-files]]) and appends the results to `currentMessageFiles` via
`ProjectsProvider`.

### 4.9 Pickers

- **Agent**: `useActiveAgent` (`lib/agents/hooks.ts:useActiveAgent`) resolves the active
  agent from the `agentId` query param against the loaded agent list, falling back to the
  default assistant. `AgentButton` (`lib/agents/components/AgentButton.tsx`) is the picker
  UI, used from `AppSidebar.tsx`.
- **Model**: `ModelSelector` (`sections/model-selector/ModelSelector.tsx`) and
  `MultiModelSelector` (`sections/model-selector/MultiModelSelector.tsx`) are backed by
  `useLlmManager` (`lib/hooks`) for the single-model path and `useMultiModelChat`
  (`hooks/useMultiModelChat.ts`) for 2-3 parallel models. `useMultiModelChat` derives the
  displayed single model straight from `llmManager.currentLlm` unless the user has
  explicitly added more than one model (`useMultiModelChat.ts`, `currentLlmModel`
  memo), so it never drifts out of sync with the manager in single-model mode.

---

## 5. Contracts and invariants

### Component rules (`web/AGENTS.md`, verified against source)

These are the rules a reviewer checks on every diff in this component; they are also
enforced by lint (`i18n/no-raw-jsx-text`) and pre-commit (`typescript-check`) where noted.

1. **Component source priority:** `web/lib/opal/src/` (`@opal/*`) first, then
   `web/src/refresh-components/`, then `web/src/sections/`/`web/src/layouts/`. Never
   import from `web/src/components/` (legacy, being deleted); the sole exception is
   `createLogoIcon` in `src/components/icons/icons.tsx`.
2. **No raw `<button>`.** Use `Button` from `@opal/components`.
3. **No raw `<input>`, `<textarea>`, or `<select>`.** Use Opal or refresh-components
   equivalents.
4. **No naked text nodes.** Use `Text` from `@opal/components` with `font` and `color`
   props. `Text` **strips `className`**; a caller that needs layout must wrap it, not
   style it directly (see §9). The boolean-flag API on `refresh-components/texts/Text` is
   deprecated.
5. **Icons only from `@opal/icons`.** Never `lucide-react` or `react-icons`. A missing
   icon is imported from Figma into `lib/opal/src/icons/`, not substituted.
6. **No `dark:` Tailwind modifier.** Design tokens already define both themes; the one
   exception is `createLogoIcon`.
7. **No built-in Tailwind colors** (`bg-gray-100`, `text-blue-600`, ...). Use token
   classes (`text-0X`, `background-neutral-0X`, `background-tint-0X`, `border-0X`,
   `action-selection-0X`, `action-danger-0X`, `status-{info,success,warning,error}-0X`,
   `theme-*`).
8. **`cn()` from `@opal/utils`** for every conditional class name, never a template
   string.
9. **Absolute imports only:** `@/` for `src/`, `@opal/` for Opal. No `../` paths.
10. **Components are `function` declarations**, not arrow functions; the props interface
    lives in the same file as the component.
11. **No hard-coded user-facing strings under `src/`.** Use `useTranslations(...)` /
    `getTranslations(...)`; a raw JSX text node fails the `i18n/no-raw-jsx-text` oxlint
    rule. Add new keys to `web/src/i18n/messages/en.json` and every other locale file.
12. **Data fetching is `useSWR`, client-side, inside the component that needs it**, with
    a loader while pending. Do not fetch at the page top and pass data down.

### Streaming invariants (this component's own)

13. **Every backend packet type needs a renderer, or a matching predicate in
    `findRenderer`, or it silently renders as nothing.** `RendererComponent` falls back to
    `{ icon: null, status: null, content: <></> }` when no renderer matches
    (`renderMessageComponent.tsx:RendererComponent`), so an unhandled packet type does not
    error, it disappears. A new backend packet type is invisible in the UI until
    `findRenderer` and `streamingModels.ts:PacketType` both know about it.
14. **The TypeScript `PacketType` enum (`services/streamingModels.ts`) must match the
    Python `PacketType`** the backend emits (see [[streaming-protocol]]). A mismatch is a
    silent no-render, not a type error, because packets arrive as parsed JSON.
15. **An unresolved citation renders nothing, never broken markup.** `MemoizedAnchor`
    returns `<></>` rather than the raw `[D1](url)` text when the citation or document has
    not arrived yet (`MemoizedTextComponents.tsx:MemoizedAnchor`).
16. **`stop` and `citation_info` are never rendered as timeline blocks.** They are
    threaded as props (`stopPacketSeen`/`stopReason`) or folded into a lookup map
    (`getCitations`). Do not add a case in `findRenderer` for them; add to the prop
    threading or the fold instead.
17. **The message tree is the source of truth for branch state.** `latestChildNodeId`
    determines what `getLatestMessageChain` renders; a UI change that shows an alternate
    branch without going through `setMessageAsLatest`/`patchMessageToBeLatest` will
    desync from what a reload shows.

---

## 6. Relationships

**Depends on**
- [[core-chat-loop]]: the turn endpoint and the packet stream this component parses and
  renders.
- [[streaming-protocol]]: the packet vocabulary; `PacketType` here must track it.
- [[citations]]: the citation numbering this component resolves to documents.
- [[chat-persistence]]: every session/message CRUD endpoint this component calls.
- [[agents-personas]]: `agentId`, `useActiveAgent`, the agent picker.
- [[projects]]: `ProjectsProvider`, `currentProjectId`, project file context.
- [[llm-providers]]: `useLlmManager`, `ModelSelector`, `MultiModelSelector`.
- [[file-store-and-user-files]]: `beginUpload`, attached files, in-message images.
- [[voice]]: `VoiceModeProvider` wraps this component's layout.

**Depended on by**
- Nothing upstream inside the web app; this is the top-level chat surface.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds or renames a streaming packet type | `services/streamingModels.ts:PacketType`, `findRenderer` in `renderMessageComponent.tsx`, and whether it belongs in `isToolPacket`/`isDisplayPacket` (`services/packetUtils.ts`); confirm parity with [[streaming-protocol]] and [[mobile-app]], which parses the same stream |
| changes the Zustand store shape (`ChatSessionData`) | every selector hook in `stores/useChatSessionStore.ts`, `createInitialSessionData`'s defaults, and any component reading the field directly instead of through a selector |
| changes a route or a query param name | `services/searchParams.ts:SEARCH_PARAM_NAMES`, `buildChatUrl`'s `PARAMS_TO_SKIP`, and `useActiveAgent`/`useActiveProject`, which read params directly |
| changes an endpoint this client calls | `services/lib.tsx` (the fetch wrapper), the e2e mocks in `web/tests/e2e/utils/chatMock.ts`, and the matching backend component in [[core-chat-loop]] or [[chat-persistence]] |
| touches markdown or citation rendering | `MemoizedAnchor`, `processContent`, and `chat_message_rendering.spec.ts`; verify unresolved citations still render nothing during streaming, not broken link text |
| changes the message tree shape or branch logic | `messageTree.ts` functions, `message_edit_regenerate.spec.ts`, and reload parity (a reloaded session must show the same branch as before reload) |
| touches uploads | `handleMessageSpecificFileUpload`, the `Dropzone`'s `noClick noPaste` props, and `chat_file_uploads.spec.ts` |
| changes sharing | `ShareChatSessionModal.tsx`, the `/app/shared/[chatId]` route and `SharedChatDisplay.tsx`, and `share_chat.spec.ts` |
| touches any `@opal/components` usage in this component | re-read the rules in §5; a missed rule usually fails review, not CI |

---

## 8. How to verify a change

### Tests

```bash
# Playwright e2e, the preferred level for this component
cd web && bun run playwright chat_message_rendering
cd web && bun run playwright message_edit_regenerate
cd web && bun run playwright message_feedback
cd web && bun run playwright chat_file_uploads
cd web && bun run playwright share_chat
cd web && bun run playwright queued_messages
cd web && bun run playwright sidebar_chat_rename
cd web && bun run playwright chat-search-command-menu
cd web && bun run playwright chat_session_not_found
```

Do not use `bunx` or `npx` for Playwright; they can fetch an unpinned version
(`web/AGENTS.md`).

`web/tests/e2e/utils/chatStream.ts` and `chatMock.ts` let a test drive a fully
deterministic stream without a real LLM: `mockChatEndpoint` /
`mockChatEndpointSequence` (`chatMock.ts`) intercept `send-chat-message` and serve a
hand-built SSE body, and `buildMockStream`, `buildMockImageGenStream`,
`buildMockSearchStream` (`chatMock.ts`) construct the NDJSON payloads packet by packet.
`parseChatStreamBody` / `getPacketObjectsByType` / `getToolPacketCounts`
(`chatStream.ts`) then let the test assert on exactly which packets were sent, which is
the fastest way to add coverage for a new renderer or a packet-parsing edge case without
touching the backend at all.

### Manual reproduction

Prefer driving the user's real Chrome via `claude-in-chrome` over launching Playwright ad
hoc for a one-off check.

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000/app`, sign in as `admin_user@example.com` /
   `TestPassword123!`.
3. Send a message that forces a tool call, e.g. "what does our onboarding doc say".
   Confirm reasoning, a search block, the streamed answer, and citations that resolve to
   real documents (not blank spots).
4. Edit an earlier message, confirm a new branch appears and the switcher lets you go
   back to the original.
5. Add a second model in the model selector, send a message, confirm both columns stream
   independently, then mark one as preferred.
6. Drag an image file onto the page (not into the input bar) and confirm it uploads.
7. Press stop mid-answer, reload the page, confirm the partial answer persisted and the
   session did not resume generating.
8. Open the share modal, toggle public, open the `/app/shared/{id}` link in a private
   window, confirm it renders without requiring the same account's edit affordances.

### What "working" looks like

- No packet renders as a mysteriously empty block (check `findRenderer` returned
  something).
- No half-formed `[D1](` citation text flashes during streaming.
- A page reload during or after a turn reproduces exactly what was on screen live.
- Every new/changed visible string obeys the i18n and Opal rules in §5.

---

## 9. Footguns

- **`web/src/app/api/[...path]/route.ts` is dev-only.** It 404s outside
  `NODE_ENV=development` unless `OVERRIDE_API_PRODUCTION=true`. Do not assume `/api/...`
  calls in this component are proxied the same way in production; something else (nginx)
  handles that path there.
- **The SSE regex fallback can silently mis-parse.** `handleSSEStream`'s
  `/\{[^{}]*\}/g` recovery only handles a flat, single-level JSON object; a packet with
  a nested object in its payload that gets split across chunks can be dropped or
  corrupted without an obvious error, because both the `JSON.parse` failure and the
  fallback failure are only `console.error`ed, never surfaced to the user.
- **`noClick noPaste` on the page-level `Dropzone` is deliberate**, not a bug. The input
  bar already handles click-to-upload and paste itself; without `noPaste` the dropzone
  and the input bar would both attach a pasted image, duplicating it.
- **Auto-naming can fire twice.** `handleNewSessionNaming`
  (`useChatController.ts`) names a new session after its first exchange;
  `useChatSessionController.ts` also renames on load if `chatSession.description` is
  still empty. A rapid reload right after the first message can trigger both.
- **Opal `Text` strips `className`.** A component that needs to control `Text`'s layout
  must use a wrapping element or `Text`'s own props, not a passed-in class.
- **Citations resolve by `document_id` lookup at render time, not by index.** A
  `citation_info` packet arriving after its `[D<n>]` markdown link has already streamed
  in is normal, not a bug; `MemoizedAnchor` renders nothing until the lookup succeeds.
- **The message tree's `latestChildNodeId` is what a reload replays**, not whatever the
  UI happens to be showing client-side. A branch switch that updates local state without
  calling `patchMessageToBeLatest` will look right until the next reload.
- **Multi-model mode auto-folds the sidebar** (`views/AppPage.tsx`,
  `foldSidebarForMultiModel`) and restores the prior fold state only when the user drops
  back to a single model; a change to the multi-model exit path that skips this can leave
  the sidebar stuck folded.
