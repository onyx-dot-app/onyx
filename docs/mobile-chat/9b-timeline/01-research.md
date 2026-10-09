> Status: draft · Task: 9b-timeline · Parent: `../05-pr-roadmap.md` (PR 9b) · Prior phase: `../9a-citations/` (shipped #13025)

# Mobile Chat 9b — Agentic Reasoning Timeline · Research

## Requirement

Port web's chat **agentic reasoning timeline** (`AgentTimeline` — reasoning/search/tool sub-steps with step
containers, headers, icons, connector lines, collapse/expand) to the Onyx React Native + Expo mobile app
(`mobile/`), at **web parity** (match web's look AND structure), extending the 9a foundation and registering
into the PR-3 renderer dispatch. Backend is unchanged. This is the rich-chat phase that additionally builds the
**`AgentTimeline` composition layer** that every later phase (search/fetch/tool renderers, 9c–9e) plugs into.

## Clarifications

- **Scope of 9b (locked, owner 2026-07-16): FOUNDATION-ONLY FIRST.** The thinnest walking skeleton of the
  timeline — (1) the turn/tab **grouping engine**, (2) the **`AgentTimeline` composition layer** (real steps +
  collapse/expand), (3) the **reasoning** step renderer only (`reasoning_start/delta/done`). **Every tool
  renderer is a separate follow-up phase**: internal/web search, fetch/open_url, python/code, coding-agent+bash,
  custom-tool, deep-research + nested (`sub_turn_index`) agents, memory. Image generation is a separate phase
  (9e). Multi-model (`model_index`) is out (mobile is single-model) but the grouping must **tolerate** non-zero
  `model_index`. Parallel-tool tabs (`tab_index` parallelism) are a follow-up, but the grouping key + data model
  should not **preclude** them.
- **Web parity is required** (per `../05-pr-roadmap.md` PR 9a–9e callout): match web's look AND structure; port
  the step-container/header/icon/connector/collapse shape, don't invent a new mobile timeline. Document any
  platform-driven divergence.
- **Chat layer is native** (`mobile/src/chat/`, NOT `@onyx-ai/shared`) per the PR-2 decision. Web is untouched.
  Backend is unchanged (reasoning packets already exist).

## Current status & reuse (from codebase scan — exact paths, validated by direct read)

**The 9b seams already exist and are explicitly reserved:**

- `mobile/src/chat/messageProcessor.ts` — flat, cursor-incremental (`nextPacketIndex`) packet→state reducer.
  `ProcessedMessageState = {nodeId, nextPacketIndex, citationMap, citations, seenCitationDocIds, documentMap,
  isComplete, stopReason}`. **Header comment: _"9b extends it with turn/tab grouping + timeline steps, so the
  shape here stays deliberately flat (grouping-free)."_**
- `mobile/src/components/chat/AgentTimeline.tsx` — **existing stub**: 36px rail (`w-36`), 24px `AgentAvatar`,
  reanimated shimmer `ThinkingLabel`, and a `TimelineStep` list primitive (`TimelineStepData = {key, label,
  status:"running"|"done"|"error", icon?}`; connector lines `h-8 w-[1px] bg-border-01` with `opacity-0` on
  first/last; fallback node dot `h-8 w-8 rounded-full bg-text-04`; step `Icon size=12`). **`steps` prop always
  `[]` — nothing populates it.** Rendered in `MessageRow.AssistantMessage` **above** the answer:
  `<AgentTimeline agent isLoading={!hasContent && !processed.isComplete} />`.
- `mobile/src/components/chat/renderers/registry.ts` — `MessageRenderer = {matches(packets), Component}`;
  `MessageRendererProps = {packets, processed}`; first-match-wins `RENDERERS`; `findRenderer`. **Simpler than
  web's render-prop `MessageRenderer<T,S>`.** Only `MessageTextRenderer` registered.
- `mobile/src/hooks/usePacketDisplay.ts` — `processed = useMemo(() => processPackets(createInitialState(nodeId),
  packets), [nodeId, packets])` — **full recompute per flush** (array identity changes each flush).
  **Deliberately NOT a render-mutated ref** — mobile's `react-hooks/refs` lint forbids `ref.current` access
  during render, so **web's ref-held `usePacketProcessor` pattern is illegal here.**
- `mobile/src/components/chat/MessageRow.tsx` — `AssistantMessage`: `usePacketDisplay(node)` →
  `<Renderer packets processed/>` inside `<View className="px-12">`; `AgentTimeline` above; `CitedSources` (9a)
  below. `hasContent = Renderer != null && packets.length > 0`.
- `mobile/src/chat/streamingModels.ts` — `PacketType` currently: `MESSAGE_START/DELTA/END`, `STOP`,
  `SECTION_END`, `ERROR`, `CITATION_INFO`, `SEARCH_TOOL_DOCUMENTS_DELTA`, `OPEN_URL_DOCUMENTS`. **`Placement`
  already carries all 4 fields** (`turn_index`, `tab_index`, `sub_turn_index`, `model_index`). Must **add**
  `REASONING_START/DELTA/DONE` (+ `TOP_LEVEL_BRANCHING` for grouping tolerance).
- `mobile/src/chat/contracts/documents.ts` — full `SearchDoc`/`StreamingCitation`/`CitationMap` (9a). Reused by
  the **deferred** search/fetch renderers, not by reasoning.
- 9a source-UI (`SourceRow`/`SourceIcon`/`openSource`/`CitedSources`) — reusable by the **deferred** search/fetch
  renderers.

**Backend (reasoning packets — already emitted, no backend change):** `ReasoningStart type="reasoning_start"`
(no fields), `ReasoningDelta type="reasoning_delta" {reasoning: str}`, `ReasoningDone type="reasoning_done"`,
from `backend/onyx/chat/llm_step.py`, carrying `Placement.turn_index/tab_index`. **There is NO `message_end` on
the wire** — the whole turn completes only via `OverallStop (type="stop")`. **`SECTION_END` is usually
client-synthesized** (web injects it into prior groups on a new `turn_index` and into all open groups on STOP —
this is how a step is marked "complete"). `TopLevelBranching {num_parallel_branches}` is pre-parallel metadata.

**Web source-of-truth (parity target), all under `web/src/app/app/message/messageComponents/`:**

- Grouping: `timeline/hooks/packetProcessor.ts` (group by `${turn_index}-${tab_index ?? 0}`, synthesize
  `SECTION_END`, categorize tool/display groups) → `timeline/transformers.ts` (`GroupedPacket[]` →
  `TransformedStep[]` → `TurnGroup[]`; `isParallel = >1 step share a turn_index`).
- Composition: `AgentMessage.tsx` runs `usePacketProcessor` + `usePacedTurnGroups` (200ms staggered reveal) →
  `<AgentTimeline>` above + final-answer `RendererComponent` below.
- Shell: `AgentTimeline.tsx` + `useTimelineUIState` (7 states: `EMPTY / DISPLAY_CONTENT_ONLY /
  STREAMING_SEQUENTIAL / STREAMING_PARALLEL / STOPPED / COMPLETED_COLLAPSED / COMPLETED_EXPANDED`) +
  `useTimelineExpansion` (default collapsed; auto-collapse on stop/answer-start unless `userHasToggled`) +
  `useTimelineHeader` (shimmer header text) + `useTimelineMetrics`.
- Per-step: `TimelineRendererComponent` (per-step `isExpanded`, `renderType = override ?? (isExpanded?FULL:COMPACT)`)
  + `StepContainer` (`TimelineIconColumn` rail + `TimelineSurface` tint + `TimelineStepContent` header+collapse+body);
  Done/Stopped terminal step appended.
- Renderer contract (`interfaces.ts`): **render-prop** `MessageRenderer<T,S>` — computes `RendererResult[]`
  (`{icon, status, content, expandedText?, supportsCollapsible?, alwaysCollapsible?, timelineLayout?,
  noPaddingRight?, surfaceBackground?}`) and calls `children(results)`; the parent `StepContainer` owns the wrapper.
- Reasoning renderer: `timeline/renderers/reasoning/ReasoningRenderer.tsx` — `SvgCircle` icon, status
  `"Thinking"` (or extracted markdown heading), `ExpandableTextDisplay` of streamed reasoning markdown, 500ms
  min-thinking gate.

**Mobile primitives + gotchas (from render-infra scan):** available — `View`, `Text` (font+color enum), `Icon`,
`Separator`, `Button`, `Card`, `Content/ContentAction`, `Spinner` (RN `Animated`, jest-safe), `StreamingMarkdown`
(enriched-markdown; colors must resolve to concrete hex via `varsLight/varsDark` + `textPresets` from
`@onyx-ai/shared/native` — NativeWind classes don't apply inside the markdown lib), `reanimated 4.3.1` (shimmer
today; `ChatSurface` uses `LinearTransition/FadeIn/FadeOut`). **No `Collapsible`/`Accordion` primitive exists** —
expand/collapse is net-new (ASK owner: port web UX vs compose reanimated). **No chevron-up** (rotate
`chevron-down`); **no brain/reasoning icon** and **no plain circle** glyph (web reasoning uses `SvgCircle`) —
adding an icon is a small owner-port decision. NativeWind spacing is **pixel-valued** (class number == px). No
hover on RN (drop web `isHover` branches). **reanimated jest gotcha**: keep pure logic (grouping / step
derivation / state machine) in reanimated-free modules; import leaf components directly. Streaming re-render
perf: memoize rows, coalesce updates; auto-collapse height animation can jank mid-stream (prefer fixed-height
summary + tap-to-expand). Accessibility: trigger = `accessibilityRole="button"` + `accessibilityState={{expanded}}`;
collapsed children removed from AX/focus tree.

## Industry best practices

- **Progressive disclosure is the mainstream** — collapse-by-default; during streaming show a compact
  "Thinking… (Ns)" label with an animated glyph + elapsed timer; auto-collapse to a one-line summary on
  completion; **do not dump full chain-of-thought by default** (DeepSeek-style firehose is called out as
  overwhelming). — <https://www.digestibleux.com/p/how-ai-models-show-their-reasoning>
- **Agent-UX "Activity Timeline"** — collapsible verbosity, a pinned "current step", tiered transparency; a
  scrolling chat thread is a poor workflow tracker, so a structured timeline (not inline text) is the right
  container. — <https://hatchworks.com/blog/ai-agents/agent-ux-patterns/>
- **Touch disclosure accessibility** — trigger must expose expanded/collapsed state; a collapsed panel's children
  must be removed from the AX/focus tree, not just visually hidden. — <https://www.w3.org/WAI/ARIA/apg/patterns/accordion/>,
  <https://webaim.org/techniques/disclosures/>
- **RN streaming re-render pitfalls** — memoize rows (`React.memo`) + `useCallback` `renderItem`; don't hand every
  row fresh object/function identities each tick; coalesce/throttle stream `setState` (don't setState per token).
  — <https://reactnative.dev/docs/optimizing-flatlist-configuration>
- **Hover→touch trap** — every desktop hover-reveal must become an always-visible or explicit-tap affordance with
  a real hit target (RN has no hover at all). — <https://uxpickle.com/alternatives-to-hover-interaction-on-touchscreens/>
- **RN timeline/step-indicator libs are thin/unmaintained** — expect to **build** the rail/dot/collapsible node
  from primitives; existing libs are linear form-wizard steppers, not streaming/nested timelines. —
  <https://www.npmjs.com/package/react-native-step-indicator>

## Approaches

### Approach A — Simplicity-First: "Lean Steps" (grouping-in-processor + reasoning leaf into the existing rail)

Extend exactly two existing seams and add one leaf. The grouping lives **inside** the already-pure
`messageProcessor` (emits a new `steps: TimelineStep[]` on `ProcessedMessageState`), so the whole
`usePacketDisplay` full-recompute-per-flush path stays untouched and jest-safe. Feed the **existing**
`AgentTimeline` stub real reasoning steps and add one `ReasoningStep` leaf (streamed `StreamingMarkdown` body +
tap-to-toggle collapse, leaf-local elapsed timer). The flat `{packets, processed}` renderer contract is preserved
verbatim — **reasoning is timeline-resident, not a registry renderer**, so `findRenderer`/`RENDERERS` and the 9a
citations path are undisturbed. No web machinery ported (no render-prop contract, no 7-state machine, no pacing).

- **Files:** MODIFY `streamingModels.ts` (+4 enum, +4 interfaces), `messageProcessor.ts` (grouping →
  `steps`/`stepByKey`), `AgentTimeline.tsx` (render `TimelineStep[]`, `switch(kind)`), `MessageRow.tsx` (pass
  steps; refine `isLoading`); NEW `ReasoningStep.tsx`, reasoning grouping unit tests.
- **Est:** ~360–420 LOC, **1 PR**.
- **Trade-off:** smallest surface, zero risk to 9a, fully unit-testable pure grouping; but no pacing / no 7-state
  header / no per-step render-prop contract, and the 2nd renderer slots in via a new `kind` + a `case` (not
  `findRenderer`), i.e. a bounded refactor of `AgentTimeline` when a real tool needs tint surfaces / per-step
  collapse.
- **Follow-up fit:** each deferred phase adds a `kind` + reducer cases + a leaf + one `case`; 9a's SourceRow drops
  into search/fetch leaves; the heavier machinery (pacing, render-prop `RendererResult`) is introduced as a
  bounded evolution of this seam **when a real tool justifies it**, not before.

### Approach B — Flexibility-First: "The Extensible Step Seam"

A pure turn/tab **grouping module** (`chat/timeline/grouping.ts`) runs **alongside** the existing flat
`processPackets` (both hosted via `useMemo`, honoring the refs-lint ban), producing `TurnGroup[]` of
`TransformedStep[]`. Each step is resolved by a **priority-ordered step registry** (mirroring web `findRenderer`)
to a step renderer that returns a mobile analog of web's **`RendererResult` data contract (NOT JSX)** — a plain
object return, simpler than web's render-prop but equally extensible. A single **`StepContainer`** (rail + tinted
surface + header + collapse body) owns all chrome; renderers never draw their own wrapper. Reasoning is renderer
#1 (and last-in-chain fallback). `messageProcessor` stays flat (grouping is a sibling, honoring its header
comment). Adds a lean `useTimelineExpansion` + lean `useTimelineUIState`, and a net-new `Collapsible` primitive +
reasoning icon (both owner-ASK).

