> Status: active · Task: 9b-timeline · Approach: C — Faithful Shell First

# Mobile Chat 9b — Agentic Reasoning Timeline · Detailed Design

Faithful 1:1 port of web's agent timeline shell (`web/src/app/app/message/messageComponents/**`) to
`mobile/`, wiring only the reasoning renderer. Line references below are to the web source (source of truth).
Mobile spacing is **pixel-valued** (class number = px); web token **rem** strings are baked to px (rem×16),
and web utility classes are translated (web Tailwind step N → mobile N×4 px). No backend/DB change.

## Database design

**N/A** — no persistence change. The timeline is derived entirely from the already-streamed/hydrated
`Packet[]` on each assistant message node. (One in-memory addition: a per-run `streamingStartedAt` timestamp for
the live elapsed timer — see Important Notes §7.)

## Class / interface design

### 1. Packet contracts — `mobile/src/chat/streamingModels.ts` (modified)

Add the **full web `PacketType` enum values** (so the ported grouping engine + `packetHelpers` +
`toolDisplay` compile with zero future enum change), plus the interfaces the **engine and shell** dereference.
Per-tool obj interfaces beyond these are added by each tool renderer's own phase.

```ts
// New PacketType members (mirror web streamingModels.ts exactly; string values = backend wire types):
REASONING_START = "reasoning_start", REASONING_DELTA = "reasoning_delta", REASONING_DONE = "reasoning_done",
TOP_LEVEL_BRANCHING = "top_level_branching",
SEARCH_TOOL_START = "search_tool_start", SEARCH_TOOL_QUERIES_DELTA = "search_tool_queries_delta",
SEARCH_TOOL_FILTER_DELTA = "search_tool_filter_delta",
FETCH_TOOL_START = "open_url_start", OPEN_URL_URLS = "open_url_urls",
PYTHON_TOOL_START = "python_tool_start", PYTHON_TOOL_DELTA = "python_tool_delta",
TOOL_CALL_ARGUMENT_DELTA = "tool_call_argument_delta",
CUSTOM_TOOL_START = "custom_tool_start", CUSTOM_TOOL_ARGS = "custom_tool_args", CUSTOM_TOOL_DELTA = "custom_tool_delta",
FILE_READER_START = "file_reader_start", FILE_READER_RESULT = "file_reader_result",
MEMORY_TOOL_START = "memory_tool_start", MEMORY_TOOL_DELTA = "memory_tool_delta", MEMORY_TOOL_NO_ACCESS = "memory_tool_no_access",
IMAGE_GENERATION_TOOL_START = "image_generation_start", IMAGE_GENERATION_TOOL_DELTA = "image_generation_final",
DEEP_RESEARCH_PLAN_START = "deep_research_plan_start", DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta",
RESEARCH_AGENT_START = "research_agent_start",
INTERMEDIATE_REPORT_START = "intermediate_report_start", INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta",
INTERMEDIATE_REPORT_CITED_DOCS = "intermediate_report_cited_docs",
CODING_AGENT_START = "coding_agent_start", CODING_AGENT_THINKING_DELTA = "coding_agent_thinking_delta",
CODING_AGENT_FINAL = "coding_agent_final", BASH_TOOL_START = "bash_tool_start", BASH_TOOL_DELTA = "bash_tool_delta",

// New obj interfaces the ENGINE/SHELL read now (others deferred to their renderer phase):
interface ReasoningStart  extends BaseObj { type: PacketType.REASONING_START }
interface ReasoningDelta  extends BaseObj { type: PacketType.REASONING_DELTA; reasoning: string }
interface ReasoningDone   extends BaseObj { type: PacketType.REASONING_DONE }
interface TopLevelBranching extends BaseObj { type: PacketType.TOP_LEVEL_BRANCHING; num_parallel_branches: number }
interface ToolCallArgumentDelta extends BaseObj { type: PacketType.TOOL_CALL_ARGUMENT_DELTA; tool_type: string; argument_deltas: Record<string, unknown> }
interface SearchToolStart extends BaseObj { type: PacketType.SEARCH_TOOL_START; is_internet_search?: boolean }
interface CustomToolStart extends BaseObj { type: PacketType.CUSTOM_TOOL_START; tool_name?: string; tool_id?: number | null }
interface ImageGenerationToolDelta extends BaseObj { type: PacketType.IMAGE_GENERATION_TOOL_DELTA; images?: { file_id: string }[] }
// extend existing MessageStart with: pre_answer_processing_seconds?: number | null
export const CODE_INTERPRETER_TOOL_TYPES = { PYTHON: "python" } as const;
// Add all new obj interfaces to the ObjTypes union.
```

