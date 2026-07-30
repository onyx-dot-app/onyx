> Status: active · Task: mobile-chat

# Mobile Chat Port — Implementation Plan

> **Altitude.** High-level by request. The ordered steps below are grouped so they map cleanly onto the PR-sized phases in `05-pr-roadmap.md`. Each phase gets its own detailed session that **grills the owner before any code is written**. This plan is the "what/how" skeleton, not a line-by-line spec.

## Issues to Address

The mobile app has auth, navigation, a sidebar, an HTTP layer, and UI primitives — but **no chat**, the core of the product. This effort ports the web chat experience to React Native + Expo so a mobile user can: pick an agent, hold a streaming conversation grounded in Onyx knowledge, browse/resume past sessions, work inside a project (with project file management), and attach documents/photos to a message. It must reuse the **existing, unchanged backend**; design tokens come from `@onyx-ai/shared` (Approach C — Hybrid Seams), but the chat pure layer is reimplemented natively on mobile rather than shared (see PR 2 Decision). Delivery is a sequence of **independently-mergeable phases**, not a big-bang merge.

## Important Notes

- **Streaming transport** — `/api/chat/send-chat-message` returns **NDJSON** (confirmed `web/src/app/app/services/lib.tsx:189`), not SSE-framed. Use **`expo/fetch`** (SDK 56 default) for `response.body.getReader()`; RN's legacy fetch has no readable body. This is the *only* call that bypasses `mobile/src/api/client.ts apiFetch`. (`01-research.md` › Industry best practices.)
- **No shared chat code — the whole pure layer is mobile-native** — the NDJSON parser, message tree, `processRawChatHistory`, and all chat/streaming/file types are written in `mobile/src/chat/` (P2), with web keeping its own copies. We considered sharing the pure layer (and briefly just the ~40-line parser), but the shared-package machinery (a `@onyx-ai/shared` util + a web re-point + jest/dist coupling) is more moving parts than the ~200 lines of duplication it removes; pre-production the protocol is stable, so drift is low and cheap to re-extract later if it bites. Keep the React-coupled `usePacketProcessor` mobile-owned (`mobile/src/hooks/usePacketDisplay.ts`); the core mapping is just "concatenate `MESSAGE_*` content." (See **PR 2 Decision (2026-06-26)** in `05-pr-roadmap.md`.)
- **No web changes at all** — the mobile chat port modifies zero web files. `web/src/lib/search/streamingUtils.ts`, `.../messageTree.ts`, and `.../fileUtils.ts` stay web-owned; mobile reimplements the parser/tree/file-descriptor logic natively.
- **Two-tier state** — TanStack Query (already MMKV-persisted, PII-excluded, keyed by `serverUrl`) for lists; a separate **non-persisted** zustand `chatSessionStore` for the live stream (it holds `AbortController`s).
- **PII (required, not optional)** — chat history (messages, file names, answers) is sensitive, so chat session/message query keys **must** be added to the `dehydrateOptions` PII-exclusion list in PR 1 before any history persists to MMKV (per the CONTRIBUTING multi-tenant PII stance). Net effect: chat content is not written to disk and refetches on launch — the safe default, matching the existing `me`-key exclusion.
- **Perf** — batch packet→UI flushes ~50ms; memoize FlashList rows on `packetCount`; FlashList v2 **non-inverted** with `maintainVisibleContentPosition` (not `inverted`).
- **Two early spikes gate the core** — confirm `expo/fetch` streaming on a **device dev build** (fallback: XHR progress → same shared buffer), and `react-native-streamdown` on RN 0.85 (fallback: `react-native-marked`). Both need a dev client (`expo-dev-client` present), not Expo Go.
- **Implicit selection** — agent (`persona_id`) and project (`project_id`) are bound at session-create; there is no per-message agent param and no backend API to change a session's agent (matches web — start a new session).
- **Send gating** — block send until attached files are indexed (`token_count != null`); surface stuck/`FAILED` rather than blocking forever (3s status poll, mirror `web/src/providers/ProjectsContext.tsx`).
- **No shared-build coupling** — nothing chat-related enters `@onyx-ai/shared`, so the chat port has no dist-rebuild / `file:`-relink dependency. (`@onyx-ai/shared` keeps its existing design-token + interactive/typography + `numbers`/`format` surface.)

## Implementation Strategy

Ordered, each step a coherent change; brackets show the PR phase it belongs to.

