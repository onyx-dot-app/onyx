> Status: active · Task: mobile-chat · Source plan: 04-implementation-plan.md

# Mobile Chat Port — PR Roadmap

> **How to use this.** Each PR below is an independently-mergeable slice (~500-700 LOC incl. tests) that leaves `main` building and the app usable. **Before implementing any PR, open a fresh session and run the "Before you start (grill on)" checklist for that PR with the owner — confirm the key decisions and re-read the relevant web files — THEN code.** This roadmap is intentionally high-level; the deep detail for each slice is produced in that per-PR session, not here. Product is pre-production, so no feature flags are required; the chat entry point is added in PR 1 but `send` stays disabled until PR 3.

## Overview

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 0 | `chore(mobile): chat streaming + markdown spikes` | ~150 (throwaway) | — | Prove `expo/fetch` streaming on device + `react-native-streamdown` on RN 0.85; pick fallbacks. **Hard gate for PR 3.** |
| 1 | `feat(mobile): authed chat shell + sessions history` | ~550 | PR 0 | `(app)` route group, history list (real data), chat screen scaffold; no streaming. |
| 2 | `feat(shared): chat contracts + NDJSON parser + message tree` | ~600 | PR 1 | Pure contracts + parser + tree in `@onyx-ai/shared`; web re-pointed; unit-tested. |
| 3 | `feat(mobile): core chat — send, stream, markdown` | ~700 | PR 2 | **Headline slice** — working streaming chat vs default agent. |
| 4 | `feat(mobile): resume in-flight run + history pagination` | ~450 | PR 3 | Reopen/resume live runs; paginate older messages; auto-name. |
| 5 | `feat(mobile): agent selection` | ~550 | PR 3 | Browse + pick an agent; starter prompts; implicit `persona_id`. |
| 6 | `feat(mobile): projects — list, select, chat-within` | ~550 | PR 3 | Browse projects, open one, chat scoped to it. |
| 7 | `feat(mobile): project file management` | ~650 | PR 6 | Add/remove project files via pickers + streaming upload + status. |
| 8 | `feat(mobile): input-bar attachments` | ~550 | PR 7 | Attach documents/photos to a message; send-gating on indexing. |
| 9a | `feat(mobile): citations & sources` | ~500-700 | PR 3 | (deferred rich-chat) |
| 9b | `feat(mobile): agentic reasoning timeline` | ~500-700 | PR 3 | (deferred rich-chat) |
| 9c | `feat(mobile): regenerate / edit / feedback` | ~500-700 | PR 3 | (deferred rich-chat) |
| 9d | `feat(mobile): follow-up suggestions` | ~400 | PR 3 | (deferred rich-chat) |
| 9e | `feat(mobile): image generation rendering` | ~500 | PR 3 | (deferred rich-chat) |

## Sequence

```
PR0 spike ─► PR1 shell+history ─► PR2 shared parser/tree/contracts ─► PR3 CORE CHAT (walking skeleton)
                                                                          │
                        ┌──────────────────────┬──────────────────────────┼───────────────┐
                        ▼                      ▼                          ▼                 ▼
                  PR4 resume/paginate     PR5 agents              PR6 projects        PR9a–9e rich-chat
                                                                       │              (each independent,
                                                                       ▼               any order after PR3)
                                                                  PR7 project files
                                                                       │
                                                                       ▼
                                                                  PR8 input attachments
```
PR 3 is the spine; PR 4/5/6 and all of PR 9 fan out from it independently. PR 7→8 is the only deeper chain (attachments reuse the project uploader).

---