### 2. Grouping engine — `mobile/src/chat/messageProcessor.ts` (modified → faithful port of web `packetProcessor.ts`)

`ProcessedMessageState` gains web's grouping fields (existing 9a fields kept for `CitedSources`):

```ts
export interface ProcessedMessageState {
  nodeId: number; nextPacketIndex: number;
  // 9a (kept): citations, seenCitationDocIds, citationMap, documentMap, isComplete, stopReason
  // 9b (new, mirroring web ProcessorState packetProcessor.ts:32-69):
  groupedPacketsMap: Map<string, Packet[]>;
  seenGroupKeys: Set<string>;
  groupKeysWithSectionEnd: Set<string>;
  expectedBranches: Map<number, number>;
  toolGroupKeys: Set<string>;
  displayGroupKeys: Set<string>;
  isGeneratingImage: boolean; generatedImageCount: number;
  finalAnswerComing: boolean; stopPacketSeen: boolean;
  toolProcessingDuration: number | undefined;
  toolGroups: GroupedPacket[];
  potentialDisplayGroups: GroupedPacket[];
}
export interface GroupedPacket { turn_index: number; tab_index: number; packets: Packet[] }
```

New internal functions (ported verbatim, pure): `getGroupKey`, `injectSectionEnd`, `handleTurnTransition`,
`handleStopPacket` (grouping half), `handleStreamingStatusPacket`, `handleToolAfterMessagePacket`,
`buildGroupsFromKeys`, `hasContentPackets`, `CONTENT_PACKET_TYPES_SET`, `FINAL_ANSWER_PACKET_TYPES_SET`.
`processPacket` gains the per-packet flow (packetProcessor.ts:323-382). See Important Notes §2 for the exact
`section_end` algorithm.

### 3. Pure step helpers — `mobile/src/chat/timeline/` (new)

- `transformers.ts` — `TransformedStep {key, turnIndex, tabIndex, packets}`, `TurnGroup {turnIndex, steps, isParallel}`,
  `transformPacketGroup`, `transformPacketGroups`, `groupStepsByTurn` (isParallel = `steps.length > 1`).
- `packetUtils.ts` — `isToolPacket`, `isActualToolCallPacket`, `isDisplayPacket`, `isSearchToolPacket`,
  `isStreamingComplete`, `isFinalAnswerComing`, `isFinalAnswerComplete`, `groupPacketsByTurnIndex`,
  `getTextContent`, `getCitations`.
- `packetHelpers.ts` — `COLLAPSED_STREAMING_PACKET_TYPES`, `CODING_AGENT_PACKET_TYPES`, `isReasoningPackets`,
  `isSearchToolPackets`, `isPythonToolPackets`, `isResearchAgentPackets`, `isCodingAgentPackets`,
  `isDeepResearchPlanPackets`, `isMemoryToolPackets`, `stepSupportsCollapsedStreaming`,
  `stepHasCollapsedStreamingContent`.
- `toolDisplay.ts` — `getToolKey`, `parseToolKey`, `getToolName` (pure), `hasToolError`, `isToolComplete`
  (sub_turn_index-aware for research/coding). **Icon factory split out** to `components/chat/timeline/toolIcons.ts`
  (returns a mobile icon component, not JSX from web react-icons).

### 4. Renderer contract — `mobile/src/components/chat/renderers/timelineContract.ts` (new)

Ported verbatim from web `interfaces.ts` (types only; `JSX.Element` = RN element):

