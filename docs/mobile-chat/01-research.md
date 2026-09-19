> Status: active · Task: mobile-chat

# Mobile Chat Port — Research

## Requirement

Port the Onyx **web chat experience** to the Onyx **mobile app** (React Native 0.85 + Expo SDK 56 + NativeWind). Scope: core chat (send → stream → markdown → sessions/history), **agent selection** (select-an-agent-to-chat-with only, no creation/editing), **projects** (select + chat-within + project file management; no project CRUD), and **input-bar file attachment** (documents + photo library; no camera). Pure-TS logic is shared via `@onyx-ai/shared`. Delivered as **independently-mergeable phases**, merged one-by-one. Product is **not in production** — no backwards-compat concerns.

## Clarifications (locked at GATE 1 intake)

| # | Question | Answer |
|---|----------|--------|
| 1 | Core-chat feature floor | **Minimal robust core**: send → stream the answer → render markdown → sessions/history list. Defer citations/sources, agentic sub-steps (reasoning/search/tool timeline), regenerate/edit/feedback, follow-up suggestions, image-gen to their own later phases. |
| 2 | Projects scope | **Select + chat-within + project file management** (add/remove files). Project create/rename/delete **deferred**. |
| 3 | Attachment sources | **Documents** (expo-document-picker) **+ photo library** (expo-image-picker). Camera **deferred**. |
| — | Agents | Select-to-chat only. No creation/editing. |
| — | Shared-extraction policy (standing) | `@onyx-ai/shared` grows **incrementally, extract-on-proven-reuse** — not a big upfront task. Cross-platform contracts go in neutral paths (`/contracts`, `/types`); `/native` is RN-only. |

## Current status & reuse (codebase scan — exact paths)

**Web chat (the thing being ported) — newer "refresh" architecture:**
- Orchestrator `web/src/refresh-pages/AppPage.tsx` wires hooks `web/src/hooks/useChatController.ts` (submit end-to-end), `web/src/hooks/useChatSessionController.ts` (session lifecycle + resume), `web/src/lib/agents/hooks.ts` (agent selection).
- State: Zustand store `web/src/app/app/stores/useChatSessionStore.ts` — per-session `messageTree: Map<nodeId, Message>`, `chatState` (`'input'|'streaming'|'loading'|'uploading'|'toolBuilding'`), per-session `AbortController`.
- **Streaming send**: `web/src/app/app/services/lib.tsx` `sendMessage()` POSTs `/api/chat/send-chat-message` (confirmed at `lib.tsx:189`). Response is **NDJSON** (newline-delimited JSON), **not SSE-framed**. Parser `web/src/lib/search/streamingUtils.ts` `handleSSEStream()` uses `fetch` `response.body.getReader()` + `TextDecoder` + buffer/`split('\n')`; filters `chat_heartbeat`.
- **Packet protocol**: wrapper `{ placement:{turn_index,tab_index?,sub_turn_index?,model_index?}, obj:{type,...} }`. 40+ packet types (pure TS) in `web/src/app/app/services/streamingModels.ts`. **Minimal core needs only** `MESSAGE_START/DELTA/END`, `STOP`, `ERROR`, `MessageResponseIDInfo`, `CreateChatSessionID`.
- **Pure-TS, React-free**: `web/src/app/app/services/messageTree.ts` (`upsertMessages`, `getLatestMessageChain`, `buildImmediateMessages`, …). Core types in `web/src/app/app/interfaces.ts`.
- **React-coupled** (must be reimplemented in RN): packet→display transform `…/timeline/hooks/usePacketProcessor.ts`; markdown `web/src/components/chat/MinimalMarkdown.tsx` (react-markdown + rehype); scroll/toolbar/editing UI.
- Sessions: `POST /api/chat/create-chat-session {persona_id(=0 default), description, project_id}` → `{chat_session_id}`. Detail returns `messages[]` + `packets[][]` (replay) + `current_run`. Resume in-flight: `GET /api/chat/chat-session/{id}/resume-stream?cursor=n`. Stop: `POST /api/chat/stop-chat-session/{id}`.
- **Agents**: `GET /api/persona` → `MinimalAgent[]` (`id,name,description,tools[],starter_messages,icon_name,uploaded_image_id,builtin_persona,is_public,is_featured,display_priority`). Selection is **implicit** — session carries `persona_id`; `sendMessage` has **no** agent param. Types `web/src/lib/agents/types.ts`. Default persona id=0.
- **Projects**: `GET /api/user/projects` → `Project[] {id,name,instructions,chat_sessions[]}`; `ChatSession.project_id`. Files many-to-many. Upload `POST /api/user/projects/file/upload` (multipart, field `files`, `project_id?`, `temp_id_map?`) → `{user_files: ProjectFile[], rejected_files[]}`. `ProjectFile {id,file_id,name,status,chat_file_type,token_count,…}`; `UserFileStatus` enum. Link/unlink `POST`/`DELETE /api/user/projects/{pid}/files/{fid}`. Service `web/src/app/app/projects/projectsService.ts`; state `web/src/providers/ProjectsContext.tsx` (optimistic temp_id, **3s status polling**).
- **Attachments**: `FileDescriptor {id, type:ChatFileType, name?, user_file_id?}`; `ChatFileType` enum (`image/document/plain_text/tabular/user_knowledge`). Pure helper `projectFilesToFileDescriptors()` `web/src/app/app/services/fileUtils.ts`. Sent message carries `file_descriptors[]`. **Send is gated** until uploaded files are indexed (`token_count != null`). Image preview via `GET /api/chat/file/{file_id}`.
- Backend: `backend/onyx/server/query_and_chat/chat_backend.py` (+ `models.py`, `streaming_models.py`), `…/features/projects/api.py`, `…/features/persona/api.py`.

