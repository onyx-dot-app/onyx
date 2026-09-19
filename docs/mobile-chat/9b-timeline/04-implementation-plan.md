> Status: active · Task: 9b-timeline

# Mobile Chat 9b — Agentic Reasoning Timeline · Implementation Plan

## Issues to Address

Mobile chat renders assistant answers with no visibility into the agent's **thinking/tool steps** — the
`AgentTimeline` above each answer is a stub whose `steps` prop is always `[]`. Web shows a full **agent timeline**
(a rail of collapsible reasoning/tool steps with a streaming "Thinking… (Ns)" header that auto-collapses to
"Thought for Ns · N steps"). 9b ports web's **entire timeline shell 1:1** to `mobile/` and wires the **reasoning**
step, so that: (a) thinking/tool activity is shown faithfully during and after streaming; (b) the composition
seam is a **zero-refactor drop-in point** for the tool renderers the owner will build immediately after
(search/fetch/python/custom-tool/deep-research/memory) and for 9c–9e. Backend, DB, and API are unchanged.

## Important Notes

- **The 9a foundation is the reserved seam.** `mobile/src/chat/messageProcessor.ts` is a flat, cursor-incremental
  reducer whose header comment states 9b extends it with turn/tab grouping; `mobile/src/components/chat/AgentTimeline.tsx`
  already has the 36px rail + 24px avatar + reanimated shimmer + a `TimelineStep` primitive; `MessageRow.AssistantMessage`
  already mounts the timeline above the answer and `CitedSources` (9a) below. 9b builds on all three.
- **Web is the source of truth.** Exact contracts, algorithms, and tokens are captured in `03-detailed-design.md`
  and `.context/pr9b-deepread/*.md`, extracted verbatim from `web/src/app/app/message/messageComponents/**`
  (`packetProcessor.ts`, `transformers.ts`, `interfaces.ts`, `renderMessageComponent.tsx`, the `timeline/hooks/*`,
  `timeline/primitives/*`, `timeline/headers/*`, `ReasoningRenderer.tsx`). Reasoning packets already stream from
  `backend/onyx/chat/llm_step.py`.
- **`section_end` synthesis is the correctness core.** A step is marked complete almost entirely by
  **client-synthesized** `section_end` — on a new `turn_index` (closes all prior groups) and on `stop` (closes all
  open groups). The backend seldom sends it. Port `injectSectionEnd`/`handleTurnTransition`/`handleStopPacket`
  verbatim (packetProcessor.ts:116-133, 190-208, 270-287).
- **The one platform-forced divergence: two ref-during-render hooks.** `usePacketProcessor` (web mutates a state
  ref during render) → mobile `useMemo` full recompute (9a's proven, lint-safe pattern). `usePacedTurnGroups` (web
  reads pacing refs during render) → `useState` written by an effect + timer handle in a ref (effect-only). Both
  **behavior-preserving** (same grouped output, same 200 ms cadence). This is required by mobile's
  `react-hooks/refs` lint; it is not a look/structure drift.
- **reanimated jest gotcha.** All pure logic (grouping, transformers, packetUtils, packetHelpers, toolDisplay,
  reasoningState, state-machine math) lives in **reanimated-free** modules so units don't hit the "Worklets not
  initialized" crash; import leaf components directly in tests.
- **Streaming re-render isolation (hardening — from plan-challenge).** The live 1/sec timer + the 200 ms pacing
  reveals re-render frequently; scope them so they can't churn the `FlatList` or the answer markdown. Concretely:
  the message row is `React.memo`'d, `renderItem` is `useCallback`'d with stable keys, the per-second timer is
  isolated to the header subtree (not the whole `AgentTimeline`/row), and grouped/paced outputs never hand a fresh
  object identity to a row that didn't change. (React Native official FlatList guidance; verified 2026.)
- **`useMemo` full-recompute cost (acknowledged).** The lint-safe `usePacketProcessor` reprocesses all packets per
  flush (O(n)), vs web's incremental cursor. Fine at chat scale (hundreds of packets); a pathologically long
  tool-heavy turn (thousands) doubles per-flush work. This is an internal implementation detail with no API impact,
  so it can be re-optimized to incremental later **without touching the seam** — do not pre-optimize.