```ts
export enum RenderType { HIGHLIGHT="highlight", FULL="full", COMPACT="compact", INLINE="inline" }
export type TimelineLayout = "timeline" | "content";
export type TimelineSurfaceBackground = "tint" | "transparent" | "error";
export interface RendererResult {
  icon: IconFunctionComponent | null;            // mobile icon type (from @/icons/types)
  status: string | React.ReactElement | null;
  content: React.ReactElement;
  supportsCollapsible?: boolean; alwaysCollapsible?: boolean;
  timelineLayout?: TimelineLayout; noPaddingRight?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
  // NOTE: web's `expandedText?` is DEAD (0 readers) — DROPPED in the port.
}
export type RendererOutput = RendererResult[];
export interface FullChatState {              // mobile subset
  agent: MinimalAgent | null;
  citations?: CitationMap; documentMap?: Map<string, SearchDoc>;
  openSource?: (doc: SearchDoc) => void;      // 9a
}
export type MessageRenderer<T extends Packet, S extends Partial<FullChatState>> = React.ComponentType<{
  packets: T[]; state: S; messageNodeId?: number; hasTimelineThinking?: boolean;
  onComplete: () => void; renderType: RenderType; animate: boolean;
  stopPacketSeen: boolean; stopReason?: StopReason; isLastStep?: boolean;
  children: (result: RendererOutput) => React.ReactElement;   // isHover DROPPED (no hover on RN)
}>;
export interface TimelineRendererResult extends RendererResult {
  isExpanded: boolean; onToggle: () => void; renderType: RenderType;
  isLastStep: boolean; timelineLayout: TimelineLayout;
}
```

### 5. Timeline state hooks — signatures (ported 1:1 from web; see Important Notes §1 for the two restructured ones)

```ts
usePacketProcessor(packets: Packet[], nodeId: number): UsePacketProcessorResult   // RESTRUCTURED
usePacedTurnGroups(toolTurnGroups, displayGroups, stopPacketSeen, nodeId, finalAnswerComing):
   { pacedTurnGroups: TurnGroup[]; pacedDisplayGroups: GroupedPacket[]; pacedFinalAnswerComing: boolean } // RESTRUCTURED
useTimelineUIState(input: TimelineUIStateInput): TimelineUIStateResult             // pure, 1:1
useTimelineExpansion(stopPacketSeen, lastTurnGroup, hasDisplayContent): TimelineExpansionState  // 1:1
useTimelineHeader(turnGroups, stopReason?, isGeneratingImage?): TimelineHeaderResult // 1:1 (see §6)
useStreamingDuration(isStreaming, startTime?, backendDuration?): number             // 1:1 (RAF→interval ok)
useTimelineMetrics(turnGroups, userStopped): TimelineMetrics                         // 1:1
useTimelineStepState(turnGroups): MemoryStepState                                    // 1:1 (dormant/minimal)
```

`TimelineUIState` (7 states), `TimelineUIStateInput`/`Result`, `TimelineExpansionState`, `TimelineMetrics` — exact
shapes per `01-research.md` and the deepread extract (`.context/pr9b-deepread/timeline-hooks-state.md`).

## New files

