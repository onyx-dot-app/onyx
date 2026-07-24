> Status: active · Task: 9b-timeline · Source plan: 04-implementation-plan.md

# Mobile Chat 9b — Agentic Reasoning Timeline · PR Roadmap

A faithful port of web's agent timeline shell (Approach C) is honestly a **multi-PR phase** (~3.7–4.3k LOC). It's
sliced into 7 layered, independently-mergeable PRs. **Pre-production → no feature flag:** the layers land "dark"
(compiled + unit-tested, not yet on screen) until the composition PR (9b.7) lights the timeline up; the one
mid-sequence behavior change is 9b.4 (the final-answer path migrates to the shared contract, behavior-identical).
Every PR leaves `main` building, `tsc`/lint/jest green, and the app usable.

## Overview

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 9b.1 | `feat(mobile): timeline grouping engine + packet contracts` | ~700 | — | Pure grouping reducer (turn/tab + `section_end` synthesis) + full `PacketType` enum + pure step helpers; unit-tested. Dark. |
| 9b.2 | `feat(mobile): timeline processor + pacing hooks` | ~590 | 9b.1 | `usePacketProcessor` (lint-safe recompute) + `usePacedTurnGroups` (200ms reveal), the two restructured hooks; unit-tested. Dark. |
| 9b.3 | `feat(mobile): timeline state hooks` | ~550 | 9b.1 | `useTimelineUIState`/`Expansion`/`Header`/`StreamingDuration`/`Metrics`/`StepState`; unit-tested. Dark. |
| 9b.4 | `feat(mobile): render-prop renderer contract + answer migration` | ~510 | 9b.1 | `RendererResult`/`MessageRenderer` contract + `findRenderer` + `RendererComponent`; migrate final-answer `MessageTextRenderer` to it. **Live** (answer path). |
| 9b.5 | `feat(mobile): timeline primitives + StepContainer` | ~650 | 9b.4 | Rail/surface/content primitives + `StepContainer` + `TimelineRendererComponent` + new icons/Button (ASK) + StreamingMarkdown `muted`. Dark. |
| 9b.6 | `feat(mobile): reasoning renderer` | ~450 | 9b.4, 9b.5 | `ReasoningRenderer` + `reasoningState` + `ReasoningTextWindow`; registered in `findRenderer`; unit-tested. Dark. |
| 9b.7 | `feat(mobile): agent timeline composition` | ~700 | 9b.2, 9b.3, 9b.5, 9b.6 | `AgentTimeline` shell + headers + Expanded/Collapsed content + `MessageRow` wiring + `streamingStartedAt`. **Lights up** the timeline. **Device gate.** |

## Sequence

```
9b.1 engine+contracts+helpers ─┬─► 9b.2 processor+pacing hooks ──┐
   (dark, unit-tested)         ├─► 9b.3 state hooks ─────────────┤
                               └─► 9b.4 contract + answer path ──┼─► 9b.5 primitives+StepContainer ─► 9b.6 reasoning ─┐
                                        (live: answer)           │        (dark)                        (dark)        │
                                                                 └──────────────────────────────────────────────────►┴─► 9b.7 composition
                                                                                                                          (LIGHTS UP + device gate)
```
9b.1 is the root. 9b.2 / 9b.3 / 9b.4 fan out from it (parallelizable). 9b.5→9b.6 chain on the contract. 9b.7
depends on the hooks (9b.2/9b.3), the UI primitives (9b.5), and the reasoning renderer (9b.6) — it's the only PR
that changes the timeline on screen.

---

## PR 9b.1 — Grouping engine + packet contracts + pure helpers
- **Goal:** The pure, unit-tested data core — packets grouped into timeline steps exactly as web does.
- **Scope (in):** full web `PacketType` enum + the engine/shell obj interfaces (§1 of `03`); extend
  `messageProcessor` into a faithful `packetProcessor` port (grouping map, `section_end` synthesis on
  turn-transition + stop, tool/display categorization, `finalAnswerComing`, `buildGroupsFromKeys`,
  `hasContentPackets`); the pure step helpers.
- **Out of scope:** all hooks, all UI, the reasoning renderer. Nothing renders differently.
- **Files:**
  | File | New/Modified | Slice |
  |------|--------------|-------|
  | `mobile/src/chat/streamingModels.ts` | modified | enum values + reasoning/branch/tool-arg interfaces + `ObjTypes` |
  | `mobile/src/chat/messageProcessor.ts` | modified | grouping fields + `section_end` synthesis + categorization (keep 9a citations/docs) |
  | `mobile/src/chat/timeline/transformers.ts` | new | `TransformedStep`/`TurnGroup`/`groupStepsByTurn` |
  | `mobile/src/chat/timeline/packetUtils.ts` | new | `isToolPacket`/`isDisplayPacket`/`getTextContent`/… |
  | `mobile/src/chat/timeline/packetHelpers.ts` | new | per-family predicates + collapsed-streaming sets |
  | `mobile/src/chat/timeline/toolDisplay.ts` | new | `parseToolKey`/`getToolName`/`isToolComplete`/`hasToolError` |
  | `mobile/src/chat/timeline/__tests__/*` | new | grouping key, 3 `section_end` triggers, categorization, parallel detection, `model_index` tolerance, history-reset |
