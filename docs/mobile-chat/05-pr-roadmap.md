> Status: active · Task: mobile-chat · Source plan: 04-implementation-plan.md

# Mobile Chat Port — PR Roadmap

> **How to use this.** Each PR below is an independently-mergeable slice (~500-700 LOC incl. tests) that leaves `main` building and the app usable. **Before implementing any PR, open a fresh session and run the "Before you start (grill on)" checklist for that PR with the owner — confirm the key decisions and re-read the relevant web files — THEN code.** This roadmap is intentionally high-level; the deep detail for each slice is produced in that per-PR session, not here. Product is pre-production, so no feature flags are required; the chat entry point is added in PR 1 but `send` stays disabled until PR 3.

> **⚠️ DECISION OVERRIDE (2026-06-29) — chat logic is NOT shared.** The owner decided **not** to extract any chat-domain code into `@onyx-ai/shared`, to keep that design-system/Opal package free of ~500–1000 lines of chat business logic. This reverses Approach C's shared-seam plan **for chat only**. Consequences, applied everywhere below: (1) **Mobile owns its own copies** of the NDJSON parser, message tree, packet/chat/file contracts, and `processRawChatHistory` under **`mobile/src/chat/`**. Wherever this roadmap or `03-detailed-design.md` says `@onyx-ai/shared/contracts/*` or `@onyx-ai/shared/utils/*` for chat code, read it as **`mobile/src/chat/*`**. (2) **Web is left completely untouched** — no import re-points, no shims, no web parity step. The accepted tradeoff: the parser/tree logic now lives in both web and mobile and can drift. (3) `@onyx-ai/shared` continues to receive only cross-platform **design** primitives (tokens, typography, interactive contracts) per the unchanged design-token policy. *(This is about NOT sharing chat **logic** — it is unrelated to **visual** parity, which is required; see the next callout.)*