- **Files:** NEW `chat/timeline/{grouping,stepContract,stepRegistry}.ts`,
  `chat/timeline/renderers/reasoning/ReasoningRenderer.tsx`, `components/chat/timeline/StepContainer.tsx`,
  `components/chat/timeline/{useTimelineExpansion,useTimelineUIState}.ts`, `components/ui/collapsible.tsx`
  (ASK), `icons/reasoning-circle.tsx` (ASK); MODIFY `streamingModels.ts`, `usePacketDisplay.ts` (+turnGroups),
  `AgentTimeline.tsx`, `MessageRow.tsx`.
- **Est:** ~1,810 LOC (prod+test), **2 PRs** — 9b-1 pure engine (grouping + contract + registry + reasoning
  derivation + tests, no UI), 9b-2 UI + wiring (Collapsible, StepContainer, expansion/uiState, view layer,
  AgentTimeline rewrite).
- **Trade-off:** every deferred phase is a single new file (predicate + renderer returning `RendererResult`) with
  zero edits to grouping/container/collapse/MessageRow — retrofit cost amortized to ~0; but ~2× the LOC of A and
  it introduces contract fields (`alwaysCollapsible`, `timelineLayout`) that reasoning barely exercises (some
  speculative until phase 2), plus 2 owner-gated artifacts add decision latency.