## PR 0 — Streaming + markdown spikes (throwaway)
- **Goal:** De-risk the two external unknowns before committing to PR 3's design.
- **Scope (in):** A dev-build branch that (1) POSTs to `/api/chat/send-chat-message` via `expo/fetch` and logs parsed packets from `response.body.getReader()` on a **physical device**; (2) renders streamed markdown via `react-native-streamdown`. Record outcomes + chosen fallbacks.
- **Out of scope:** Any real UI, state, or shared code. This is throwaway/spike code (may merge as a documented spike or stay on a branch).
- **Files:** a scratch screen + notes appended to this doc. No production surface.
- **Est. size:** ~150 LOC throwaway.
- **Depends on:** —
- **Feature-flag state:** N/A.
- **Tests on merge:** Manual device run; outcomes documented (works / fallback needed).
- **Before you start (grill on):** Which physical devices/OS versions to validate? Is the dev client already provisioned (iOS signing / Android)? Acceptable fallback if `streamdown` fails (`react-native-marked`) — confirm.
- **Drift checkpoint:** If `expo/fetch` lacks `response.body.getReader()` on device, switch PR 3's transport to XHR-progress feeding the *same* shared buffer — re-confirm before PR 2 finalizes the parser seam.

### Step 1 status — streaming spike (in progress)
- **Decisions (grilled 2026-06-25):** iOS Simulator (localhost backend); in-app temporary dev screen reusing real session/token; streaming proven first, `streamdown` config deferred to Step 2.
- **Scaffold (throwaway, delete after PR 3):** `mobile/src/app/dev-stream.tsx` (the probe screen) + a temporary "Dev: streaming spike (PR0)" button in `mobile/src/app/index.tsx`. No new deps, no native config. Reuses `apiFetch` for `create-chat-session` and swaps in `expo/fetch` only for `send-chat-message`; body mirrors `web/src/app/app/services/lib.tsx` `sendMessage()`.
- **What it reports on screen:** base URL · HTTP status · `response.body` present (Y/N) · `getReader()` present (Y/N) · packets parsed · duration · accumulated answer · last-40 packet types · any error.
- **Results (run 1, 2026-06-25 — HTTP 422, body-contract findings before streaming reached):**
  - [x] `expo/fetch` POST + secure-store bearer + `create-chat-session` (via `apiFetch`) all work — a real backend response came back through `expo/fetch`.
  - [x] `parent_message_id: null` **accepted** for a first message (not flagged).
  - [x] **Finding:** backend `MessageOrigin` enum has **no `"mobile"` value** — allowed: `webapp | chrome_extension | api | slackbot | widget | discordbot | unknown | unset`. Spike now sends `origin: "unknown"`. **PR 3 decision:** add a `"mobile"` origin to the backend enum (small change, better analytics) vs keep `"unknown"`.
  - [x] (run 2, after the `origin` fix) **HTTP 200**; `response.body` present **YES**; **`getReader()` present YES** → **PR 3 transport = `expo/fetch`, no XHR fallback needed.**
  - [x] (run 2) NDJSON packets parse + arrive incrementally — 16 packets: `message_start` → N×`message_delta` → `stop`.
  - [x] (run 2) message text accumulates from `message_start`/`message_delta` — rendered "Hello, Subash! 👋 Hope you're having a great day!"

- **✅ Step 1 verdict: GO.** `expo/fetch` streams NDJSON on the iOS sim; the shared-parser design holds. Two carry-forward notes:
  - **Mixed packet shapes:** the stream mixes `{placement, obj:{type}}` wrappers with top-level control objects (`{type: ...}` at root, e.g. message-id-info — surfaced as `<<no-type>>` in the probe). PR 2 parser/types must handle both (web already does).
  - **Emoji glyph:** 👋 rendered as tofu in Hanken Grotesk — PR 3 markdown renderer needs an emoji-capable font fallback (cosmetic).
- **Scaffold removed:** the throwaway `dev-stream.tsx` + the temporary home-screen button were deleted after the run (findings captured above); `index.tsx` is back to its committed state.
- **Step 2 (`react-native-streamdown` build/render on RN 0.85) NOT run** — moved into **PR 3 pre-work** (its drift checkpoint / "before you start" gate), since PR 1 and PR 2 are markdown-independent. Fallback `react-native-marked` if it won't build.