> **🎯 WEB-PARITY PRINCIPLE (2026-06-30) — applies to every component from PR 4 onward (PR 0–3 done).** Each mobile component/screen must look and behave like its **web counterpart** as closely as the platform allows — layout, spacing (remember mobile spacing is **pixel-valued**, so translate web Tailwind steps, don't copy class numbers), sizing, color, and interaction. Pixel/behaviour-exact is the goal; small platform-driven differences are fine. Concretely, in order:
> 1. **Reuse the parity primitives first.** `@/components/ui/text` `Text` and `@/components/ui/button` `Button` are already built to **full web parity** — compose them (and the other `components/ui/*`: `text-input`, `icon`, `separator`) instead of hand-rolling raw RN `Text` / `Pressable` / `TextInput`.
> 2. **Before building anything new, check what already exists** — scan `components/ui/*`, `components/chat/*`, the `@/icons/*` set, and the shared design tokens for something that already covers it (or is close).
> 3. **If web parity needs a primitive mobile doesn't have yet, STOP and ASK the owner** whether to port it — use the `port-web-component-to-mobile` skill for a pixel/behaviour-exact RN port. **Never hand-roll a divergent lookalike** to avoid the ask.
> 4. **Document the divergences.** Every PR's "As built" note must explicitly list **what mobile renders differently from web and why** (intentional simplification, platform constraint, deferred-to-a-later-PR feature), so reviewers and the owner can see the gaps at a glance.
>
> *(Owner is handling **sidebar** parity separately, out of the chat PRs.)*

## Overview

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 0 | `chore(mobile): chat streaming + markdown spikes` | ~150 (throwaway) | — | Prove `expo/fetch` streaming on device + `react-native-streamdown` on RN 0.85; pick fallbacks. **Hard gate for PR 3.** |
| 1 | `feat(mobile): authed chat shell + sessions history` | ~550 | PR 0 | `(app)` route group, history list (real data), chat screen scaffold; no streaming. |
| 2 | `feat(mobile): native chat data layer` ✅ | ~550 | PR 1 | Mobile-native NDJSON parser + core packet/chat/file **contracts** + message tree + `processRawChatHistory` in `mobile/src/chat/`; jest unit-tested. **Web untouched; nothing shared.** |
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
PR0 spike ─► PR1 shell+history ─► PR2 mobile-native chat data layer (parser+contracts+tree+history) ─► PR3 CORE CHAT (walking skeleton)
                                                                                                          │
                        ┌──────────────────────┬────────────────────────────────────────────────────────────┼───────────────┐
                        ▼                      ▼                                                            ▼                 ▼
                  PR4 resume/paginate     PR5 agents                                                PR6 projects        PR9a–9e rich-chat
                                                                                                         │              (each independent,
                                                                                                         ▼               any order after PR3)
                                                                                                    PR7 project files
                                                                                                         │
                                                                                                         ▼
                                                                                                    PR8 input attachments
```
PR 3 is the spine; PR 4/5/6 and all of PR 9 fan out from it independently. PR 7→8 is the only deeper chain (attachments reuse the project uploader). PR 2 is the mobile-native pure data layer (NDJSON parser + core contracts + message tree + history) — written independently in mobile; web keeps its own copies, nothing is shared.

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
- **As built (2026-06-26, "match web"):** Nav = the existing **Stack + foldable sidebar overlay** (no tab bar). The **sidebar IS the history** — a flat "Recents" list (mirrors web's `RecentsSection`), so **no separate `history.tsx`** screen. The demo `mobile/src/app/index.tsx` was replaced: the authed home moved into `(app)/index.tsx` (route groups are path-transparent, so `(app)/index.tsx` = `/`), and the sidebar (`components/chat/AppSidebar.tsx`) is mounted in `(app)/_layout.tsx` to overlay every authed screen. Data: `api/chat/sessions.ts` `useChatSessions` = `useInfiniteQuery` over `GET /chat/get-user-chat-sessions?page_size=50[&before=<last.time_updated>]&only_non_project_chats=true` (mirrors web's `useSWRInfinite` cursor pagination); `name`-null rows fall back to web's `"New Chat"`. Landing mirrors web's `WelcomeMessage` (Onyx logo + random greeting from `["How can I help?", "Let's get started."]`); the `chat/[id]` scaffold + landing share a disabled `InputBar` shell (send lands in PR 3). New files: `(app)/{_layout,index,chat/[id]}.tsx`, `components/chat/{AppSidebar,ChatSessionList,ChatHeader,InputBar,WelcomeMessage}.tsx`, `api/chat/sessions.ts`, `lib/greetings.ts`; modified `api/query-keys.ts` + `query/client.ts` (PII exclusion). **Web untouched.** Verified: mobile `tsc` clean, lint clean, 83 jest tests pass (6 new — `ChatSessionList` + `useChatSessions`). Device run vs a live backend is the remaining manual check.

## PR 2 — Mobile-native chat data layer  ✅ IMPLEMENTED (2026-06-29)

> **Decision (2026-06-26, revised — no shared chat code).** The chat pure layer — NDJSON parser, message tree, `processRawChatHistory`, and all chat/streaming/file contracts — is written **natively in mobile**, while web keeps its own existing copies. **Nothing chat-related enters `@onyx-ai/shared`.** We first considered sharing the whole pure layer, then narrowed it to just the ~40-line NDJSON parser, and ultimately dropped even that: the shared-package machinery (a `@onyx-ai/shared` util + a web `streamingUtils.ts` re-point + a jest module-mapper + dist/build coupling) is more moving parts than the ~200 lines of duplication it removes. Pre-production, the backend NDJSON framing + message-threading are stable, so drift risk is low and cheap to fix if it ever bites (re-extract then). **Web is completely untouched by the mobile chat port.** (`@onyx-ai/shared` stays design tokens + the existing interactive/typography contracts + `numbers`/`format` utils.)

- **Goal:** Establish the pure, unit-tested core that PR 3's transport + UI build on. **Mobile-local — nothing extracted to `@onyx-ai/shared`; web is untouched.**
- **Scope (in) — as built:** `mobile/src/chat/`:
  - `streamingModels.ts` — minimal core packet contracts: `PacketType` (subset: `message_start/delta/end`, `stop`, `section_end`, `error`), `MessageStart/Delta/End`, `Stop`/`StopReason`, `SectionEnd`, `PacketError`, `ChatHeartbeat`, `Placement`, `Packet`, `ObjTypes`, root `MessageResponseIDInfo`. No `OnyxDocument`/rich types.
  - `interfaces.ts` — minimal `Message` (no documents/citations/multi-model/toolCall), `MessageType`, `ChatState` (4-member core), `FileDescriptor`, `ChatFileType`, and the minimal session-snapshot input types `BackendMessage` + `BackendChatSession`.
  - `ndjson.ts` — `createNdjsonBuffer<T>()` (`pushChunk`/`flush`), the pure NDJSON line-buffer split out of web's `handleSSEStream` (brace-recovery + trailing-flush preserved; no reader/decoder/abort).
  - `messageTree.ts` — `upsertMessages`/`getLatestMessageChain`/`getMessageByMessageId`/`getLastSuccessfulMessageId`/`setMessageAsLatest`/`buildEmptyMessage`/`buildImmediateMessages` + `SYSTEM_NODE_ID`/`MessageTreeState`, ported ~verbatim from web (typed on the minimal `Message`).
  - `chatHistory.ts` — `processRawChatHistory(BackendMessage[], Packet[][])` → tree, ported from web; mobile-local it just emits minimal `Message`s (no rich types), aligning packets to assistant messages by ordinal.
  - `__tests__/{ndjson,messageTree,chatHistory}.test.ts` — 31 jest unit tests.
- **Out of scope (deferred to PR 3):** the stream transport (`expo/fetch` generator) and the send/create/session **request** contracts (transport-consumed).
- **Files:** the six `mobile/src/chat/*` files above (all new). No shared-package or web changes.
- **Est. size:** ~550 LOC (incl. tests).
- **Depends on:** — (independent of PR 1; can land in parallel).
- **Feature-flag state:** N/A.
- **Tests on merge:** Jest unit (`bunx jest src/chat`) — NDJSON buffering (partial lines, brace-recovery, heartbeat passthrough, trailing flush, mixed wrapped/root shapes) + `upsertMessages`/`getLatestMessageChain`/`getMessageByMessageId`/`getLastSuccessfulMessageId`/`setMessageAsLatest`/builders + `processRawChatHistory` (nodeId reuse, child sort, packet alignment, error mapping, chain traversal). **All 31 passing.**
- **Resolved decisions (from the grill):** `PacketType` core subset = `message_start/delta/end · stop · section_end · error` (+`chat_heartbeat` interface, +root `message_id_info`). `handleSSEStream` split = pure `createNdjsonBuffer` (buffer + split + JSON.parse + flat-brace recovery + trailing flush) vs platform reader/decoder/abort in PR 3. Minimal `Message` keeps only the ~10 structural/core fields (drops `toolCall`/`documents`/`citations`/multi-model). No dist/relink wiring needed (mobile-local).
- **Drift checkpoint:** PR 0's transport outcome stands (`expo/fetch` + `getReader()`); `createNdjsonBuffer` is fed decoded text by whatever transport PR 3 uses, so it accepts either a `getReader()` stream or an XHR-progress feed unchanged.
- **Kept faithful to web (Greptile P1 review):** `buildEmptyMessage`'s `-Date.now()-offset` temp ids (collision-safe via send-gating) and `getLastSuccessfulMessageId` returning the synthetic `-3` are intentional, matching web. **PR 3 carry-forward:** mobile's send flow must port web's call-site `-3 → null` guard (`useChatController.ts`: `parentId === SYSTEM_MESSAGE_ID ? null : parentId`) so the synthetic id is never sent as `parent_message`.

## PR 3 — Core chat: send → stream → markdown  ✅ IMPLEMENTED (2026-06-30)
- **Goal:** The walking skeleton — a user can send a message to the default agent and watch a markdown answer stream in, then stop.
- **Scope (in):** `mobile/src/api/chat/stream.ts` (`expo/fetch` generator + the **PR 2 mobile-native NDJSON parser** + `AbortController`); `state/chatSessionStore.ts` (zustand, not persisted); `hooks/useChatController.ts` (create session at `persona_id=0`, optimistic nodes via the **PR 2 builders**, drive stream, ~50ms batched flush, stop); the **packet-renderer foundation** — `components/chat/renderers/registry.ts` (`MessageRenderer` contract + `findRenderer` dispatch, mirroring web `renderMessageComponent`) with **only** `renderers/MessageTextRenderer.tsx` registered + `hooks/usePacketDisplay.ts` (group + dispatch); `components/chat/{MessageList,MessageRow,StreamingMarkdown,InputBar}.tsx`; hydrate existing sessions via `GET get-chat-session` + the **PR 2 `processRawChatHistory`**; enable `send`.
- **Out of scope:** Resume, agents, projects, attachments, all rich-chat packets/renderers, the `AgentTimeline` composition layer (built in PR 9b). **Build the dispatch seam, not the rich renderers.**
- **Files:** the above (all new, incl. `components/chat/renderers/{registry.ts,MessageTextRenderer.tsx}`) + `chat/[id].tsx` (modified: real screen) + `create-chat-session` call in `api/chat/sessions.ts` (modified).
- **Est. size:** ~700 LOC — at the band. The renderer registry adds ~nothing over a flat reducer. If over, split `StreamingMarkdown` + perf memoization into a follow-up slice.
- **Depends on:** PR 2.
- **Feature-flag state:** N/A — chat now fully functional for the default agent.
- **Tests on merge:** RN Testing Library with a **mocked packet stream** — tokens render incrementally; stop aborts; reopening hydrates history. Manual device run vs live backend.
- **Before you start (grill on):** **PR 0 spike outcomes (HARD GATE)** — streaming is proven (`expo/fetch` + `getReader()`); **still owed: run the deferred `react-native-streamdown` build/render spike on RN 0.85 here (fallback `react-native-marked`).** Use `origin: "unknown"` (or decide whether to add a `"mobile"` value to the backend `MessageOrigin` enum). Exact send-body fields for the minimal core (`origin` value; which fields null/omitted: `internal_search_filters`, `deep_research`, `allowed_tool_ids`, `forced_tool_id`, `llm_override`). Optimistic node-id scheme + `parent_message_id` semantics (-1 vs null vs id). Stop semantics (immediate UI vs wait for `STOP`). Markdown styling → NativeWind token mapping. Where the chosen markdown lib's dev-build config lives. **Renderer contract shape** — confirm the `MessageRenderer<TPacket,TState>` interface (study web's `messageComponents/interfaces.ts` + `renderMessageComponent.tsx`) so PR 9's renderers slot in cleanly; decide whether packet-grouping is mobile-only or a shared pure helper.
- **Drift checkpoint:** If the spike forced the XHR fallback, confirm `stream.ts` shape before coding the controller.
- **As built (2026-06-30, "do it right" decisions — grilled before coding):** Owner chose the full native/faithful path on every gate (see [[mobile-chat-pr3-decisions]]): **markdown = `react-native-streamdown`** (worklet Bundle Mode; adds `react-native-enriched-markdown`+`remend`, babel `worklets:false`+explicit `react-native-worklets/plugin {bundleMode,workletizableModules:['remend']}`, metro `getBundleModeMetroConfig` compose, enriched-markdown config plugin); **keyboard = `react-native-keyboard-controller`** (`KeyboardProvider` in `_layout`, `KeyboardStickyView` in `ChatScreen`); **origin = `"mobile"`** (added `MessageOrigin.MOBILE` to the backend enum — the port now touches backend by choice); **renderer contract = web-faithful** (a `MessageRenderer = {matches(packets), Component}` + `findRenderer(packets)` in `components/chat/renderers/registry.ts`, NOT the `03-detailed-design` reduce sketch). New files: `api/chat/stream.ts` (`expo/fetch` NDJSON generator over the PR2 `createNdjsonBuffer` + `AbortController`), `state/chatSessionStore.ts` (ephemeral zustand, Map-per-session, never persisted), `hooks/useChatController.ts` (module-scope `runChatStream` so the stream survives the landing→`/chat/[id]` navigation; optimistic nodes via PR2 builders; ~50ms batched flush; `-3→null` parent guard; create-at-`persona_id=0`), `hooks/usePacketDisplay.ts`, `components/chat/renderers/{registry,MessageTextRenderer}`, `components/chat/{StreamingMarkdown,MessageRow,MessageList,ChatConversation}.tsx`, `icons/stop-circle.tsx`; modified `api/chat/sessions.ts` (create/get/stop), `components/chat/{InputBar,ChatScreen}.tsx`, `app/(app)/{index,chat/[id]}.tsx`, `app/_layout.tsx`, `babel.config.js`, `metro.config.js`, `app.json`. Send body (minimal): `{message, chat_session_id, parent_message_id, file_descriptors:[], deep_research:false, origin:"mobile"}`. Hydrate via `GET get-chat-session/{id}` → PR2 `processRawChatHistory` (guarded against clobbering a live stream). Stop = client abort + `POST stop-chat-session/{id}` + immediate UI flip. ~1000 source LOC (over the ~700 band — kept whole as one cohesive skeleton rather than split mid-feature). Verified: mobile `tsc` clean, lint clean, **129 jest pass** (10 new: store + controller flow [incremental tokens / new-session create / stop-aborts / hydrate] + stream discriminators). Adversarial multi-agent review = 7 findings, 6 false-positives (FlashList/memo/re-render "concerns" are intended streaming behavior), 1 nit fixed (`ChatHeader` off-token `py-3`→`py-12`). **HARD GATE STILL OWED: the `react-native-streamdown` on-device render + a clean `expo prebuild --clean` + `run:ios`/`run:android` dev-build (adds native `enriched-markdown` + `keyboard-controller`) — the agent can't run a device build; owner must verify. Fallback if streamdown won't build: `react-native-marked` (pure-JS, swap only `StreamingMarkdown.tsx`).**

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
- **As built (2026-07-01, "grilled before coding" — scope tightened to resume + auto-name):** The grill collapsed the "history pagination" line item. **Within-session message pagination was DROPPED** — web has none (it loads the whole `get-chat-session` snapshot and lets virtualization handle long chats; there is no older-messages endpoint to page against), and mobile already gets the full conversation in one call + FlashList already virtualizes. Implementing `onStartReached` would have been a mobile-only divergence, so `MessageList.tsx` is **unchanged**. The **session-list** cursor (sidebar recents, built in PR 1) keeps its `before=time_updated` cursor as-is — the owner chose to leave the rare same-timestamp tie rather than add a `(time_updated, id)` compound cursor to the shared backend route (the chat port stays **backend-free**; comment updated in `api/chat/sessions.ts`). So PR 4 = **resume in-flight run + auto-name** only (~190 source LOC + tests, under the ~450 est).
  - **Resume (faithful web port):** new `hooks/useChatSessionController.ts` — a module-scope `runResumeStream` (survives re-renders, like PR 3's `runChatStream`) + a module `resumingRuns: Set<number>` dedupe. The hook is a **read-only observer** (`useQuery` `enabled:false`) of the `get-chat-session` snapshot that `useChatController` fetches (same query key → React Query dedups; no second network call). When the snapshot's `current_run.run_id` maps to an **assistant** node (single-model only — a multi-model run_id is the user message and fails the node-type check, matching web), it re-attaches: `resumeChatMessage(sessionId, cursor=0, signal)` (full buffer replay + live tail), ~50 ms batched flush, a `stillCurrent = currentSessionId===sessionId && !aborted` guard (drops writes once the user switches away). **Heartbeats pass through on the resume path** (web does the same via `resumeStream`, unlike send) so the loop re-checks focus during quiet phases and releases the connection promptly on navigate-away; they're excluded from render via `isHeartbeat`. On finish/error (**404 = nothing to resume**, swallowed by the bare catch) it settles from `get-chat-session` (`processRawChatHistory` → `hydrateSession`) and `setQueryData`s the fresh snapshot so a remount can't re-resume a finished run. **abortController is reused** (not a second field): send and resume are mutually exclusive per session (resume only fires on cold-open hydration, guarded by `data.abortController == null`), so PR 3's existing `stop()` aborts a resume for free. The settle-block guards `hydrateSession`/`setQueryData`/controller-release on **`stillOurs()` — the resume's own `AbortController` object used as an ownership token held through the settle await** — so a send that races in (and even completes) during the `get-chat-session` fetch is not clobbered by the now-stale snapshot (a completed send leaves a `null` controller, which ≠ the resume's token).
  - **Auto-name:** `runChatStream` now takes an `AutoNameContext | null` (set only when `sessionId == null` at submit — a brand-new session). In its `finally`, when the run produced an answer (`!signal.aborted && sawStreaming && !hadError`), it fires `nameNewSession`: a 200 ms delay (mirrors web's `handleNewSessionNaming` — backend needs a beat to persist the row), then `renameChatSession` → `PUT /chat/rename-chat-session {name:null}` (backend LLM-generates the title), then invalidates `chatSessions` so the sidebar + the header title (which reads from `useChatSessions()`) update and the new chat appears. `api/chat/sessions.ts` gains `renameChatSession`; `stream.ts` refactors the NDJSON reader into a shared `readNdjson` used by both send + resume, adds `resumeChatMessage` (GET, bearer) + `StreamHttpError`.
  - **Divergences from web (per WEB-PARITY PRINCIPLE):** (1) no within-session message pagination (neither does web — parity preserved); (2) auto-name fires only after a **new** session's first answer — web additionally has a "catch-up" rename on the 2nd message if the first naming failed (`useChatSessionController.ts` `newMessageHistory.length >= 2 && !description`); mobile defers that minor recovery path; (3) mobile reuses the single `abortController` for resume (web uses a dedicated one) — safe because the two are mutually exclusive per session on mobile.
  - **Files:** `hooks/useChatSessionController.ts` (new), `hooks/__tests__/useChatSessionController.test.tsx` (new, 9 tests); modified `hooks/useChatController.ts` (auto-name), `api/chat/stream.ts` (`resumeChatMessage` + `readNdjson` refactor + `keepHeartbeats` + exported `isHeartbeat`), `api/chat/sessions.ts` (`renameChatSession` + cursor comment), `components/chat/ChatConversation.tsx` (mounts the resume hook), `hooks/__tests__/useChatController.test.tsx` (+3 auto-name tests). **Web untouched; no backend change.** Verified: mobile `tsc` clean, lint clean (2 pre-existing `_layout.tsx` warnings), **141 jest pass** (12 new). **Two adversarial multi-agent reviews** (each: 3 dimensions × independent verification). Review 1 (19 findings) surfaced 2 confirmed-real bugs, FIXED — (1) the settle-refetch could clobber a send that completed during its await → fixed with the `stillOurs()` ownership-token guard above; (2) heartbeats were filtered on the resume path, dropping web's quiet-phase liveness re-check → fixed with `keepHeartbeats` passthrough (a stop-during-resume `setQueryData` "uncertain" was resolved by the same guard). Review 2 (post-fix) confirmed **both fixes correct (0 fix-correctness findings)** and the comment cut behavior-neutral; its only actionable items were code-quality nits — applied: dropped the unused `StreamHttpError` (→ plain `Error`) + unused `readNdjson(signal)` param, tightened the auto-name comment (in-band error packets still name, web-faithfully), and added the observer post-mount-reactivity test. On-device resume/auto-name against a live backend is the remaining manual check.

## PR 5 — Agent selection
- **Goal:** Browse available agents, pick one, start a chat with it; use its starter prompts.
- **Scope (in):** `mobile/src/chat/contracts/agents.ts` (mobile-native `MinimalAgent` subset — per the PR 2 minimal-sharing decision, **not** shared); `api/chat/agents.ts` (`GET /api/persona`); `components/chat/AgentPicker.tsx` (bottom sheet: avatar/name/description); selection sets `persona_id` at create; starter prompts on the empty screen. No creation/editing.
- **Out of scope:** Agent CRUD, per-agent tool preferences UI.
- **Files:** `mobile/src/chat/contracts/agents.ts` (new, mobile-native), `api/chat/agents.ts` (new), `components/chat/AgentPicker.tsx` (new), empty-state screen (modified), `useChatController.ts` (modified: pass `persona_id`).
- **Est. size:** ~550 LOC.
- **Depends on:** PR 3.
- **Feature-flag state:** N/A.
- **Tests on merge:** RN Testing Library — agents list renders; selecting threads `persona_id` into `create-chat-session`; starter prompt submits.
- **Before you start (grill on):** Which list endpoint (`/api/persona` vs paginated `/agents`) + filtering (`is_listed`/`builtin`/featured). Avatar rendering: `icon_name` mapping + `uploaded_image_id` fetch URL (needs bearer). Picker UX (sheet vs screen; launch point). Default agent (id 0) + `disable_default_assistant` handling.
- **Drift checkpoint:** Confirm select-only is still the scope (no quick-create).

## PR 6 — Projects: list, select, chat-within
- **Goal:** Browse projects, open one, see its chats, start/continue a chat scoped to it.
- **Scope (in):** `mobile/src/chat/contracts/projects.ts` (mobile-native `Project`, `ProjectFile`, `UserFileStatus`); `api/chat/projects.ts` (list + detail/files, read-only); `app/(app)/projects/{index,[id]}.tsx`; "new chat in project" passes `project_id` to `create-chat-session`; sidebar surfaces projects.
- **Out of scope:** Project create/rename/delete; file add/remove (PR 7).
- **Files:** `mobile/src/chat/contracts/projects.ts` (new, mobile-native), `api/chat/projects.ts` (new), `projects/index.tsx` + `projects/[id].tsx` (new), sidebar (modified), `useChatController.ts` (modified: `project_id`).
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
- **Scope (in):** Reuse PR 7 pickers/uploader from the input bar; `components/chat/AttachmentChips.tsx`; `mobile/src/chat/fileDescriptors.ts` (mobile-native `projectFilesToFileDescriptors` + type detection — per the PR 2 minimal-sharing decision, **not** shared; web keeps its own `fileUtils.ts`); build `file_descriptors[]` on send; **gate send until indexed** (`token_count != null`); image preview via `GET /api/chat/file/{file_id}`. Camera deferred.
- **Web parity (REQUIRED — owner-enforced 2026-06-30):** this PR must bring the **input bar to full web parity**. PR 3 shipped a deliberately minimal single-line input; PR 8 reworks it anyway for attachments, so restyle `InputBar.tsx` here to web's **composer** shape/layout — the rounded, auto-growing multi-line container with the control/toolbar row and the send/stop affordance positioned as in web's `BaseInputBar`/`AppInputBar`, attachment chips slotted in. The mobile input must **look and behave like web's composer** (small platform diffs OK), per the WEB-PARITY PRINCIPLE. Re-read `web/src/sections/input/{BaseInputBar,AppInputBar}.tsx` first; if a needed piece isn't a mobile primitive yet, ask before porting.
- **Out of scope:** Camera capture.
- **Files:** `mobile/src/chat/fileDescriptors.ts` (new, mobile-native), `components/chat/AttachmentChips.tsx` (new), `InputBar.tsx` (modified), `useChatController.ts` (modified: attach descriptors). Web `fileUtils.ts` **untouched**.
- **Est. size:** ~550 LOC.
- **Depends on:** PR 7.
- **Feature-flag state:** N/A.
- **Tests on merge:** RN Testing Library — attach→chip→send-gating blocks until indexed; `file_descriptors[]` built correctly; image preview renders.
- **Before you start (grill on):** Send-gating UX while indexing + error surfacing for `FAILED`. `file_descriptors` field mapping (`file_id`→`id`, `chat_file_type`→`type`, `id`→`user_file_id`). Image-preview auth (`GET /api/chat/file/{id}` needs bearer in `<Image>` — header vs signed URL). Reuse vs minor duplication with PR 7's uploader.
- **Drift checkpoint:** This completes the locked scope — confirm before starting whether camera moves in-scope.

## PR 9a–9e — Deferred rich-chat (each its own phase)
- **Goal:** Enrich the working core, one independent feature at a time: **9a** citations/sources · **9b** agentic reasoning timeline (reasoning/search/tool sub-steps) · **9c** regenerate/edit/feedback · **9d** follow-up suggestions · **9e** image-generation rendering.
- **Scope (each):** Add the relevant rich packet types to mobile's `mobile/src/chat/contracts/` packet types, **register a new `MessageRenderer` into the PR 3 dispatch** (`components/chat/renderers/`), and add the RN UI. The dispatch seam from PR 3 means none of these touch the core display path. **9b (agentic timeline) additionally builds the `AgentTimeline` composition layer** (mirrors web's `AgentTimeline`/`TimelineRendererComponent`); 9b's reasoning/search/tool sub-renderers and any later timeline renderers plug into it. Web's `usePacketProcessor` stays web-only.
- **Web parity (REQUIRED — owner-enforced 2026-06-30):** every rich renderer **and** the `AgentTimeline` composition (9b) must match web's **look AND structure**, not just its data. Port web's renderer/timeline component layout — step containers, headers, icons, indentation/connector lines, spacing, and collapse/expand behaviour — so a mobile reasoning/search/tool step reads like its web counterpart (`web/src/app/app/message/messageComponents/**` incl. `timeline/**`). Mirror the structure; **do not invent a new mobile timeline shape.** Document any platform-driven divergence in the As-built note, per the WEB-PARITY PRINCIPLE.
- **Est. size:** ~400–700 LOC each.
- **Depends on:** PR 3 (+ PR 5/6/7/8 where a feature interacts, e.g. citations over project docs).
- **Tests on merge:** RN Testing Library with a mocked packet stream containing the new packet types.
- **Before you start (grill on):** **Treat each as its own mini feature-flow** — re-run research/design for that feature (the packet shapes, the web UI it mirrors, the RN rendering). Confirm priority order (likely 9a citations first — most product value).
- **Drift checkpoint:** Re-prioritize against product needs at the time; these are explicitly post-core and independently schedulable.