| File | Responsibility |
|------|----------------|
| `mobile/src/chat/timeline/transformers.ts` | GroupedPacket→TransformedStep→TurnGroup; parallel detection |
| `mobile/src/chat/timeline/packetUtils.ts` | packet categorizers (tool/display/search/text/citations) |
| `mobile/src/chat/timeline/packetHelpers.ts` | per-family predicates + collapsed-streaming sets |
| `mobile/src/chat/timeline/toolDisplay.ts` | tool key parse, name, completion, error (pure) |
| `mobile/src/chat/timeline/reasoningState.ts` | `extractFirstParagraph` + `constructCurrentReasoningState` (pure) |
| `mobile/src/components/chat/renderers/timelineContract.ts` | RenderType/RendererResult/MessageRenderer/FullChatState |
| `mobile/src/components/chat/renderers/findRenderer.ts` | priority-ordered dispatch (reasoning last) |
| `mobile/src/components/chat/renderers/RendererComponent.tsx` | final-answer dispatch at FULL (+ mixed-content stub) |
| `mobile/src/components/chat/renderers/ReasoningRenderer.tsx` | the one wired step renderer |
| `mobile/src/hooks/timeline/usePacketProcessor.ts` | host reducer + derive turn groups (restructured) |
| `mobile/src/hooks/timeline/usePacedTurnGroups.ts` | 200ms staggered reveal + answer gating (restructured) |
| `mobile/src/hooks/timeline/useTimelineUIState.ts` | 7-state machine + show/style booleans |
| `mobile/src/hooks/timeline/useTimelineExpansion.ts` | collapse state + auto-collapse |
| `mobile/src/hooks/timeline/useTimelineHeader.ts` | header text map |
| `mobile/src/hooks/timeline/useStreamingDuration.ts` | live elapsed timer (frozen by backend duration) |
| `mobile/src/hooks/timeline/useTimelineMetrics.ts` | step count + last-step flags |
| `mobile/src/hooks/timeline/useTimelineStepState.ts` | memory-only extraction (dormant) |
| `mobile/src/components/chat/timeline/primitives/timelineTokens.ts` | px token constants (rail 36, icon 12, …) |
| `mobile/src/components/chat/timeline/primitives/TimelineRoot.tsx` | outer column |
| `mobile/src/components/chat/timeline/primitives/TimelineHeaderRow.tsx` | rail cell (avatar) + header slot |
| `mobile/src/components/chat/timeline/primitives/TimelineRow.tsx` | icon column + content row |
| `mobile/src/components/chat/timeline/primitives/TimelineIconColumn.tsx` | connector rail + node icon |
| `mobile/src/components/chat/timeline/primitives/TimelineSurface.tsx` | tint/error surface + rounding |
| `mobile/src/components/chat/timeline/primitives/TimelineStepContent.tsx` | header row + collapse control + body |
| `mobile/src/components/chat/timeline/StepContainer.tsx` | composes the primitives into a step frame |
| `mobile/src/components/chat/timeline/TimelineRendererComponent.tsx` | per-step expand state + renderType derive |
| `mobile/src/components/chat/timeline/TimelineStep.tsx` | step composer (children render-prop → StepContainer) |
| `mobile/src/components/chat/timeline/ExpandedTimelineContent.tsx` | maps TurnGroup[]→steps + Done/Stopped |
| `mobile/src/components/chat/timeline/CollapsedStreamingContent.tsx` | streaming live preview of last step |
| `mobile/src/components/chat/timeline/ParallelTimelineTabs.tsx` | **dormant stub** (linearizes for 9b) |
| `mobile/src/components/chat/timeline/headers/StreamingHeader.tsx` | shimmer text + live seconds + fold |
| `mobile/src/components/chat/timeline/headers/CompletedHeader.tsx` | "Thought for X · N steps" fold |
| `mobile/src/components/chat/timeline/headers/StoppedHeader.tsx` | "Interrupted Thinking" + N steps |
| `mobile/src/components/chat/timeline/headers/ParallelStreamingHeader.tsx` | **dormant stub** |
| `mobile/src/components/chat/timeline/toolIcons.ts` | packet-type → mobile icon map (for headers/tabs) |
| `mobile/src/components/chat/timeline/ReasoningTextWindow.tsx` | maxHeight markdown window (ExpandableTextDisplay analog) |
| `mobile/src/icons/{circle,fold,expand,check-circle}.tsx` | new icons (ASK owner) — see §6 |
| `mobile/src/chat/timeline/__tests__/*.test.ts` | grouping / section-end / transformers / pacing / uiState / reasoningState |

**Modified:** `mobile/src/chat/streamingModels.ts` (§1), `mobile/src/chat/messageProcessor.ts` (§2),
`mobile/src/components/chat/renderers/registry.ts` (→ re-export `findRenderer`), `MessageTextRenderer.tsx`
(migrate to render-prop contract), `mobile/src/hooks/usePacketDisplay.ts` (fold into the new hooks / expose
`processed` for `CitedSources`), `mobile/src/components/chat/MessageRow.tsx` (AssistantMessage → AgentMessage
analog), `mobile/src/components/chat/AgentTimeline.tsx` (stub → full shell), `mobile/src/components/chat/StreamingMarkdown.tsx`
(+ optional `muted` variant), and the PR-3 stream controller/store (capture `streamingStartedAt`, §7).

## File structure (tree)