> **PR 0 status: streaming spike COMPLETE (GO).** Markdown build-check carried into PR 3 pre-work. PR 1 and PR 2 are unblocked.

## PR 1 — Authed chat shell + sessions history
- **Goal:** A reachable, authed chat surface showing real chat history; navigation works end-to-end with no streaming yet.
- **Scope (in):** `(app)` expo-router group under `AuthGate`; new-chat home (empty state); `chat/[id]` scaffold (static input shell, `send` disabled); history list via a TanStack Query hook over the sessions-list endpoint; `chatSessions`/`chatSession` query keys; sidebar wired to sessions; **add chat session/message query keys to the `dehydrateOptions` PII-exclusion list (`mobile/src/query/client.ts`) before any history persists to MMKV — required, not optional.**
- **Out of scope:** Streaming, message rendering, agents, projects, attachments.
- **Files:** `mobile/src/app/(app)/_layout.tsx` (new), `app/(app)/index.tsx` (new), `app/(app)/chat/[id].tsx` (new, scaffold), `app/(app)/history.tsx` (new), `app/_layout.tsx` (modified: mount group), `api/chat/sessions.ts` (new, list only), `api/query-keys.ts` (modified), sidebar (modified).
- **Est. size:** ~550 LOC.
- **Depends on:** PR 0.
- **Feature-flag state:** N/A — chat entry visible; `send` disabled until PR 3.
- **Tests on merge:** RN Testing Library — history list renders mocked sessions; navigation to `chat/[id]` works; empty state shows. Provably working: real history list on device.
- **Before you start (grill on):** Exact sessions-list endpoint + response shape + pagination (e.g. `get-user-chat-sessions` vs project-scoped). Navigation model — stack vs tabs vs drawer; where do new-chat / history / projects live; what's the sidebar's role vs a tab bar? What does the empty `chat/[id]` scaffold show?
- **Drift checkpoint:** Confirm the sidebar primitives (already merged) are the intended host for the history list.