- **Full `PacketType` enum now, per-tool interfaces later** — so the engine/helpers compile once and never need an
  enum edit; each future tool renderer adds only its obj interface + one `findRenderer` predicate wire-up.
- **Progressive disclosure = the industry default** (collapse-by-default, streaming "Thinking… (Ns)" summary,
  auto-collapse-on-answer, tap-not-hover) — parity and best practice coincide (`digestibleux.com`, `hatchworks`
  agent-ux, W3C accordion APG).
- **Owner-ASK before UI lands:** new icons (`circle`, `fold`, `expand`, `check-circle`; `stop-circle` exists) and
  confirming the mobile `Button` covers a tertiary icon button — per the web-parity principle, don't hand-roll a
  divergent primitive.
- **Documented divergences** (must appear in the "as-built" note): the two restructured hooks; shimmer = opacity
  pulse not gradient; reasoning window = fixed maxHeight not translateY auto-scroll (copy/download modal deferred);
  parallel-tab tabs dormant → linearized; search header sub-labels generic until the search phase; entrance CSS
  animations optional; memory tooltip/modal dropped; `expandedText` dead field dropped; no hover anywhere.

## Implementation Strategy

Ordered, coherent changes. Each maps to a step Phase 5 bundles into ~500–700 LOC PRs.

1. **Packet contracts.** Extend `mobile/src/chat/streamingModels.ts` with the full web `PacketType` enum values and
   the obj interfaces the engine/shell dereference (`ReasoningStart/Delta/Done`, `TopLevelBranching`,
   `ToolCallArgumentDelta` + `CODE_INTERPRETER_TOOL_TYPES`, `SearchToolStart.is_internet_search`,
   `CustomToolStart.tool_name`, `ImageGenerationToolDelta.images`, `MessageStart.pre_answer_processing_seconds`);
   extend the `ObjTypes` union.
2. **Grouping engine.** Extend `mobile/src/chat/messageProcessor.ts` into a faithful port of web `packetProcessor.ts`:
   add the grouping fields to `ProcessedMessageState` + `GroupedPacket`; port `getGroupKey`, `injectSectionEnd`,
   `handleTurnTransition`, `handleStopPacket` (grouping), `handleStreamingStatusPacket`,
   `handleToolAfterMessagePacket`, categorization, `buildGroupsFromKeys`, `hasContentPackets`, and the packet-type
   Sets. Preserve the 9a citation/document/`isComplete` behavior.
3. **Pure step helpers.** Add `mobile/src/chat/timeline/{transformers,packetUtils,packetHelpers,toolDisplay,reasoningState}.ts`
   ported verbatim (step→turn grouping + parallel detection; categorizers; per-family predicates + collapsed-streaming
   sets; tool key/name/completion; reasoning heading extraction + delta accumulation).