```
mobile/src/
├── chat/
│   ├── streamingModels.ts                 (modified: full PacketType enum + reasoning/branch/tool-arg objs)
│   ├── messageProcessor.ts                (modified: + web packetProcessor grouping/section-end/finalAnswer)
│   └── timeline/                          (new — pure, reanimated-free, unit-tested)
│       ├── transformers.ts · packetUtils.ts · packetHelpers.ts · toolDisplay.ts · reasoningState.ts
│       └── __tests__/
├── hooks/
│   ├── usePacketDisplay.ts                (modified: expose processed for CitedSources)
│   └── timeline/                          (new)
│       ├── usePacketProcessor.ts (restructured) · usePacedTurnGroups.ts (restructured)
│       ├── useTimelineUIState.ts · useTimelineExpansion.ts · useTimelineHeader.ts
│       └── useStreamingDuration.ts · useTimelineMetrics.ts · useTimelineStepState.ts
├── components/chat/
│   ├── MessageRow.tsx                     (modified: AssistantMessage → AgentMessage analog)
│   ├── AgentTimeline.tsx                  (modified: stub → full shell)
│   ├── StreamingMarkdown.tsx              (modified: + muted variant)
│   ├── renderers/
│   │   ├── registry.ts                    (modified: re-export findRenderer)
│   │   ├── timelineContract.ts · findRenderer.ts · RendererComponent.tsx · ReasoningRenderer.tsx  (new)
│   │   └── MessageTextRenderer.tsx        (modified: → render-prop contract)
│   └── timeline/                          (new)
│       ├── StepContainer.tsx · TimelineRendererComponent.tsx · TimelineStep.tsx
│       ├── ExpandedTimelineContent.tsx · CollapsedStreamingContent.tsx
│       ├── ParallelTimelineTabs.tsx (dormant) · toolIcons.ts · ReasoningTextWindow.tsx
│       ├── primitives/ (timelineTokens, TimelineRoot/HeaderRow/Row/IconColumn/Surface/StepContent)
│       └── headers/ (StreamingHeader, CompletedHeader, StoppedHeader, ParallelStreamingHeader[dormant])
└── icons/  circle.tsx · fold.tsx · expand.tsx · check-circle.tsx   (new; stop-circle already exists from PR3)
```

## What each file will contain

- **`messageProcessor.ts`** — the pure reducer: `processPackets(state, rawPackets)` loops from `nextPacketIndex`,
  routes each packet through `handleTurnTransition` (synthesizes `section_end` into prior groups on a new
  `turn_index`), grouping/categorization, citations/docs (9a), `handleStreamingStatusPacket` (finalAnswerComing +
  `pre_answer_processing_seconds`), `handleStopPacket` (synthesizes `section_end` into all open groups), then
  rebuilds `toolGroups`/`potentialDisplayGroups` via `buildGroupsFromKeys` (spreads packets → new array; filters
  `hasContentPackets`; sorts by turn then tab).
- **`usePacketProcessor.ts`** — `const state = useMemo(() => processPackets(createInitialState(nodeId), packets), [nodeId, packets])`
  (lint-safe full recompute), then `toolTurnGroups = useMemo(groupStepsByTurn(transformPacketGroups(state.toolGroups)))`,
  `displayGroups` gated on `finalAnswerComing || toolGroups.length===0`, `renderComplete`/`forceShowAnswer` as
  `useState`, `isComplete = stopPacketSeen && renderComplete`. Returns `UsePacketProcessorResult`.
- **`usePacedTurnGroups.ts`** — `useState(revealedStepKeys: Set)` + `useState(toolPacingComplete)` written by an
  effect; timer handle in a ref (effect/cleanup only, never read in render). Effect: bypass if `stopPacketSeen &&
  nothing revealed && groups exist`; first step immediate, rest queued 200 ms apart (`PACING_DELAY_MS=200`); `stop`
  flushes all. Memos build `pacedTurnGroups` (filter revealed), `pacedDisplayGroups` (withheld until pacing
  complete), `pacedFinalAnswerComing`. Web's `prevPacedRef` referential-stabilization is **dropped**.
