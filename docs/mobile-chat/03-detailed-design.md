> Status: active · Task: mobile-chat · Approach: C — Hybrid Seams

# Mobile Chat Port — Detailed Design

> **Altitude note.** Kept deliberately high-level per the project owner's request: this is a *map*, not a line-by-line spec. Each PR phase (see `05-pr-roadmap.md`) gets its own detailed-analysis session that grills the owner before coding. Treat file lists and shapes here as the intended structure, to be confirmed/refined per phase.

> **⚠️ DECISION OVERRIDE (2026-06-29) — chat logic is NOT shared.** See the matching callout in `05-pr-roadmap.md`. The owner reversed Approach C's shared-seam plan *for chat code*: nothing chat-related is extracted into `@onyx-ai/shared`. **Everywhere this document lists `web/lib/shared/src/contracts/*` or `web/lib/shared/src/utils/*` (e.g. `ndjson.ts`, `messageTree.ts`, `chatHistory.ts`, `streaming.ts`, `chat.ts`, `files.ts`, `agents.ts`, `projects.ts`, `fileDescriptors.ts`), read it as `mobile/src/chat/*` — mobile-owned, no web re-points, no shims.** The "Shared message-tree fns", "Shared `createNdjsonBuffer()`", and the shared-`dist`/`watch.mjs` integration notes below are superseded: mobile owns these copies and web is untouched. `@onyx-ai/shared` keeps receiving only cross-platform **design** primitives. Implemented in PR 2 under `mobile/src/chat/` (`streamingModels.ts`, `interfaces.ts`, `ndjson.ts`, `messageTree.ts`, `__tests__/`).

## Database design

**N/A — no backend or database changes.** The mobile client talks to the existing Onyx backend and its existing schema. All "data model" work is client-side (in-memory zustand + TanStack Query cache, plus MMKV persistence already configured). The relevant backend tables (`chat_session.project_id`, `user_file`, `persona`, `project`, `Project__UserFile`) already exist and are documented in `01-research.md`.

## Client data model

### Ephemeral chat state — `chatSessionStore` (zustand, **not** persisted)
Mirrors web's `useChatSessionStore` shape, trimmed to the locked core (no multi-model, no regeneration, no queued-messages, no doc-sidebar fields):

| Field | Shape | Why |
|-------|-------|-----|
| `currentSessionId` | `string \| null` | which session the open screen renders |
| `sessions` | `Map<sessionId, SessionData>` | per-session isolation so one stream can't write into another |
| `SessionData.messageTree` | `Map<nodeId, Message>` (mobile-native `Message` type) | the conversation; mutated only via the mobile-native `upsertMessages` |
| `SessionData.chatState` | `'input'\|'loading'\|'streaming'\|'uploading'` | drives input bar + spinner + send gating |
| `SessionData.abortController` | `AbortController` | cancels the stream on stop/unmount; **non-serializable → store must never be persisted** |
| `SessionData.submittedMessage` | `string` | optimistic echo before the user node lands |

Actions (ported, trimmed): `setCurrentSession`, `createSession`, `updateSessionAndMessageTree`, `updateChatState`, `setAbortController`, `abortSession`.

### Server-state lists — TanStack Query (persisted to MMKV, PII-excluded)
Keys extend `mobile/src/api/query-keys.ts`, all keyed by `serverUrl`:
`chatSessions(serverUrl)`, `chatSession(serverUrl, id)`, `agents(serverUrl)`, `projects(serverUrl)`, `projectFiles(serverUrl, projectId)`.

### Attachment progress — `uploadStore` (zustand, ephemeral, separate)
Keyed by client-side temp file id → `{ uri, name, mimeType, size, status, bytesSent, totalBytes }`. Consumed by the input bar and the project file screen.

## Class / interface design

No classes. The new surface is functions + types + hooks. Key seams:

- **Mobile-native `createNdjsonBuffer<T>()`** (`mobile/src/chat/ndjson.ts`) — `pushChunk(text: string) => T[]` and `flush() => T[]`, generic over the caller's packet type. Holds the partial-line string; splits on `\n`, keeps the trailing partial, `JSON.parse`s each complete line with web's brace-recovery fallback. **No `fetch`/`TextDecoder`** — those stay in the transport. Mirrors web's `handleSSEStream` parsing core (reader removed); **not shared** (PR 2 Decision (2026-06-26) in `05-pr-roadmap.md`).
- **Mobile `streamChatMessage(body, signal): AsyncGenerator<Packet>`** (`mobile/src/api/chat/stream.ts`) — owns the `expo/fetch` POST + `getReader()` + `TextDecoder` loop; feeds the mobile-native buffer; filters `chat_heartbeat`; `reader.cancel()` on abort/`finally`.
- **Mobile packet-renderer registry** (mirrors web's `renderMessageComponent.tsx` + `MessageRenderer<TPacket,TState>` contract) — the **extensibility foundation**, built in PR 3 even though only one renderer ships then:
  - `MessageRenderer<TPacket, TState>` (mobile contract) — `{ matches(packetType): boolean; reduce(state, packet): TState; render(state): ReactNode }`. RN-coupled (returns RN nodes) → **mobile-owned**, not shared. The *packet-grouping* step can later be shared if reuse is proven.
  - `findRenderer(packetType): MessageRenderer | null` — the dispatch (mobile equivalent of web's `findRenderer`).
  - **Core (PR 3) registers exactly one renderer: `MessageTextRenderer`** (`MESSAGE_START/DELTA/END` → markdown string + `isComplete`/`error`). This is ~the same code as a flat concatenator, so it does **not** grow core scope.
  - **`usePacketDisplay(node)`** groups the node's packets and walks the registry to produce render output. Deferred rich-chat PRs (9a–9e) **add a renderer to the registry** (and, for agentic steps, a timeline composition layer) — **no core rewrite**. (Web's React-coupled `usePacketProcessor` stays web-only.)
- **Mobile-native message-tree fns** — `upsertMessages`, `getLatestMessageChain`, `getMessageByMessageId`, `buildImmediateMessages`, `buildEmptyMessage`, `SYSTEM_NODE_ID`, `MessageTreeState`. Ported from web's `messageTree.ts` against the **minimal mobile `Message`** (per the PR 2 minimal-sharing decision — **not** shared; web keeps its own copy untouched). `processRawChatHistory` likewise lives in `mobile/src/chat/chatHistory.ts`.

## New files

### Shared package (`web/lib/shared/src/`)
**No new shared files.** Per the PR 2 Decision the chat pure layer is mobile-native; nothing chat-related enters `@onyx-ai/shared`.

### Mobile-native chat layer (`mobile/src/chat/`) — per the PR 2 Decision the entire chat pure layer lives in mobile, **not** shared
| File | Responsibility |
|------|----------------|
| `ndjson.ts` | `createNdjsonBuffer<T>()` — pure line-buffer NDJSON parser (mirrors web's `handleSSEStream` parsing core). |
| `contracts/streaming.ts` | Minimal `Packet` wrapper, `Placement`, `PacketType` (core subset), `MessageStart/Delta/End`, `Stop`/`StopReason`, `PacketError`, `ChatHeartbeat`, `MessageResponseIDInfo`. `MessageStart.final_documents` typed `unknown[] \| null` (no `OnyxDocument`). Rich packet types added later, per their phase. |
| `contracts/chat.ts` | `Message` (minimal), `ChatState`, `ChatSession`/`BackendChatSession`/`BackendMessage`, send-message request body type, create-session request/response. |
| `contracts/files.ts` | `FileDescriptor`, `ChatFileType`, `UserFileStatus`. |
| `contracts/agents.ts` | `MinimalAgent` (selection subset), `AgentStarterMessage`. |
| `contracts/projects.ts` | `Project`, `ProjectFile`, `CategorizedFiles`, `RejectedFile`. |
| `messageTree.ts` | Tree upsert/traversal/builders — ported from web against the minimal `Message`. |
| `chatHistory.ts` | `processRawChatHistory` — backend messages+packets → tree (structural-only). |
| `fileDescriptors.ts` | `projectFilesToFileDescriptors` + type detection (PR 8). |

### Mobile (`mobile/src/`)
| File | Responsibility |
|------|----------------|
| `app/(app)/_layout.tsx` | Authed Stack under `AuthGate`; hosts the chat group. |
| `app/(app)/index.tsx` | New-chat / chat home (empty state, starter prompts). |
| `app/(app)/chat/[id].tsx` | A chat session screen (message list + input bar). |
| `app/(app)/history.tsx` | Sessions/history list. |
| `app/(app)/projects/index.tsx`, `projects/[id].tsx` | Projects list + project detail (chats + files). |
| `state/chatSessionStore.ts` | Ephemeral per-session zustand store (above). |
| `state/uploadStore.ts` | Attachment upload progress (above). |
| `api/chat/stream.ts` | `expo/fetch` streaming generator (above). |
| `api/chat/sessions.ts` | TanStack Query hooks: create/get/list/rename sessions. |
| `api/chat/agents.ts` | `GET /api/persona` hook. |
| `api/chat/projects.ts` | projects list/detail/files + link/unlink hooks. |
| `api/files/upload.ts` | `expo-file-system` `createUploadTask` multipart uploader. |
| `hooks/useChatController.ts` | `onSubmit`, drive stream, ~50ms batched flush, stop. |
| `hooks/useChatSessionController.ts` | Load session → hydrate tree; resume in-flight run. |
| `hooks/usePacketDisplay.ts` | Groups a node's packets + walks the renderer registry to produce render output. |
| `components/chat/renderers/registry.ts` | `MessageRenderer` contract + `findRenderer` dispatch (mirrors web's `renderMessageComponent`). Core registers only `MessageTextRenderer`. |
| `components/chat/renderers/MessageTextRenderer.tsx` | The one core renderer: `MESSAGE_*` → `StreamingMarkdown`. Rich renderers (9a–9e) register alongside it later. |
| `components/chat/MessageList.tsx` | FlashList v2 non-inverted, `maintainVisibleContentPosition`, `onStartReached` pagination, memoized rows. |
| `components/chat/MessageRow.tsx` | User vs assistant bubble; memoized on `(nodeId, packetCount)`; renders via `usePacketDisplay`. |
| `components/chat/AgentTimeline.tsx` | *(deferred — first built in PR 9b)* composition layer for agentic timeline renderers; mirrors web's `AgentTimeline`/`TimelineRendererComponent`. |
| `components/chat/StreamingMarkdown.tsx` | RN markdown (streamdown behind an interface; marked fallback); block-memoized. |
| `components/chat/InputBar.tsx` | `KeyboardStickyView` growing input + send/stop; later: attachment chips. |
| `components/chat/AgentPicker.tsx` | Bottom-sheet agent list (avatar/name/description/starters). |
| `components/chat/AttachmentChips.tsx` | Selected-file chips + status + remove. |
| `icons/*` | Any new icons (paperclip, stop, etc.). |

## File structure (tree)

```
web/lib/shared/src/   (NO chat changes — nothing chat-related enters shared)
web/src/              (UNTOUCHED — streamingUtils.ts / messageTree.ts / fileUtils.ts stay web-owned)

mobile/src/
├── app/
│   ├── _layout.tsx         (modified: mount (app) group)
│   └── (app)/              (new)  _layout · index · chat/[id] · history · projects/*
├── chat/                   (new, mobile-native pure layer)
│   ├── ndjson.ts (new)     contracts/ (new)  streaming · chat · files · agents · projects
│   ├── messageTree.ts (new)  chatHistory.ts (new)  fileDescriptors.ts (new)
│   └── *.test.ts           (new)  ndjson + tree + history unit tests
├── state/                  (new)  chatSessionStore.ts · uploadStore.ts
├── api/
│   ├── query-keys.ts       (modified: add chat/agents/projects keys)
│   ├── chat/               (new)  stream.ts · sessions.ts · agents.ts · projects.ts
│   └── files/              (new)  upload.ts
├── hooks/                  (new)  useChatController · useChatSessionController · usePacketDisplay
└── components/chat/        (new)  MessageList · MessageRow · StreamingMarkdown · InputBar · AgentPicker · AttachmentChips
```

## Integration points

- **Auth / HTTP** — list calls reuse `mobile/src/api/client.ts apiFetch` (bearer + `ApiError`). The streaming call (`api/chat/stream.ts`) reuses `getBaseUrl()` (`config.ts`) + the token from `tokenStore.ts`, but uses `expo/fetch` directly.
- **Navigation** — `(app)` group mounts under the existing `AuthGate` in `mobile/src/app/_layout.tsx`; sidebar (`mobile/src/components/sidebar`) surfaces sessions/projects.
- **Query cache** — extend `mobile/src/api/query-keys.ts` + reuse the persisted client in `mobile/src/query/client.ts`. **Required (not conditional):** chat content is sensitive by nature, so the chat session-list + session-detail/message query keys **must** be added to the `dehydrateOptions` PII-exclusion list (alongside the existing `me` exclusion) in PR 1, **before any chat history is persisted to MMKV**. Consequence: chat history is not cached to disk and refetches on launch — the correct PII-safe default (mirrors the `me`-exclusion pattern).
- **No web changes** — the mobile chat port touches no web files. `web/src/lib/search/streamingUtils.ts`, `.../messageTree.ts`, and `.../fileUtils.ts` stay web-owned; mobile reimplements the parser/tree/file-descriptor logic natively in `mobile/src/chat/`.
- **No shared-build coupling** — nothing chat-related enters `@onyx-ai/shared`, so there's no dist-rebuild/`file:`-relink dependency for the chat port. (`@onyx-ai/shared` keeps its existing design-token + interactive/typography + `numbers`/`format` surface.)

## Important notes before implementation

- **De-risk spikes first (Phase 0/early):** (1) confirm `expo/fetch` exposes `response.body.getReader()` on a **device dev build** (RN 0.85 / SDK 56) — fallback is XHR progress feeding the *same* NDJSON buffer; (2) confirm `react-native-streamdown` builds on RN 0.85 / Reanimated v4 — fallback `react-native-marked` (both keep block-memoization). Both require a **dev client** (already have `expo-dev-client`), not Expo Go.
- **Never persist `chatSessionStore`** — it holds `AbortController`s and live streams. Keep it strictly separate from the persisted TanStack cache; on relaunch, rehydrate a session via `GET get-chat-session` + the mobile-native `processRawChatHistory`.
- **Batch flushes ~50ms** and memoize rows on `packetCount` (not array identity) — the single biggest streaming-perf lever; port web's `stillCurrent`/abort guards so a backgrounded stream can't write into the wrong session.
- **Send gating** — block send until attached files are indexed (`token_count != null`); surface a `FAILED`/stuck status instead of blocking forever (3s status polling, mirror `ProjectsContext`).
- **Keep the mobile `contracts/streaming.ts` minimal** — only the core packet types now; add rich types in their deferred phases. Avoid dragging web's full `OnyxDocument` shape across until citations land.
- **Renderer foundation in PR 3, renderers as follow-ups** — build the `MessageRenderer` contract + `findRenderer` dispatch in PR 3 (registering only `MessageTextRenderer`) so rich-chat features are *additive registrations*, not core rewrites. The agentic-timeline composition layer (`AgentTimeline`) is itself deferred — the **first** timeline renderer PR (9b) builds it; the dispatch seam it plugs into already exists from PR 3. Do **not** build the rich renderers in core — only the seam.
- **Agent/project selection is implicit** — carried by the session's `persona_id`/`project_id` at create-time; there is no per-message agent param. Selecting an agent for an *existing* session is not supported by the backend (matches web) — start a new session.
- **Error handling** — `ERROR`/`PacketError` packets set the assistant node to an error state; raise `OnyxError`-style messages only on the backend (client surfaces `ApiError` messages). No `HTTPException` concerns here (client-only).
- **`expires=` / Celery** — N/A (no backend tasks introduced).