**Mobile foundation already in place (reuse these):**
- Navigation: `mobile/src/app/_layout.tsx` (`PersistQueryClientProvider` + `SidebarProvider` + `AuthGate` + expo-router `Stack`). Route group `(auth)` at `mobile/src/app/(auth)`. A new authed chat route group slots alongside.
- HTTP: `mobile/src/api/client.ts` `apiFetch<T>` — injects Bearer token, normalizes errors to `ApiError`, base URL lazy from `session.serverUrl` (`mobile/src/api/config.ts`). Query keys `mobile/src/api/query-keys.ts` (keyed by `serverUrl`).
- Server state: TanStack Query persisted to MMKV, PII excluded via `dehydrateOptions` (`mobile/src/query/client.ts`). Auth/session: `mobile/src/api/auth/sessionManager.ts`, `mobile/src/api/auth/tokenStore.ts` (bearer store — `getToken`/`setToken`, secure-store backed), `mobile/src/hooks/useCurrentUser.ts`, `mobile/src/state/session.ts` (zustand).
- UI primitives: `mobile/src/components/ui` (`text/button/text-input/icon/separator`). Sidebar `mobile/src/components/sidebar`. Icons `mobile/src/icons`. `zustand`, `@shopify/flash-list@2.0.2`, `react-native-reanimated@4`, `react-native-worklets`, `expo-dev-client` all present.
- Shared pkg `@onyx-ai/shared` at `web/lib/shared/src` — currently thin (`types/dto.ts`, `types/enums.ts`, `contracts/`, `utils/`). Subpath exports `./types ./contracts ./utils`. Consumed by mobile via `file:` dep; **dist must be rebuilt** when shared changes.

## Industry best practices (web research, 2025–2026)