- **`useTimelineUIState.ts`** — pure `useMemo`: the 6-branch precedence (EMPTY → DISPLAY_CONTENT_ONLY →
  STREAMING_PARALLEL/SEQUENTIAL → STOPPED → COMPLETED_EXPANDED → COMPLETED_COLLAPSED) + `showTintedBackground`,
  `showRoundedBottom`, `showDoneStep`, `showStoppedStep`, `hasDoneIndicator`, `showParallelTabs`,
  `showCollapsedCompact`, `showCollapsedParallel`, `isStreaming`, `isCompleted`, `isActivelyExecuting`.
- **`useTimelineExpansion.ts`** — `isExpanded=useState(false)`, `userHasToggled=useRef(false)` (read only in
  effect), auto-collapse effect on `stopPacketSeen||hasDisplayContent`, parallel-tab sync effect.
- **`useTimelineHeader.ts`** — the exact packet-type→text map (§6). **9b caveat:** the SEARCH sub-labels
  ("Reading" vs "Searching the web", which need `constructCurrentSearchState`) degrade to a generic label until
  the search phase; reasoning → "Thinking", default → "Thinking…". (Documented divergence §8.)
- **`useStreamingDuration.ts`** — `elapsedSeconds` via `requestAnimationFrame` (or `setInterval(1000)`), updates
  only when the integer second changes; returns `backendDuration` if defined (freezes). Reset only when no
  `startTime`.
- **`AgentTimeline.tsx`** — runs `useTimelineExpansion` + `useTimelineUIState` + `useTimelineHeader` +
  `useTimelineMetrics` + `useStreamingDuration`; `TimelineRoot > TimelineHeaderRow(avatar 24 in 36 rail) >
  header`; header switch by `uiState`; body = `CollapsedStreamingContent` (streaming) or
  `ExpandedTimelineContent` (expanded). Memoized.
- **`StepContainer.tsx` + primitives** — `TimelineRow`(`TimelineIconColumn` rail + content); `TimelineSurface`
  (tint/error bg, rounded bottom if last); `TimelineStepContent` (header row height 32 with `status` Text +
  collapse control gated by `supportsCollapsible`, body `pl-1 pb-1`, right gutter 34 unless `noPaddingRight`).
  Rail geometry: 1px line, 8px top connector (hidden if first), 20px node wrapper, 12px icon, flex-fill (hidden
  if last). All hover branches dropped (resting colors: `bg-border-01`, `stroke-text-02`, `bg-background-tint-00`).
- **`TimelineRendererComponent.tsx`** — `isExpanded=useState(defaultExpanded)`, `renderType = override ??
  (isExpanded?FULL:COMPACT)`, `findRenderer(packets)` → render-prop, `enhanceResult` attaches
  `{isExpanded,onToggle,renderType,isLastStep,timelineLayout}`; `children(results.map(enhanceResult))`.
- **`ReasoningRenderer.tsx`** — `constructCurrentReasoningState(packets)` (hasStart/hasEnd/content=join deltas),
  `extractFirstParagraph(content)` (markdown-heading → step title, ≤60 chars), 500 ms min-thinking gate
  (`useState(start)` + timer ref in effect; `animate` gates the floor), then
  `children([{ icon: SvgCircle, status: title ?? "Thinking", content: <ReasoningTextWindow .../>, noPaddingRight:true, supportsCollapsible:true }])`.
- **`ReasoningTextWindow.tsx`** — maxHeight 192px (8×24) overflow-hidden `View` wrapping `StreamingMarkdown
  content={displayContent} isStreaming={!hasEnd} variant="muted"`. (Web's pixel-perfect translateY auto-scroll +
  copy/download modal are **not** ported in 9b — §8.)
- **`findRenderer.ts`** — the full priority chain (chat → deep-research → research-agent → coding-agent →
  web-search → internal-search → image → python → file-reader → custom-tool → fetch → memory → **reasoning
  last**). For 9b only **chat→MessageTextRenderer** and **reasoning→ReasoningRenderer** are wired; the other 11
  predicates are present and return their (not-yet-registered) renderer as `null`, each tagged
  `// PR 9x: <tool>` so a follow-up is a one-line wire-up.
- **`RendererComponent.tsx`** — final-answer path: `findRenderer({packets})` at `RenderType.FULL`; mixed
  chat+image content handler is **stubbed** (image = 9e). Memoized on packet identity + stop flags.