- **Est. size:** ~700 LOC (at the band; the engine + its helpers + tests are one coherent, tightly-coupled unit — splitting the helpers out would ship an engine that can't compile).
- **Depends on:** —
- **Feature-flag state:** N/A (pre-production; additive — dark).
- **Tests on merge:** Jest unit — grouping + `section_end` synthesis + transformers fully covered; `messageProcessor` still passes its 9a citation/document tests.
- **Drift checkpoint:** Confirm the backend reasoning packet shapes (`reasoning_start/delta/done`) and `Placement`
  fields are still as `03`/deepread recorded; re-verify `web/.../packetProcessor.ts` hasn't changed since extraction.

## PR 9b.2 — Processor + pacing hooks
- **Goal:** Host the reducer and drive the 200 ms staggered reveal — the two lint-forced restructures.
- **Scope (in):** `usePacketProcessor` (`useMemo` full recompute + derive `toolTurnGroups`/`displayGroups`/
  `isComplete`); `usePacedTurnGroups` (`useState`+effect reveal, answer gating, history bypass; drop
  `prevPacedRef`).
- **Out of scope:** the state/derive hooks (9b.3), all UI.
- **Files:**
  | File | New/Modified | Slice |
  |------|--------------|-------|
  | `mobile/src/hooks/timeline/usePacketProcessor.ts` | new | recompute + group derivation + `renderComplete` gate |
  | `mobile/src/hooks/timeline/usePacedTurnGroups.ts` | new | 200ms reveal + gating (restructured) |
  | `mobile/src/hooks/timeline/__tests__/*` | new | fake-timer pacing (first-immediate/200ms/stop-flush/bypass) + processor derivation |
- **Est. size:** ~590 LOC.
- **Depends on:** 9b.1.
- **Feature-flag state:** N/A (dark).
- **Tests on merge:** Jest unit with fake timers — reveal cadence, stop-flush, history bypass, answer withheld until pacing completes; processor recompute correctness.
- **Drift checkpoint:** Confirm on-device the recompute + effect-driven reveal feel identical to web (the one-frame
  risk called out in `03` §1); if the first-packet render flashes, revisit before 9b.7 wires it.

## PR 9b.3 — Timeline state hooks
- **Goal:** The pure UI-state derivation — 7-state machine, expansion, header text, live timer, metrics.
- **Scope (in):** `useTimelineUIState` (7 states + booleans), `useTimelineExpansion` (auto-collapse +
  `userHasToggled`), `useTimelineHeader` (text map; search sub-labels generic for now), `useStreamingDuration`
  (live timer + backend freeze), `useTimelineMetrics`, `useTimelineStepState` (memory, dormant).
- **Out of scope:** all UI; the search-specific header sub-labels (search phase).
- **Files:**
  | File | New/Modified | Slice |
  |------|--------------|-------|
  | `mobile/src/hooks/timeline/useTimelineUIState.ts` | new | state machine + show/style booleans |
  | `mobile/src/hooks/timeline/useTimelineExpansion.ts` | new | collapse + auto-collapse |
  | `mobile/src/hooks/timeline/useTimelineHeader.ts` | new | header text map |
  | `mobile/src/hooks/timeline/useStreamingDuration.ts` | new | live elapsed timer |
  | `mobile/src/hooks/timeline/useTimelineMetrics.ts` | new | step count + last-step flags |
  | `mobile/src/hooks/timeline/useTimelineStepState.ts` | new | memory extraction (dormant) |
  | `mobile/src/hooks/timeline/__tests__/*` | new | 7 states + booleans, auto-collapse + toggle suppression, timer tick + freeze |
- **Est. size:** ~550 LOC.
- **Depends on:** 9b.1 (types + predicates).
- **Feature-flag state:** N/A (dark).
- **Tests on merge:** Jest unit — every `TimelineUIState` branch + derived boolean; expansion auto-collapse and `userHasToggled`; duration tick/freeze.
- **Drift checkpoint:** none beyond 9b.1's.

## PR 9b.4 — Render-prop renderer contract + final-answer migration
- **Goal:** Adopt web's render-prop contract and route the final answer through it — the "no refactor later" move.
- **Scope (in):** `timelineContract.ts` (RenderType/RendererResult/MessageRenderer/FullChatState/TimelineRendererResult);
  `findRenderer.ts` (full 13-slot priority chain — chat wired, reasoning slot present-but-null, others tagged
  `// PR 9x`); `RendererComponent.tsx` (final-answer at `FULL`, mixed chat+image stubbed = 9e); migrate
  `MessageTextRenderer` to the contract; re-export from `registry.ts`; point `MessageRow`'s answer render at
  `RendererComponent` (timeline still stub).
- **Out of scope:** timeline UI, reasoning renderer.
- **Files:**
  | File | New/Modified | Slice |
  |------|--------------|-------|
  | `mobile/src/components/chat/renderers/timelineContract.ts` | new | the contract types |
  | `mobile/src/components/chat/renderers/findRenderer.ts` | new | priority dispatch |
  | `mobile/src/components/chat/renderers/RendererComponent.tsx` | new | final-answer dispatch |
  | `mobile/src/components/chat/renderers/MessageTextRenderer.tsx` | modified | → render-prop contract |
  | `mobile/src/components/chat/renderers/registry.ts` | modified | re-export `findRenderer` |
  | `mobile/src/components/chat/MessageRow.tsx` | modified | answer → `RendererComponent` (timeline still stub) |
  | `mobile/src/hooks/usePacketDisplay.ts` | modified | keep exposing `processed` for `CitedSources` |
  | `__tests__/*` | new | findRenderer dispatch order, MessageTextRenderer render-prop, RendererComponent |
- **Est. size:** ~510 LOC.
- **Depends on:** 9b.1.
- **Feature-flag state:** N/A — **live behavior change** (answer path). Must render identically.
- **Tests on merge:** Jest — dispatch order (chat first, reasoning last); MessageTextRenderer emits `children([result])`; RendererComponent renders answer. **Manual:** confirm the streamed markdown answer + 9a inline citations + Sources bar are unchanged.
- **Drift checkpoint:** This touches shipped PR-3/9a code — before starting, re-confirm the 9a citation-link + `CitedSources` behavior so the migration preserves it exactly.

## PR 9b.5 — Timeline primitives + StepContainer
- **Goal:** The visual step frame — rail, connector, surface, header, collapse — plus the new icons/primitives.
- **Scope (in):** `primitives/*` (`timelineTokens` px constants, `TimelineRoot`/`HeaderRow`/`Row`/`IconColumn`/
  `Surface`/`StepContent`, hover dropped); `StepContainer`; `TimelineRendererComponent` (per-step expand +
  `renderType` derivation); new icons `circle`/`fold`/`expand`/`check-circle` (**owner-ASK**); confirm/port a
  tertiary icon `Button` (**owner-ASK**); `StreamingMarkdown` `muted` variant.
- **Out of scope:** the reasoning renderer, `AgentTimeline` composition, headers.
- **Files:**
  | File | New/Modified | Slice |
  |------|--------------|-------|
  | `mobile/src/components/chat/timeline/primitives/*` | new | tokens + 6 rail/surface/content primitives |
  | `mobile/src/components/chat/timeline/StepContainer.tsx` | new | compose primitives into a step frame |
  | `mobile/src/components/chat/timeline/TimelineRendererComponent.tsx` | new | per-step expand + renderType |
  | `mobile/src/icons/{circle,fold,expand,check-circle}.tsx` | new | ASK owner |
  | `mobile/src/components/chat/StreamingMarkdown.tsx` | modified | `muted`/`compact` variant |
  | `__tests__/*` | new | StepContainer (collapse gating, last-step connector, error surface), renderType derivation |
- **Est. size:** ~650 LOC.
- **Depends on:** 9b.4 (contract).
- **Feature-flag state:** N/A (dark — not yet mounted).
- **Tests on merge:** RN Testing Library — StepContainer renders header/body/collapse per `renderType`; icon rail geometry; error surface.
- **Drift checkpoint:** **Owner-ASK gate** — resolve the new-icon ports + tertiary Button before coding UI (per the web-parity principle). Re-confirm the token px values against `03` if web tokens changed.

## PR 9b.6 — Reasoning renderer
- **Goal:** The one wired step renderer — streamed reasoning with heading, 500 ms min-thinking, markdown body.
- **Scope (in):** `reasoningState.ts` (pure `extractFirstParagraph` + `constructCurrentReasoningState`);
  `ReasoningRenderer.tsx` (render-prop; 500 ms gate; icon `circle`; `noPaddingRight`; `supportsCollapsible`);
  `ReasoningTextWindow.tsx` (maxHeight markdown window); register reasoning in `findRenderer`.
- **Out of scope:** `AgentTimeline` composition (9b.7); the copy/download modal + translateY auto-scroll (deferred).
- **Files:**
  | File | New/Modified | Slice |
  |------|--------------|-------|
  | `mobile/src/chat/timeline/reasoningState.ts` | new | heading extraction + delta accumulation (pure) |
  | `mobile/src/components/chat/renderers/ReasoningRenderer.tsx` | new | the render-prop renderer + 500ms gate |
  | `mobile/src/components/chat/timeline/ReasoningTextWindow.tsx` | new | maxHeight markdown window |
  | `mobile/src/components/chat/renderers/findRenderer.ts` | modified | wire the reasoning slot |
  | `__tests__/*` | new | heading extraction rules, delta accumulation, 500ms gate (fake timers), empty/pre-start branch |
- **Est. size:** ~450 LOC.
- **Depends on:** 9b.4 (contract), 9b.5 (`circle` icon, `StreamingMarkdown` muted, StepContainer for the smoke test).
- **Feature-flag state:** N/A (dark — reachable only once 9b.7 mounts the timeline).
- **Tests on merge:** Jest — `reasoningState` heading + accumulation; `ReasoningRenderer` 500 ms gate + branches; a StepContainer-wrapped smoke render.
- **Drift checkpoint:** Confirm `react-native-streamdown` renders the `muted` variant acceptably (color/margins) — device-adjacent; the owner's 9b.7 device gate covers it.

## PR 9b.7 — Agent timeline composition (lights up)
- **Goal:** Assemble the shell and render the timeline on screen — the walking skeleton completes.
- **Scope (in):** rewrite `AgentTimeline` into the shell (runs the state hooks + header switch + body);
  `ExpandedTimelineContent` + `CollapsedStreamingContent` + `TimelineStep`; headers
  (`StreamingHeader`/`CompletedHeader`/`StoppedHeader`; `ParallelStreamingHeader` dormant stub);
  `ParallelTimelineTabs` dormant (linearize) + `toolIcons`; Done/Stopped terminal step; wire
  `MessageRow.AssistantMessage` into the AgentMessage analog (`usePacketProcessor` + `usePacedTurnGroups` →
  `AgentTimeline` above + `RendererComponent` answer below + `CitedSources`); capture `streamingStartedAt` in the
  PR-3 stream controller/store.
- **Out of scope:** any tool renderer (follow-up phases); real parallel-tab tabs.
- **Files:**
  | File | New/Modified | Slice |
  |------|--------------|-------|
  | `mobile/src/components/chat/AgentTimeline.tsx` | modified | stub → full shell |
  | `mobile/src/components/chat/timeline/ExpandedTimelineContent.tsx` | new | TurnGroup[]→steps + Done/Stopped |
  | `mobile/src/components/chat/timeline/CollapsedStreamingContent.tsx` | new | streaming live preview |
  | `mobile/src/components/chat/timeline/TimelineStep.tsx` | new | step composer (children → StepContainer) |
  | `mobile/src/components/chat/timeline/headers/*` | new | Streaming/Completed/Stopped (+Parallel dormant) |
  | `mobile/src/components/chat/timeline/ParallelTimelineTabs.tsx` | new | dormant stub (linearize) |
  | `mobile/src/components/chat/timeline/toolIcons.ts` | new | packet-type → icon map |
  | `mobile/src/components/chat/MessageRow.tsx` | modified | AssistantMessage → AgentMessage analog |
  | stream controller / `chatSessionStore` | modified | `streamingStartedAt` per node |
  | `__tests__/*` | new | mocked reasoning stream → "Thinking" step → collapse to "Thought for Ns"; tap expands; USER_CANCELLED → Stopped |
- **Est. size:** ~700 LOC.
- **Depends on:** 9b.2, 9b.3, 9b.5, 9b.6.
- **Feature-flag state:** N/A — **the timeline goes live.**
- **Tests on merge:** RN Testing Library — mocked reasoning packet stream renders the streaming header → step → auto-collapse → tap-expand → Done; Stopped path. **HARD device gate (owner):** dev build, reasoning model — streaming shimmer + live timer, auto-collapse on answer, tap-to-expand, Done step, hydrated render; migrated answer + 9a Sources intact; streaming re-render stays smooth (perf-isolation from `04`).
- **Drift checkpoint:** Re-confirm the `unify-chat-input` `ChatSurface` composition (post-PR6 refactor) is where `MessageRow`/`AgentTimeline` mount, and that per-conversation draft/reset rules don't interfere with the per-node timeline state.

## After 9b — the follow-up renderer phases (not designed here)

Each is its own grill-first PR on the zero-refactor seam: add the tool's obj interfaces + one `findRenderer`
predicate wire-up + one render-prop renderer returning `RendererResult` (search/fetch reuse 9a `SourceRow`).
Order by product value (owner's call): **search → fetch → python/code → custom-tool → deep-research (+nested) →
memory**, plus **parallel-tab tabs** (UI-only, un-dormant `ParallelTimelineTabs`) and **9c/9d/9e** independently.