- **Follow-up fit:** near-perfect — this **is** the seam. search/fetch reuse 9a's SourceRow verbatim; parallel
  tabs already distinguished in the key; `model_index` tolerated; nesting is the only phase that may extend
  `groupStepsByTurn`.

### Approach C — Full-Parity: "Faithful Shell First"

Port web's **entire timeline shell 1:1 now** — grouping + `transformers` + `usePacedTurnGroups` (200ms stagger) +
the full `useTimelineUIState` (7 states) + `useTimelineExpansion` + `useTimelineHeader` + `useStreamingDuration`
(live "Ns"/"Thought for {duration}") + `useTimelineMetrics` + the render-prop renderer contract + `StepContainer`
+ `TimelineRendererComponent` + Streaming/Stopped/Completed headers + Done/Stopped terminal step — wiring **only**
the reasoning renderer body. Keeps mobile's recompute-per-flush model (web's ref-held `usePacketProcessor` is
illegal here) by making grouping a pure function; `usePacedTurnGroups` must be **restructured off web's
render-time ref reads** to satisfy the refs lint. The shell is behaviorally indistinguishable from web with
reasoning-only content, so deferred phases only add renderer bodies.

- **Files:** ~22 new + 6 modified (grouping, transformers, interfaces, pacing hook, 4 state/header/metrics hooks,
  duration hook, 3 rail/surface/content primitives, StepContainer + TimelineRendererComponent, 3 header
  components, ReasoningRenderer, Collapsible/ExpandableTextDisplay (ASK), circle icon, AgentTimeline rewrite;
  MODIFY `streamingModels`, `usePacketDisplay`, `MessageRow`, `registry`).