- **`MessageRow.tsx` (AssistantMessage)** — the AgentMessage analog: `usePacketProcessor` + `usePacedTurnGroups`,
  `<AgentTimeline turnGroups=pacedTurnGroups chatState stopPacketSeen finalAnswerComing hasDisplayContent
  toolProcessingDuration/>` above, `pacedDisplayGroups.map(<RendererComponent renderType=FULL/>)` below,
  `<CitedSources/>` (9a) last.

## Integration points

- **`mobile/src/chat/messageProcessor.ts`** (9a) — extended in place; existing citation/document/`isComplete`
  fields preserved so `CitedSources.tsx` and `usePacketDisplay` keep working.
- **`mobile/src/components/chat/renderers/registry.ts` + `MessageTextRenderer.tsx`** (PR 3/9a) — migrated to the
  render-prop `MessageRenderer` contract; the final answer routes through the new `RendererComponent`. Inline
  citation links (9a) and streamed markdown render identically.
- **`mobile/src/components/chat/AgentTimeline.tsx`** (PR 5 stub) — `steps: TimelineStepData[]` seam replaced by
  `turnGroups: TurnGroup[]`; the existing rail geometry + reanimated shimmer are reused/expanded.
- **`mobile/src/components/chat/MessageRow.tsx`** — `AssistantMessage` becomes the composition root; `hasContent`
  gating updated (`isLoading` now driven by `uiState===EMPTY`).
- **`mobile/src/components/chat/StreamingMarkdown.tsx`** (PR 3/9a) — gains a `muted`/`compact` variant so reasoning
  bodies render `text-03` with tight margins (colors still resolved to hex via `varsLight/varsDark`).
- **PR-3 stream controller / `chatSessionStore`** — records `streamingStartedAt` per assistant node (Important
  Notes §7) for the live timer.
- **`mobile/src/components/avatars/AgentAvatar`** (PR 5) — reused at `size={24}` in the rail.
- **`@onyx-ai/shared/native`** — `varsLight/varsDark` + `textPresets` for markdown colors (unchanged pattern).
- **Backend / DB / API** — **untouched.** Reasoning packets already stream from `backend/onyx/chat/llm_step.py`.

## Important notes before implementation

1. **The two ref-during-render restructures (the only accepted divergence).** `usePacketProcessor` (web mutates
   `stateRef.current` during render) → mobile uses a **`useMemo` full recompute** per flush (9a's proven pattern;
   O(n)/flush, fine at chat scale). `usePacedTurnGroups` (web reads pacing refs during render for
   `shouldBypassPacing` + memos) → hoist `revealedStepKeys`/`toolPacingComplete` into **`useState`** written by the
   effect; compute `shouldBypassPacing` from props synchronously; timer handle stays in a ref (effect-only). Both
   are **behavior-preserving**. Verify the first-packet render + 200 ms cadence feel identical on device (a
   reducer-in-effect can add a one-frame delay — §parity-risk in the deepread).
2. **`section_end` synthesis is the correctness core — port it exactly.** `injectSectionEnd(state, key)`:
   idempotent (skip if already ended); parse `{turn,tab}` from key; push a synthetic `{placement:{turn,tab},
   obj:{type:SECTION_END}}` (NO `sub_turn_index` — so research/coding parent-completion works) into the group;
   mark the key done. **Trigger 1:** a real `SECTION_END`/`ERROR` packet. **Trigger 2 (turn transition):** the
   first packet of a **new `turn_index`** injects into every prior `seenGroupKey` not yet ended. **Trigger 3
   (stop):** the first `stop` injects into all open groups. A new *`tab_index`* within a seen turn does **not**
   trigger 2. (packetProcessor.ts:116-133, 190-208, 270-287.)
3. **Full `PacketType` enum now, per-tool interfaces later.** Add every enum value (so the engine/helpers/Sets
   compile with zero future enum edits) but only the obj interfaces the engine/shell dereference (§1). Each tool
   renderer phase adds its own obj interface + wires its `findRenderer` predicate — a one-line change, no engine
   or enum churn. This is the "zero refactor later" guarantee.