## PR 2 — Shared chat contracts + NDJSON parser + message tree
- **Goal:** Establish the shared pure seam (Approach C) and prove web parity — no mobile behavior change yet.
- **Scope (in):** `@onyx-ai/shared/contracts/{streaming(minimal),chat,files}.ts`; `@onyx-ai/shared/utils/{ndjson,messageTree,chatHistory}.ts` lifted from the already-pure web code (split `handleSSEStream` → pure buffer + platform reader); re-point `web/src/lib/search/streamingUtils.ts` + `web/src/app/app/services/messageTree.ts` imports to shared; rebuild dist. Unit tests for parser + tree.
- **Out of scope:** Mobile consumption (that's PR 3), file-descriptor + project + agent contracts (their phases).
- **Files:** shared `contracts/*` + `utils/*` (new) + `contracts/index.ts`/`utils/index.ts` (modified); `web/src/lib/search/streamingUtils.ts` (modified: import shared), `web/src/app/app/services/messageTree.ts` (modified: re-export shared); shared tests (new).
- **Est. size:** ~600 LOC (incl. tests).
- **Depends on:** PR 1.
- **Feature-flag state:** N/A.
- **Tests on merge:** Jest unit — NDJSON buffering (partial lines, brace-recovery, heartbeat passthrough, trailing flush) + `upsertMessages`/`getLatestMessageChain`/`processRawChatHistory`. Web parity via existing `test_chat_stream`. Provably working: web still streams through shared code.
- **Before you start (grill on):** The exact minimal `PacketType` subset to include now (which `type` strings). How to split `handleSSEStream` without regressing the brace-recovery fallback. Which `messageTree` functions/types move vs stay — and whether the minimal shared `Message` type can avoid dragging `OnyxDocument`/multi-model fields. How dist rebuild + mobile `file:` relink is wired in dev and CI.
- **Drift checkpoint:** Re-confirm PR 0's transport outcome — the parser must accept either a `getReader()` stream or an XHR-progress feed.

## PR 3 — Core chat: send → stream → markdown
- **Goal:** The walking skeleton — a user can send a message to the default agent and watch a markdown answer stream in, then stop.
- **Scope (in):** `mobile/src/api/chat/stream.ts` (`expo/fetch` generator + shared buffer + `AbortController`); `state/chatSessionStore.ts` (zustand, not persisted); `hooks/useChatController.ts` (create session at `persona_id=0`, optimistic nodes via shared builders, drive stream, ~50ms batched flush, stop); the **packet-renderer foundation** — `components/chat/renderers/registry.ts` (`MessageRenderer` contract + `findRenderer` dispatch, mirroring web `renderMessageComponent`) with **only** `renderers/MessageTextRenderer.tsx` registered + `hooks/usePacketDisplay.ts` (group + dispatch); `components/chat/{MessageList,MessageRow,StreamingMarkdown,InputBar}.tsx`; hydrate existing sessions via `GET get-chat-session` + shared `processRawChatHistory`; enable `send`.
- **Out of scope:** Resume, agents, projects, attachments, all rich-chat packets/renderers, the `AgentTimeline` composition layer (built in PR 9b). **Build the dispatch seam, not the rich renderers.**
- **Files:** the above (all new, incl. `components/chat/renderers/{registry.ts,MessageTextRenderer.tsx}`) + `chat/[id].tsx` (modified: real screen) + `create-chat-session` call in `api/chat/sessions.ts` (modified).
- **Est. size:** ~700 LOC — at the band. The renderer registry adds ~nothing over a flat reducer. If over, split `StreamingMarkdown` + perf memoization into a PR 3b.
- **Depends on:** PR 2.
- **Feature-flag state:** N/A — chat now fully functional for the default agent.
- **Tests on merge:** RN Testing Library with a **mocked packet stream** — tokens render incrementally; stop aborts; reopening hydrates history. Manual device run vs live backend.
- **Before you start (grill on):** **PR 0 spike outcomes (HARD GATE)** — streaming is proven (`expo/fetch` + `getReader()`); **still owed: run the deferred `react-native-streamdown` build/render spike on RN 0.85 here (fallback `react-native-marked`).** Use `origin: "unknown"` (or decide whether to add a `"mobile"` value to the backend `MessageOrigin` enum). Exact send-body fields for the minimal core (`origin` value; which fields null/omitted: `internal_search_filters`, `deep_research`, `allowed_tool_ids`, `forced_tool_id`, `llm_override`). Optimistic node-id scheme + `parent_message_id` semantics (-1 vs null vs id). Stop semantics (immediate UI vs wait for `STOP`). Markdown styling → NativeWind token mapping. Where the chosen markdown lib's dev-build config lives. **Renderer contract shape** — confirm the `MessageRenderer<TPacket,TState>` interface (study web's `messageComponents/interfaces.ts` + `renderMessageComponent.tsx`) so PR 9's renderers slot in cleanly; decide whether packet-grouping is mobile-only or a shared pure helper.
- **Drift checkpoint:** If the spike forced the XHR fallback, confirm `stream.ts` shape before coding the controller.