- **Est:** ~3,700–4,300 LOC, **honestly 5–6 PRs** (wire → pacing → state → primitives → renderer → headers+composition).
- **Trade-off:** shell is web-faithful day one (header/timer/auto-collapse/stagger/Done-Stopped/tint surfaces) and
  every deferred renderer is a pure additive with zero shell rework and zero drift; but by far the most LOC/review
  surface for a reasoning-only phase, large tracts of the 7-state machine ship as **dead paths** until parallelism
  exists, pacing + auto-collapse height animation add real streaming-perf/jank risk, and `usePacedTurnGroups`
  (restructured off render-time refs) is the highest-bug-density file with behavioral-divergence risk.
- **Follow-up fit:** best-in-class — parallel-tab data model + `sub_turn_index`/`model_index` tolerance built-in
  and dormant; but that maximal extensibility is the entire justification for paying the shell cost up front.

## Cross-comparison

- **LOC / PRs:** A ≈ 400 (1 PR) · B ≈ 1,800 (2 PRs) · C ≈ 4,000 (5–6 PRs). All three add the same
  `streamingModels` packet types and the same grouping **key** (`${turn_index}-${tab_index ?? 0}`, `model_index`
  ignored) — they diverge only on how much shell/contract is built now.
- **Refs-lint constraint** binds all three: none may port web's render-mutated `usePacketProcessor` ref; grouping
  is a pure `useMemo`. C carries the most risk here (pacing hook restructure).