1. **[P1] Authed chat shell + sessions list.** Add the `(app)` expo-router group under `AuthGate` in `mobile/src/app/_layout.tsx`: new-chat home, `chat/[id]` scaffold (empty state + non-functional input shell), history list. Add `chatSessions(serverUrl)`/`chatSession(...)` query keys + a sessions-list hook over `apiFetch`. **Required in this PR (before any history persists): add the chat session/message query keys to the `dehydrateOptions` PII-exclusion list in `mobile/src/query/client.ts`.** Wire the sidebar to list sessions. No streaming yet.
2. **[P2] Mobile-native chat data layer.** Create `mobile/src/chat/`: `ndjson.ts` (pure NDJSON buffer mirroring web's `handleSSEStream` core), `contracts/*` (minimal packet/`Message`/`BackendMessage`/`FileDescriptor` types), `messageTree.ts` (upsert/traversal/builders against the minimal `Message`), `chatHistory.ts` (`processRawChatHistory`, structural-only). Jest unit-test the parser + tree + history. **Web + `@onyx-ai/shared` untouched.**
3. **[P3] Core chat: send → stream → markdown.** `mobile/src/api/chat/stream.ts` (`expo/fetch` generator + the **P2 mobile-native parser** + `AbortController`); `state/chatSessionStore.ts`; `hooks/useChatController.ts` (create session at `persona_id=0`, optimistic nodes via the P2 builders, drive stream, ~50ms flush, stop); the **packet-renderer foundation** — `components/chat/renderers/registry.ts` (`MessageRenderer` contract + `findRenderer` dispatch, mirroring web's `renderMessageComponent`) with **only** `renderers/MessageTextRenderer.tsx` registered + `hooks/usePacketDisplay.ts` (group + dispatch); `components/chat/{MessageList,MessageRow,StreamingMarkdown,InputBar}`; hydrate existing sessions via `GET get-chat-session` + the P2 `processRawChatHistory`. *(Run the two spikes at the start of this phase.)* The registry is the extensibility seam for PR 9 — building it now costs ~nothing over a flat reducer; **do not build rich renderers here.**
4. **[P4] Resume in-flight run + history polish.** `useChatSessionController` resume tail (`resume-stream?cursor=`) with a `stillCurrent` guard; `onStartReached` older-message pagination (guard short-list); rename-on-first-message + history refresh.
5. **[P5] Agent selection.** `contracts/agents.ts`; `api/chat/agents.ts` (`GET /api/persona`); `components/chat/AgentPicker.tsx`; selection sets `persona_id` at create; starter prompts on the empty screen. No creation/editing.
6. **[P6] Projects: list + select + chat-within.** `contracts/projects.ts`; `api/chat/projects.ts` (list/detail/files); projects list + detail screens; "new chat in project" passes `project_id`. No project CRUD.
7. **[P7] Project file management.** `api/files/upload.ts` (`expo-file-system` `createUploadTask`, multipart, field `files`); `state/uploadStore.ts` + 3s status polling; `expo-document-picker` + `expo-image-picker`; link/unlink; file list UI with status chips.
8. **[P8] Input-bar attachments (per-message).** Reuse P7 pickers/uploader for the input bar; `components/chat/AttachmentChips.tsx`; `mobile/src/chat/fileDescriptors.ts` (mobile-native `projectFilesToFileDescriptors`); build `file_descriptors[]` on send; gate send on indexing; image preview via `GET /api/chat/file/{file_id}`. Camera deferred.
9. **[P9+] Deferred rich-chat (each its own phase).** citations/sources · agentic timeline (reasoning/search/tool sub-steps) · regenerate/edit/feedback · follow-up suggestions · image-gen. Each adds rich packet types to **mobile's `mobile/src/chat/contracts/`** and **registers a new `MessageRenderer` into the P3 dispatch** (no core rewrite); the agentic-timeline phase additionally builds the `AgentTimeline` composition layer that subsequent timeline renderers plug into. Web's `usePacketProcessor` stays web-only.

## Tests

One dominant type per phase — don't overtest:

- **Pure helpers (P2)** → **unit tests** (jest, mobile runner): NDJSON buffering (partial lines, brace-recovery, heartbeat passthrough, trailing flush) + `upsertMessages`/`getLatestMessageChain`/`processRawChatHistory`. These are the highest-value tests — they protect the mobile-owned parser + tree + history. (Web's streaming path is unchanged and stays covered by its existing tests.)
- **Mobile hooks + components (P1, P3–P8)** → **`@testing-library/react-native`** component/hook tests with the **streaming transport mocked** (feed a scripted packet sequence): assert tokens render incrementally, stop aborts, send-gating blocks until indexed, agent/project selection threads `persona_id`/`project_id`, attachment chips reflect upload status. Use the existing mobile jest mocks (`jest.setup.ts`, `__mocks__/`) per the project's centralized RN mocking.
- **Real-backend streaming** → **manual device verification** on a dev build per phase (no RN e2e harness in-repo; the web Playwright suite covers web). Verify end-to-end against a live backend: send, stream, stop, reopen, resume after backgrounding.
- *No new backend tests* — the backend is unchanged.

## Plan Challenge Results

### 1. Extendability & Scalability: PASS
Vertical-slice phases bolt deferred rich-chat onto a stable core; mobile-native contracts grow incrementally; `usePacketDisplay` extends one branch per feature; long histories handled by `onStartReached` pagination + FlashList v2. The only tunables (~50ms batch, 3s status poll) are config, not hardcoded ceilings.

### 2. Fragility: CONCERN (identified + hardened)
Three brittle points, each already mitigated in the plan: (a) **web↔mobile chat duplication** — the parser/tree/history now live in two places, so a backend protocol change must be mirrored in both → annotate the mobile copies as mirroring their web origin, and re-extract to `@onyx-ai/shared` only if drift actually bites (pre-production, protocol stable, so this is cheap); (b) **external-dep risk** (`expo/fetch` device streaming, `streamdown` on RN 0.85) → named fallbacks (XHR→same buffer; `react-native-marked`) + **two early spikes gate P3**; (c) **stream/session cross-talk** → port web's `stillCurrent`/`AbortController` guards so a backgrounded stream can't write into the wrong session. Acceptable with these in place.

### 3. Industry Standard: VERIFIED (fresh web search, June 2026)
- `expo/fetch` is the **default global fetch on iOS/Android in SDK 56** (released 2026-05-21) and supports incremental `response.body.getReader()` — the standard RN streaming path. ([docs.expo.dev/versions/latest/sdk/expo](https://docs.expo.dev/versions/latest/sdk/expo/), [expo/expo#21710](https://github.com/expo/expo/discussions/21710))
- **FlashList v2 non-inverted + `maintainVisibleContentPosition` + `startRenderingFromBottom`** is the documented v2 chat pattern (inverted deprecated; use `onStartReached` for older messages). Known caveats #1844/#2050/#1872 are exactly the ones the plan flagged. ([flash-list v2-changes](https://shopify.github.io/flash-list/docs/v2-changes/), [#2050](https://github.com/Shopify/flash-list/issues/2050))
- **`react-native-keyboard-controller`** is the recommended 2026 chat-input solution (`KeyboardStickyView`/`KeyboardChatScrollView`); Expo itself calls `KeyboardAvoidingView` prototype-only. ([Expo keyboard-handling](https://docs.expo.dev/guides/keyboard-handling/), [keyboard-controller](https://kirillzyusko.github.io/react-native-keyboard-controller/docs/guides/components-overview))
- **`react-native-streamdown`** (Software Mansion, worklet-based) is the current streaming-markdown choice; the ecosystem has moved past plain `react-native-markdown-display` for token-by-token AI output. ([react-native-streamdown](https://github.com/software-mansion-labs/react-native-streamdown))

### 4. Fact Check: PASS (one nuance refined)
All "best-practice" claims verified above. **Refinement**: the FormData-causes-OOM framing is more nuanced than stated — RN `FormData` with a **file-URI reference** (not base64) also streams and avoids the memory blow-up for small/medium files; `expo-file-system` `createUploadTask`'s real edge is **upload progress + very large files**. Plan stands (we want progress + large-doc safety), but per-phase P7/P8 should treat `createUploadTask` as the choice *for progress/large files*, not because FormData is universally broken. ([Expo FileSystem](https://docs.expo.dev/versions/latest/sdk/filesystem/))

### 5. Maintainability: PASS
Mirrors the web structure and the existing mobile patterns (`apiFetch`, `query-keys`, zustand, UI primitives); clean shared/mobile boundary; each phase is a coherent, independently-reviewable slice. Minor: the `usePacketDisplay` (mobile) vs `usePacketProcessor` (web) naming divergence is intentional and documented.

### 6. Patch vs. Fix: PROPER FIX
This is a genuine feature build against the real backend contract, not a workaround. Transport choice (`expo/fetch`), batching, and status-polling are standard patterns, not symptom-masking. No patch decision to surface.

**Verdict: proceed.** No failed checks; Fragility concerns are pre-mitigated; one fact-check nuance folded into P7/P8 guidance. The two pre-P3 spikes are the only hard gate.