## PR 4 — Resume in-flight run + history pagination
- **Goal:** Backgrounding mid-answer and reopening resumes the live run; long histories paginate; sessions auto-name.
- **Scope (in):** `hooks/useChatSessionController.ts` resume tail (`resume-stream?cursor=`) with a `stillCurrent` guard; `onStartReached` older-message pagination (guard short-list); rename-on-first-message + history refresh.
- **Out of scope:** Everything else.
- **Files:** `useChatSessionController.ts` (new), `MessageList.tsx` (modified: pagination), `useChatController.ts` (modified: rename hook).
- **Est. size:** ~450 LOC.
- **Depends on:** PR 3.
- **Feature-flag state:** N/A.
- **Tests on merge:** RN Testing Library — resume re-attaches to a mocked live run; pagination loads older mocked pages; guard prevents cross-session writes.
- **Before you start (grill on):** `resume-stream` cursor semantics + `current_run` shape; how to detect a live run on open. Auto-name endpoint + trigger timing. Which endpoint/params page older messages.
- **Drift checkpoint:** Confirm resume is still wanted for v1 (it's polish; could defer if scope tightens).

## PR 5 — Agent selection
- **Goal:** Browse available agents, pick one, start a chat with it; use its starter prompts.
- **Scope (in):** `@onyx-ai/shared/contracts/agents.ts` (MinimalAgent subset); `api/chat/agents.ts` (`GET /api/persona`); `components/chat/AgentPicker.tsx` (bottom sheet: avatar/name/description); selection sets `persona_id` at create; starter prompts on the empty screen. No creation/editing.
- **Out of scope:** Agent CRUD, per-agent tool preferences UI.
- **Files:** shared `contracts/agents.ts` (new), `api/chat/agents.ts` (new), `components/chat/AgentPicker.tsx` (new), empty-state screen (modified), `useChatController.ts` (modified: pass `persona_id`).
- **Est. size:** ~550 LOC.
- **Depends on:** PR 3.
- **Feature-flag state:** N/A.
- **Tests on merge:** RN Testing Library — agents list renders; selecting threads `persona_id` into `create-chat-session`; starter prompt submits.
- **Before you start (grill on):** Which list endpoint (`/api/persona` vs paginated `/agents`) + filtering (`is_listed`/`builtin`/featured). Avatar rendering: `icon_name` mapping + `uploaded_image_id` fetch URL (needs bearer). Picker UX (sheet vs screen; launch point). Default agent (id 0) + `disable_default_assistant` handling.
- **Drift checkpoint:** Confirm select-only is still the scope (no quick-create).

## PR 6 — Projects: list, select, chat-within
- **Goal:** Browse projects, open one, see its chats, start/continue a chat scoped to it.
- **Scope (in):** `@onyx-ai/shared/contracts/projects.ts` (Project, ProjectFile, UserFileStatus); `api/chat/projects.ts` (list + detail/files, read-only); `app/(app)/projects/{index,[id]}.tsx`; "new chat in project" passes `project_id` to `create-chat-session`; sidebar surfaces projects.
- **Out of scope:** Project create/rename/delete; file add/remove (PR 7).
- **Files:** shared `contracts/projects.ts` (new), `api/chat/projects.ts` (new), `projects/index.tsx` + `projects/[id].tsx` (new), sidebar (modified), `useChatController.ts` (modified: `project_id`).
- **Est. size:** ~550 LOC.
- **Depends on:** PR 3.
- **Feature-flag state:** N/A.
- **Tests on merge:** RN Testing Library — projects list renders; opening shows scoped chats; new chat carries `project_id`.
- **Before you start (grill on):** Project-list endpoint + how project chats are scoped (filter sessions by `project_id` vs the `chat_sessions[]` in the snapshot). Show project instructions? token-count? Navigation placement (sidebar vs tab). Read-only confirmation (no CRUD).
- **Drift checkpoint:** Re-confirm "no project CRUD" still holds.

## PR 7 — Project file management
- **Goal:** Add documents/photos to a project, watch indexing, and remove them.
- **Scope (in):** `api/files/upload.ts` (`expo-file-system` `createUploadTask`, MULTIPART, field `files`, bearer, `onProgress`); `state/uploadStore.ts` + 3s status polling; `expo-document-picker` + `expo-image-picker` entry points + asset normalization; link/unlink; file list UI with status chips. app config plugin entries (photo permission strings).
- **Out of scope:** Per-message attachments (PR 8); camera.
- **Files:** `api/files/upload.ts` (new), `state/uploadStore.ts` (new), picker helpers (new), `projects/[id].tsx` (modified: files section), `app.json`/config plugin (modified).
- **Est. size:** ~650 LOC.
- **Depends on:** PR 6.
- **Feature-flag state:** N/A.
- **Tests on merge:** RN Testing Library — picker→normalize→upload mocked; progress + status chips reflect store; link/unlink update the list.
- **Before you start (grill on):** Upload endpoint field names + `temp_id_map` usage; status-poll cadence + terminal states (`COMPLETED/FAILED/SKIPPED`). Picker config: allowed MIME types, multiple selection, size-limit source. Config-plugin entries (`NSPhotoLibraryUsageDescription` etc.; `microphonePermission:false`). Link/unlink vs delete semantics (delete cascades?). **Fact-check nuance:** use `createUploadTask` for progress/large files; FormData-with-URI is fine for small — confirm the threshold/approach.
- **Drift checkpoint:** Confirm dev-build rebuild after adding native picker deps.

## PR 8 — Input-bar attachments (per-message)
- **Goal:** Attach documents/photos to an individual message and send them.
- **Scope (in):** Reuse PR 7 pickers/uploader from the input bar; `components/chat/AttachmentChips.tsx`; extract `@onyx-ai/shared/utils/fileDescriptors.ts`; build `file_descriptors[]` on send; **gate send until indexed** (`token_count != null`); image preview via `GET /api/chat/file/{file_id}`. Camera deferred.
- **Out of scope:** Camera capture.
- **Files:** shared `utils/fileDescriptors.ts` (new) + web `fileUtils.ts` (modified: re-point), `components/chat/AttachmentChips.tsx` (new), `InputBar.tsx` (modified), `useChatController.ts` (modified: attach descriptors).
- **Est. size:** ~550 LOC.
- **Depends on:** PR 7.
- **Feature-flag state:** N/A.
- **Tests on merge:** RN Testing Library — attach→chip→send-gating blocks until indexed; `file_descriptors[]` built correctly; image preview renders.
- **Before you start (grill on):** Send-gating UX while indexing + error surfacing for `FAILED`. `file_descriptors` field mapping (`file_id`→`id`, `chat_file_type`→`type`, `id`→`user_file_id`). Image-preview auth (`GET /api/chat/file/{id}` needs bearer in `<Image>` — header vs signed URL). Reuse vs minor duplication with PR 7's uploader.
- **Drift checkpoint:** This completes the locked scope — confirm before starting whether camera moves in-scope.

## PR 9a–9e — Deferred rich-chat (each its own phase)
- **Goal:** Enrich the working core, one independent feature at a time: **9a** citations/sources · **9b** agentic reasoning timeline (reasoning/search/tool sub-steps) · **9c** regenerate/edit/feedback · **9d** follow-up suggestions · **9e** image-generation rendering.
- **Scope (each):** Add the relevant rich packet types to `@onyx-ai/shared/contracts/streaming.ts`, **register a new `MessageRenderer` into the PR 3 dispatch** (`components/chat/renderers/`), and add the RN UI. The dispatch seam from PR 3 means none of these touch the core display path. **9b (agentic timeline) additionally builds the `AgentTimeline` composition layer** (mirrors web's `AgentTimeline`/`TimelineRendererComponent`); 9b's reasoning/search/tool sub-renderers and any later timeline renderers plug into it. Web's `usePacketProcessor` stays web-only.
- **Est. size:** ~400–700 LOC each.
- **Depends on:** PR 3 (+ PR 5/6/7/8 where a feature interacts, e.g. citations over project docs).
- **Tests on merge:** RN Testing Library with a mocked packet stream containing the new packet types.
- **Before you start (grill on):** **Treat each as its own mini feature-flow** — re-run research/design for that feature (the packet shapes, the web UI it mirrors, the RN rendering). Confirm priority order (likely 9a citations first — most product value).
- **Drift checkpoint:** Re-prioritize against product needs at the time; these are explicitly post-core and independently schedulable.