- **Streaming transport** — Use **`expo/fetch`** (SDK 56 default global), *not* RN's legacy XHR-backed fetch (no `response.body`). POST with Bearer + JSON, consume `response.body.getReader()` + `TextDecoder.decode(value,{stream:true})` + buffer/`split('\n')`, keep trailing partial, flush on `done`. **This mirrors the web parser almost verbatim → the NDJSON line-parsing layer is shareable pure TS.** Batch token state updates ~50ms, memoize rows, `reader.cancel()` on unmount/abort. *Not* `react-native-sse` (stream is NDJSON, not SSE-framed). — reactnative.dev/blog/2026/04/07/react-native-0.85 · docs.expo.dev/versions/latest/sdk/expo · getwireai.com/blog/react-native-llm-streaming
- **Message list** — `@shopify/flash-list` v2 (already pinned), **non-inverted**, `maintainVisibleContentPosition={{ startRenderingFromBottom:true, autoscrollToBottomThreshold:0.2 }}`; paginate older via `onStartReached`; guard the short-list case (#2050). Note: `startRenderingFromBottom` / `autoscrollToBottomThreshold` are **FlashList v2's own extended `maintainVisibleContentPosition` keys** (verified against the v2 docs' chat example) — distinct from React Native core's ScrollView prop, which only has `minIndexForVisible` / `autoscrollToTopThreshold`. — shopify.github.io/flash-list/docs/v2-changes · shopify.github.io/flash-list/docs/usage
- **Markdown** — `react-native-markdown-display` is unmaintained. Options: **`react-native-streamdown`** (Software Mansion; handles partial/unterminated markdown during streaming via worklets; needs dev build + RN0.85 compat spike) or **`react-native-marked`** (pure JS, safe fallback). **Block-level memoization** is the key streaming-perf win regardless of lib. — github.com/software-mansion-labs/react-native-streamdown · streamdown.ai/docs/memoization
- **Keyboard/input** — `react-native-keyboard-controller` (`KeyboardStickyView` for the sticky growing input) — needs a dev build (have `expo-dev-client`) + Reanimated (present). — docs.expo.dev/guides/keyboard-handling
- **Files** — `expo-document-picker` (`copyToCacheDirectory:true`) + `expo-image-picker` (`mediaTypes:['images']`). Upload via **new `expo-file-system` `File(uri).createUploadTask(url,{uploadType:MULTIPART, fieldName:'files', headers:{Authorization}, onProgress})`** — streams from disk, avoids the iOS FormData 2-3× memory OOM. Non-2xx **resolves** (check status yourself). Normalize each asset to `{uri,name,mimeType,size}` with fallbacks; drive via `useMutation` + a small zustand progress store. — docs.expo.dev/versions/latest/sdk/filesystem · github.com/facebook/react-native/issues/33998

## Approaches

> All three share the **same vertical-slice phase roadmap** (foundation → shared parser/contracts → core chat → sessions/history → agents → projects → project files → input attachments → deferred rich-chat). They diverge **only on the shared-extraction boundary** — how much of the web chat's pure-TS heart moves into `@onyx-ai/shared` vs is reimplemented/copied on mobile, and whether web is refactored to consume it.

### Approach A — Simplicity-First: "Thin-Contracts, Fat-Mobile"
Share **only** what is provably identical *today*: the packet **type contracts** (trimmed `streamingModels.ts`) and the pure **NDJSON line parser** (the buffer/split core of `handleSSEStream`, minus the reader). DTO types (FileDescriptor/enums, MinimalAgent, Project/ProjectFile) move to shared incrementally as each phase needs them. Mobile **copies** the ~4 message-tree functions it actually uses (web's `messageTree.ts` carries multi-model/agentic cruft) and **reimplements** the packet→display reducer, handling only `MESSAGE_*`/`STOP`/`ERROR` in core. Web is touched only to import the shared packet types + parser (low-risk, covered by web tests).
- **Gains**: smallest shared surface, most policy-aligned, lowest per-PR risk; mobile uses RN-native idioms freely.
- **Sacrifices**: two parsers + two reducers + two tree copies → silent drift risk if the backend protocol changes; mobile may re-debug bugs web already fixed.

### Approach B — Robustness/Reuse-First: "Fat Shared Chat Engine"
Extract the web's entire pure-TS heart into a new `@onyx-ai/shared/chat` subpath: all packet types, the NDJSON parser **behind a `ChatTransport` interface**, `messageTree.ts`, the `packetProcessor.ts` reducer, `buildSendMessageBody`, and `processRawChatHistory`. **Refactor web** to consume it (thin re-export shims keep web import paths working). Mobile implements exactly one new platform primitive — an expo/fetch `ChatTransport` — plus the RN render layer + thin store/query glue.
- **Gains**: true single-source-of-truth — a backend packet change updates one file and both apps follow; mobile phases become nearly pure render work; engine is trivially unit-testable with a fake transport.
- **Sacrifices**: **violates the standing extract-on-proven-reuse policy** (extracts before reuse is proven); **edits working web streaming code inside the porting PRs** (regression surface on live web); couples web + mobile to the shared dist rebuild; front-loads abstraction for deferred features.

### Approach C — Flexibility-First: "Hybrid Seams" *(recommended)*
Share the cross-platform **contracts** (chat/streaming/files/agents/projects types) **and** the genuinely dependency-free **pure helpers** where drift is most dangerous and the move is cheap: the NDJSON line-buffer parser, `messageTree` upsert/traversal, `processRawChatHistory`, `projectFilesToFileDescriptors`. Do **not** extract the React-coupled `usePacketProcessor`. **Mobile owns** its orchestration hooks + zustand store + render layer + a thin packet→display mapping (core = "concatenate `MESSAGE_*` content"). **No web refactor** in the porting PRs — web imports are re-pointed *opportunistically*, per phase, only where the file is already pure (mechanical import swap).
- **Gains**: shares exactly the high-value/low-cost/high-drift-risk pieces (these are identical by construction since both clients speak the same protocol = proven reuse, not speculative); keeps RN-native render/orchestration; no forced big-bang web refactor; honors the standing policy.
- **Sacrifices**: the packet→display logic lives in two places (web hook + mobile mapping) — accepted because that piece is genuinely React-coupled and the core mapping is trivial; some orchestration control-flow duplication.

## Cross-comparison

- **Drift risk** (backend protocol change touches N codebases): B = 1 · C = ~1.5 (parser/tree/contracts shared; thin display map duplicated) · A = 2 (parser, reducer, tree copies).
- **Risk to live web** in the porting PRs: A/C ≈ none (web import swaps only, or untouched) · B = real (refactors the streaming path; mitigated by re-export shims + web e2e).
- **Per-PR size / mergeability**: A/C keep phases ≤700 LOC cleanly · B's early shared-engine + web-refactor phases are the largest.
- **Policy fit** (extract-on-proven-reuse): C and A fit · B explicitly contradicts it.
- **Phase roadmap**: identical across all three — the choice does **not** reshape the roadmap, mainly the *content of Phase 2* and *how much web is touched*.
- **Shared spike risks** common to all: confirm `expo/fetch` exposes `response.body.getReader()` on a device build (RN 0.85 / SDK 56); confirm `react-native-streamdown` builds on RN 0.85 (fallback `react-native-marked`); both need a dev build (have `expo-dev-client`).

## Chosen approach

**Approach C — Hybrid Seams.** Selected at GATE 1.

> **Refinement (2026-06-26, PR 2 — revised to no shared chat code).** The shared boundary below is dropped **entirely** for chat: the NDJSON parser, contracts/types, `messageTree`, `processRawChatHistory`, and `projectFilesToFileDescriptors` are **all written natively in mobile**, with web keeping its own copies. We considered sharing the pure layer (and briefly just the parser), but the shared-package machinery (util + web re-point + jest mapper + dist coupling) is more moving parts than the ~200 lines of duplication it removes; pre-production the protocol is stable so drift is cheap to fix later. **Web is untouched.** See the **PR 2 Decision** in `05-pr-roadmap.md`. The bullets below record the original (wider) Approach-C intent.

- **Into `@onyx-ai/shared`** — **nothing chat-related** (revised). *(Originally: NDJSON parser + contracts + `messageTree` + `processRawChatHistory` + `projectFilesToFileDescriptors`, added incrementally — all now mobile-native; web untouched.)*
- **Stays mobile-only**: expo/fetch transport, the zustand chat-session store, mobile orchestration hooks (`useChatController`/`useChatSessionController`), **the chat/streaming/file contracts + `messageTree` + `processRawChatHistory` + `fileDescriptors` (now mobile-native, `mobile/src/chat/`)**, a thin packet→display mapping (core = concatenate `MESSAGE_*`), all RN UI, expo pickers + `expo-file-system` upload.
- **Stays web-only**: `usePacketProcessor` + transformers, `MinimalMarkdown`, the full tool/citation packet zoo, the SWR hooks. Web keeps its current copies; imports are re-pointed to shared **opportunistically per phase**, only where the file is already pure — **no big-bang web refactor**.
- The deferred rich-chat features (citations, agentic timeline, regenerate/edit/feedback, follow-ups, image-gen) each land as their **own later phase**, adding the relevant packet types to shared + a mobile mapping extension + RN UI.