- **Extensibility vs YAGNI:** A defers the render-prop/pacing/state-machine until a 2nd renderer proves the shape
  (risk: bounded `AgentTimeline` refactor later); B front-loads the **data contract + registry** (the genuinely
  expensive-to-retrofit part) but not pacing/full-state; C front-loads **everything** (risk: dead code + jank +
  porting a moving target).
- **Parity now:** only C makes the *shell* web-faithful immediately (shimmer header text, live timer, staggered
  reveal, auto-collapse-on-answer, Done/Stopped). A and B render reasoning correctly but with a simpler shell;
  the roadmap's parity requirement is about *look AND structure* — reasoning-only, A/B can still match the
  step/rail/collapse shape while deferring the header state machine.
- **Owner-ASK artifacts:** A needs none (no new primitive/icon). B and C both need the `Collapsible` primitive +
  a reasoning icon decision before UI lands.

## Chosen approach

**Approach C — "Faithful Shell First" (Full parity).** Selected at GATE 1 (owner, 2026-07-16).

**Owner directive (verbatim intent):** _"I want something that matches web. I am going to build the renderers
immediately — current PR goes in [first], then the renderers. I don't want any refactor later. I'm fine with any
number of lines — I want everything, whatever way we need it. Just don't drift away from web."_

**What this means for 9b:**

- Port web's **entire timeline shell 1:1**: the render-prop `MessageRenderer<T,S>` contract + `RendererResult` /
  `RenderType` (HIGHLIGHT/FULL/COMPACT/INLINE), the pure grouping (`packetProcessor` → `transformers`),
  `usePacedTurnGroups` (200ms staggered reveal), the full `useTimelineUIState` (7 states) + `useTimelineExpansion`
  + `useTimelineHeader` + `useStreamingDuration` + `useTimelineMetrics`, `StepContainer` +
  `TimelineRendererComponent` + the rail/surface/content primitives, the Streaming/Stopped/Completed headers, and
  the Done/Stopped terminal step. Adopt **web's render-prop renderer contract exactly** (not Approach B's
  simplified data-object) so each future web renderer ports **near-mechanically**.
- Wire **only the reasoning renderer** body in 9b. The dormant parallel-tab state (`isParallel`,
  `STREAMING_PARALLEL`, `showParallelTabs`) and `sub_turn_index`/`model_index` tolerance ship with the shell (as
  in web) so parallelism / nesting / multi-model are later **UI-only** follow-ups with no seam change.
- **Scope of the 9b feature-flow (confirmed):** this spec covers the **full shell + reasoning renderer** only.
  Each tool renderer (internal/web search, fetch/open_url, python/code, coding-agent+bash, custom-tool,
  deep-research + nested agents, memory) is its **own immediate follow-up PR** on the zero-refactor seam, spec'd
  per-phase (grill-first) as the owner builds it — not designed here. The design must nonetheless fully specify
  the render-prop contract + the per-tool renderer **inventory/dispatch** so those follow-ups are mechanical.

**The one accepted divergence from web (platform-forced, behavior-preserving):** web's `usePacketProcessor` and
`usePacedTurnGroups` read `stateRef.current` **during render** (reset detection / bypass), which mobile's
`react-hooks/refs` lint **forbids**. These are restructured to a `useMemo`-recompute + effect-only-ref-write model
that preserves the same grouping output and the same 200ms reveal timing. This is an implementation-level
necessity, **not** a look/structure drift — the rendered timeline is web-faithful. Documented in `03-detailed-design.md`.