4. **`react-hooks/refs` + reanimated jest gotcha.** Keep ALL pure logic (grouping, transformers, packetUtils,
   packetHelpers, toolDisplay, reasoningState, the state-machine math) in **reanimated-free** modules under
   `chat/timeline/` and import leaf components directly in tests. Refs are fine when written/read **only in
   effects/callbacks** (timer handles, `userHasToggled`) — never during render.
5. **Icons + primitives = owner-ASK before UI lands (PR 9b.4).** New icons: `circle` (reasoning node), `fold` /
   `expand` (collapse control — no `chevron-up`, rotate `chevron-down` or add glyphs), `check-circle` (Done).
   `stop-circle` already exists (PR 3). New primitive: a **tertiary icon Button** (confirm the existing mobile
   `Button` covers it, else ASK per the web-parity principle). `x-octagon` (error surface) — confirm/port.
6. **Header text map + tool names (`useTimelineHeader` / `getToolName`).** Port the full map; reasoning →
   "Thinking", `stop_reason===USER_CANCELLED` → StoppedHeader. Tool sub-labels needing `constructCurrentSearchState`
   (search "Reading" vs "Searching the web") degrade to a generic label until the search phase (§8). `getToolName`
   ("Web Search"/"Code Interpreter"/…) is pure and ported so a *rendererless* tool step still gets a real header.
7. **Live timer needs a per-message `streamingStartedAt`.** Web reads a `useStreamingStartTime` store. Mobile:
   the PR-3 stream controller stamps `streamingStartedAt = Date.now()` on the assistant node/run at stream start
   (send + resume); `AgentTimeline` passes it to `useStreamingDuration`. Without it the elapsed label never shows.
   `toolProcessingDuration` (`message_start.pre_answer_processing_seconds`) **freezes** the timer when present.
8. **Documented, intentional divergences from web (per the WEB-PARITY PRINCIPLE — the "as-built" note must list
   these):** (a) the two restructured hooks (§1) — behavior-preserving; (b) shimmer = reanimated **opacity pulse**,
   not web's `background-clip:text` gradient (no RN equivalent) — reuse the existing 9a `ThinkingLabel`; (c)
   `ReasoningTextWindow` = fixed **maxHeight window**, not web's pixel-perfect `translateY` auto-scroll; copy/
   download modal deferred; (d) **`ParallelTimelineTabs`/`ParallelStreamingHeader` dormant** — parallel turns
   **linearized** into a sequential list for 9b (no `@opal` pill Tabs on mobile); (e) SEARCH header sub-labels
   generic until the search phase; (f) entrance/`transition-colors` CSS animations optional (reanimated
   `FadeIn`/`Layout` or dropped); (g) memory tooltip/modal dropped (memory renderer is a later phase); (h) `expandedText`
   dead field dropped; (i) no hover anywhere (resting colors). None change the timeline's look/structure for the
   reasoning path.
9. **Render-prop discipline.** A renderer must call `children(results)` — never return its own `View` tree
   directly — or `StepContainer` can't wrap it. `RenderType` policy: final-answer path = always `FULL`; timeline
   steps = `override ?? (isExpanded?FULL:COMPACT)`. Keep BOTH entry points.
10. **Testing (unit-first — the pure core carries the risk).** Jest over `chat/timeline/**` +
    `hooks/timeline/**` leaf logic: grouping key + the three `section_end` triggers; `groupStepsByTurn`
    parallel detection + turn/tab sort; `transformPacketGroups`; `usePacedTurnGroups` (first-immediate,
    200 ms stagger with fake timers, stop-flush, history-bypass); `useTimelineUIState` all 7 states + booleans;
    `useTimelineExpansion` auto-collapse + userHasToggled; `useStreamingDuration` tick + freeze;
    `reasoningState` heading extraction + delta accumulation; `ReasoningRenderer` 500 ms gate (fake timers).
    Component smoke test: a mocked reasoning packet stream renders a "Thinking" step that collapses to "Thought
    for Xs". **HARD device gate (owner):** on a dev build, a reasoning model shows the streaming shimmer + timer,
    auto-collapse on answer, tap-to-expand, and hydrated (history) render — the agent can't run a device build.