4. **Processor + pacing hooks (the restructure).** Add `mobile/src/hooks/timeline/usePacketProcessor.ts` (useMemo
   recompute + derive `toolTurnGroups`/`displayGroups`/`isComplete`) and `usePacedTurnGroups.ts` (useState +
   effect-driven 200 ms reveal, answer gating, history bypass; drop web's `prevPacedRef`).
5. **State/derive hooks.** Add `useTimelineUIState` (7 states + booleans), `useTimelineExpansion` (auto-collapse +
   userHasToggled), `useTimelineHeader` (text map), `useStreamingDuration` (live timer, backend-freeze),
   `useTimelineMetrics`, `useTimelineStepState` (memory, dormant) under `mobile/src/hooks/timeline/`.
6. **Renderer contract + dispatch.** Add `renderers/timelineContract.ts` (RenderType/RendererResult/MessageRenderer/
   FullChatState/TimelineRendererResult) and `renderers/findRenderer.ts` (full 13-slot priority chain; chat +
   reasoning wired, the rest tagged `// PR 9x`). Re-export from `registry.ts`.
7. **Renderer-path migration.** Migrate `MessageTextRenderer.tsx` to the render-prop `MessageRenderer` contract;
   add `RendererComponent.tsx` (final-answer dispatch at `FULL`, mixed chat+image stubbed = 9e). Preserve 9a inline
   citations + streamed markdown.
8. **Icons + primitives (owner-ASK).** Add `circle`, `fold`, `expand`, `check-circle` icons; confirm/port a
   tertiary icon `Button`; add a `muted`/`compact` variant to `StreamingMarkdown.tsx`.
9. **Timeline primitives + StepContainer.** Add `components/chat/timeline/primitives/*` (`timelineTokens`,
   `TimelineRoot/HeaderRow/Row/IconColumn/Surface/StepContent`) with baked px tokens + dropped hover; add
   `StepContainer.tsx` and `TimelineRendererComponent.tsx` (per-step expand + `renderType` derivation).
10. **Reasoning renderer.** Add `renderers/ReasoningRenderer.tsx` (constructReasoningState + extractFirstParagraph +
    500 ms min-thinking gate) and `timeline/ReasoningTextWindow.tsx` (maxHeight markdown window). Register reasoning
    in `findRenderer`.
11. **Timeline composition + headers.** Rewrite `AgentTimeline.tsx` into the shell (runs the state hooks + header
    switch + body), add `ExpandedTimelineContent.tsx`, `CollapsedStreamingContent.tsx`, `TimelineStep.tsx`, the
    `headers/*` (Streaming/Completed/Stopped; Parallel* dormant stubs), `ParallelTimelineTabs.tsx` (dormant,
    linearized), `toolIcons.ts`, the Done/Stopped terminal step.
12. **Wire the composition root.** Update `MessageRow.AssistantMessage` into the AgentMessage analog (run
    `usePacketProcessor` + `usePacedTurnGroups`; `AgentTimeline` above; `pacedDisplayGroups` → `RendererComponent`
    below; `CitedSources` last); fold/adjust `usePacketDisplay` to keep exposing `processed` for `CitedSources`.
    Capture `streamingStartedAt` per assistant node in the PR-3 stream controller/store for the live timer.

## Tests

**Primary type: RN Testing Library + Jest unit** (the pure core + hooks carry essentially all the risk; there is
no backend surface — reasoning packets already exist). Cover:

- **Grouping/engine (`chat/timeline` + `messageProcessor`):** group key `"{turn}-{tab}"`; the three `section_end`
  triggers (real packet, turn-transition closes prior groups, stop closes all open); tool-vs-display
  categorization; `finalAnswerComing` + tool-after-message reset; `hasContentPackets`; `model_index` tolerance;
  history-reload reset (array shrink).
- **Transformers:** `groupStepsByTurn` parallel detection + turn/tab ordering.
- **Pacing (`usePacedTurnGroups`, fake timers):** first step immediate, subsequent 200 ms apart, `stop` flush-all,
  history bypass reveals instantly, answer withheld until pacing completes.
- **State hooks:** `useTimelineUIState` all 7 states + each derived boolean; `useTimelineExpansion` auto-collapse
  on answer/stop + `userHasToggled` suppression; `useStreamingDuration` per-second tick + backend-duration freeze.
- **Reasoning:** `reasoningState` heading extraction (markdown-heading rule, 60-char cap) + delta accumulation;
  `ReasoningRenderer` 500 ms min-thinking gate (fake timers) + empty/pre-start branch.
- **Component smoke test:** a mocked reasoning packet stream renders a "Thinking" step, streams markdown, marks
  done, and collapses to "Thought for Ns · 1 step"; tap expands; a `USER_CANCELLED` stop shows the Stopped step.

**HARD device gate (owner-run, not automatable):** on a dev build, drive a reasoning model and confirm the
streaming shimmer + live timer, auto-collapse when the answer begins, tap-to-expand, the Done terminal step, and a
hydrated (history-reloaded) render — plus that the migrated final-answer path + 9a Sources still render correctly.

## Plan Challenge Results

Ran the mandatory 6-point challenge (web-verified checks 3 & 4).

### 1. Extendability & Scalability: PASS
Full-shell-now means each of the 6 deferred tool renderers + 9c/9e is a single new file + one `findRenderer`
wire-up — zero engine/enum/shell change; the grouping key already carries `tab_index`/`sub_turn_index`/`model_index`
for parallel/nested/multi-model. Sole caveat (documented, not a rewrite): the lint-safe `usePacketProcessor` is
O(n)/flush vs web's incremental cursor — fine at chat scale, re-optimizable later behind the same API.

### 2. Fragility: CONCERN → hardened
Two brittle points, each with a concrete mitigation now in the plan: (a) `usePacedTurnGroups` (timers +
effect-published state) is the highest-bug-density file → fake-timer unit tests for first-immediate / 200 ms /
stop-flush / history-bypass; (b) the 1/sec timer + 200 ms reveals could churn the `FlatList`/answer → isolate the
timer to the header subtree, `React.memo` the row, stable keys, no per-tick identity churn (added as a hardening
note). `section_end` synthesis depends on turn-transition ordering but is ported verbatim + unit-tested.

### 3. Industry Standard: VERIFIED
Searched render-props-vs-hooks (2025), ref-during-render/purity, and RN FlatList streaming perf. (a) Render-props /
children-as-function remain the recognized standard **for headless renderers where the wrapper owns the tree**
(Downshift, React Aria, TanStack Table, Framer Motion `AnimatePresence`) — exactly the `StepContainer`↔renderer
split, so the render-prop contract is legitimate here, not legacy. (b) The ref restructure **aligns with React's
own rule** — react.dev's `eslint-plugin-react-hooks/refs` + purity docs say reading/writing `ref.current` during
render breaks purity/concurrent rendering; web's ref-during-render is the anti-pattern React now lints against, so
mobile's restructure is *more* correct, not a workaround. (c) FlatList streaming perf best practices (memo rows,
`useCallback` renderItem, stable keys, no per-tick object churn) confirmed and folded in.
Sources: [react.dev refs lint](https://react.dev/reference/eslint-plugin-react-hooks/lints/refs),
[react.dev purity](https://react.dev/reference/rules/components-and-hooks-must-be-pure),
[patterns.dev render props](https://www.patterns.dev/react/render-props-pattern/),
[RN FlatList optimization](https://reactnative.dev/docs/optimizing-flatlist-configuration).

### 4. Fact Check: PASS (one honest nuance)
Claims verified: "progressive disclosure = industry default" (Phase 1 + re-verified); "refs-during-render must be
restructured" (React official docs, above); "render-prop makes future ports mechanical" (valid for the headless-
renderer case). **Nuance stated plainly:** render-props are *not* the modern default for brand-new logic-sharing
(hooks are) — mobile adopts them **purely for web-parity / mechanical future ports**, an explicit, owner-chosen
divergence from the hooks-default norm, not an oversight.

### 5. Maintainability: PASS (conditional, satisfied)
Mirrors web's exact `timeline/` file tree (a dev who knows web finds the identical structure), pure logic isolated +
unit-tested, clear engine/hooks/primitives/renderers boundaries. The ~35-files-for-one-wired-renderer surface only
pays off **if the follow-up renderers get built** — which the owner has explicitly committed to doing immediately,
so the investment is justified rather than speculative. Gotcha to guard with a comment: the render-prop inversion
(renderer calls `children(results)`, never returns its own tree) — documented in `03` §9.

### 6. Patch vs. Fix: PROPER FIX (no escalation needed)
The render-prop migration of shipped PR-3/9a code is a **root-cause fix** — it unifies mobile onto web's contract
now so there is *no* later refactor; the alternative (bolt reasoning onto the simpler `{matches,Component}`
contract) is precisely the "refactor later" the owner forbade. The two hook restructures are fixes (align with
React's purity rule), not lint-suppression. The scoped deferrals (search sub-labels, parallel tabs, reasoning
auto-scroll) are documented scope boundaries restored by later phases, not symptom-patches. No patch-vs-fix
decision to surface.

**Verdict: all six pass (2 concerns hardened in-plan). No patch-vs-fix escalation. Cleared for Phase 5.**
