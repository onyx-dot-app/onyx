> Status: active · Task: 9b-timeline · Approach: **C — Faithful Shell First (full web parity)**

# Mobile Chat 9b — Agentic Reasoning Timeline · High-Level Design

## What it does

When the assistant "thinks" or runs tools before answering, web shows an **agent timeline** above the answer — a
vertical rail of steps (a reasoning "Thinking" step, search/tool steps, …), each with an icon, a status header,
a connector line, and a body you can collapse/expand; while streaming it shows a shimmering "Thinking… (12s)"
header that **auto-collapses** into a "Thought for 12s · 3 steps" pill once the answer starts. 9b ports that
**entire timeline shell to mobile, 1:1**, and wires the **reasoning** step. Every other step type (search, fetch,
python, custom-tool, deep-research, memory) is a later drop-in renderer — the shell already knows how to place it.

## How it works (end-to-end walkthrough)

The mobile chat stream is a flat list of `Packet`s (`{placement, obj}`) that grows as the model streams. Today
each assistant message runs one flat pass over those packets (`messageProcessor`) to pull out citations/documents
and mounts a single answer renderer. 9b inserts web's **grouping + pacing + state-machine** layer between the raw
packets and the on-screen timeline, faithfully mirroring web's `AgentMessage`:

1. **Group.** A pure reducer walks the packets and buckets them into **steps** by a grouping key
   `"{turn_index}-{tab_index}"` (from each packet's `placement`). A new `turn_index` closes out ("completes")
   every earlier step by **synthesizing a `section_end`** into it; the final `stop` packet closes whatever's left.
   This is exactly how web decides a step is done — the backend rarely sends `section_end` itself. Steps are then
   arranged into **turn groups** (steps that share a `turn_index` are "parallel"; single ones are "sequential").

2. **Pace.** A stateful hook reveals steps with a **200 ms stagger** (first step immediately, the rest one every
   200 ms; a `stop` flushes them all at once). It also **withholds the final answer** until the tool steps have
   finished animating in — so the answer never pops in before the timeline. A history-reloaded (already-complete)
   message **bypasses** pacing and shows everything instantly.

3. **Derive UI state.** A pure state machine turns "what's streaming / stopped / expanded" into one of **seven
   states** (EMPTY, DISPLAY_CONTENT_ONLY, STREAMING_SEQUENTIAL, STREAMING_PARALLEL, STOPPED, COMPLETED_COLLAPSED,
   COMPLETED_EXPANDED) plus a set of "show this / round that" booleans. Separate small hooks compute the **header
   text** (from the current step's first packet — "Thinking", "Searching the web", …), the **live elapsed timer**
   (1/sec, frozen once the backend reports a duration), the **step count**, and the **expand/collapse** state
   (default collapsed; **auto-collapses** when the answer begins, unless the user manually toggled it).

4. **Render.** The **timeline shell** draws the agent avatar in a 36 px rail, the header (a shimmering
   "Thinking…" while streaming, a "Thought for X · N steps" fold button when done), and — when expanded — the
   full step list. Each step is drawn by a **`StepContainer`** (icon rail + connector line + tinted surface +
   header + collapsible body). A **`TimelineRendererComponent`** owns each step's expanded/collapsed state and
   picks the renderer via **`findRenderer`** (web's priority-ordered dispatch, reasoning last). The renderer is a
   **render-prop component**: it computes a small `RendererResult` (`{icon, status, content, …}`) and hands it to
   the container, which owns the visual frame. For 9b the one wired renderer is **`ReasoningRenderer`**, which
   accumulates the streamed reasoning markdown, extracts a heading for the step title, enforces a 500 ms minimum
   "Thinking" display, and renders the body via mobile's `StreamingMarkdown`.

5. **Answer + sources.** Below the timeline, the **final answer** renders through the same renderer contract at
   `FULL` (mobile's existing `MessageTextRenderer`, migrated to the render-prop contract), and the 9a **Sources**
   bar renders below that — both unchanged in behavior.

## Component interaction

```
 assistant node.packets[]  (flat Packet[], grows each stream flush)
            │
            ▼
 ┌───────────────────────────────────────────────────────────────────────┐
 │ MessageRow.AssistantMessage   (mobile analog of web AgentMessage)       │
 │                                                                         │
 │   usePacketProcessor(packets, nodeId)                                   │
 │     └─ messageProcessor.processPackets  (PURE reducer: grouping +       │
 │        section_end injection + citations/docs + finalAnswerComing)      │
 │        → toolGroups, displayGroups, citations, stopPacketSeen, …        │
 │     └─ transformers.groupStepsByTurn → toolTurnGroups: TurnGroup[]      │
 │                                                                         │
 │   usePacedTurnGroups(toolTurnGroups, displayGroups, stop, node, final)  │
 │     └─ 200ms staggered reveal (timer)                                   │
 │        → pacedTurnGroups, pacedDisplayGroups, pacedFinalAnswerComing    │
 │                                                                         │
 │   ┌── <AgentTimeline turnGroups=pacedTurnGroups … />  ── (ABOVE) ──┐    │
 │   │     useTimelineUIState (7 states) · useTimelineExpansion       │    │
 │   │     useTimelineHeader · useStreamingDuration · useMetrics      │    │
 │   │     header switch → StreamingHeader / CompletedHeader / Stopped│    │
 │   │     ExpandedTimelineContent → per step:                        │    │
 │   │        TimelineStep → TimelineRendererComponent (owns expand)  │    │
 │   │          → findRenderer(step.packets) → ReasoningRenderer      │    │
 │   │             → children([RendererResult]) → StepContainer wraps │    │
 │   │        + Done / Stopped terminal step                          │    │
 │   └─────────────────────────────────────────────────────────────── ┘   │
 │                                                                         │
 │   pacedDisplayGroups → <RendererComponent renderType=FULL/> (BELOW)     │
 │      → findRenderer → MessageTextRenderer → StreamingMarkdown answer    │
 │                                                                         │
 │   <CitedSources/>  (9a, unchanged)                                      │
 └───────────────────────────────────────────────────────────────────────┘
```

## Key components

- **`messageProcessor` (grouping engine)** — extended from the 9a flat reducer into a faithful port of web's
  `packetProcessor`: turn/tab grouping, client-side `section_end` synthesis, tool/display categorization,
  `finalAnswerComing`, `stopPacketSeen`, image counters — plus the existing 9a citations/documents. (modified)
- **`transformers` / `packetUtils` / `packetHelpers` / `toolDisplay`** — pure helpers ported verbatim from web:
  step→turn grouping, packet categorizers, per-family predicates, tool name/completion/key parsing. (new)
- **`usePacketProcessor` / `usePacedTurnGroups`** — the two hooks that host the reducer + drive the 200 ms
  reveal. **These are the only two files that need a lint-forced restructure** (see decisions). (new)
- **`useTimelineUIState` / `useTimelineExpansion` / `useTimelineHeader` / `useStreamingDuration` /
  `useTimelineMetrics` / `useTimelineStepState`** — the pure state/derive hooks, ported 1:1. (new)
- **Renderer contract** — `RenderType`, `RendererResult`, `MessageRenderer<T,S>` render-prop type, `findRenderer`
  priority dispatch, `TimelineRendererComponent`, `RendererComponent` — ported exactly so future tool renderers
  are mechanical drop-ins. (new; `registry.ts` + `MessageTextRenderer` migrated to it) (modified)
- **Timeline UI** — `AgentTimeline` (rewritten from the stub), `StepContainer`, `TimelineRendererComponent`,
  `ExpandedTimelineContent`, `TimelineStep`, `CollapsedStreamingContent`, the rail/surface/content **primitives**,
  and the **headers** (Streaming/Completed/Stopped; Parallel stubbed). (new + `AgentTimeline` modified)
- **`ReasoningRenderer`** — the one wired renderer: reasoning-state accumulation + heading extraction + 500 ms
  min-thinking + `StreamingMarkdown` body. (new)
- **Packet contracts** — the full web `PacketType` enum + the reasoning/branching/tool-arg interfaces the engine
  and shell dereference. (modified `streamingModels.ts`)

## End-to-end scenario

User asks a reasoning model a question in an existing chat:

1. User sends. The stream begins; `AgentTimeline` shows the avatar + a shimmering **"Thinking…"** (state EMPTY).
2. `reasoning_start` then `reasoning_delta` packets arrive (turn 0). The grouping engine opens step `"0-0"`; the
   header switches to **STREAMING_SEQUENTIAL** and shimmers **"Thinking"**; the collapsed streaming preview shows
   the latest lines of the reasoning markdown scrolling in; the elapsed timer ticks **"3s… 4s…"**.
3. The model finishes thinking (`reasoning_done`, or a new turn / `message_start`). The reasoning step is marked
   **done** (synthesized `section_end`); a `message_start` sets `finalAnswerComing`; the timeline **auto-collapses**
   into **"Thought for 6s · 1 step"**.
4. `message_delta` packets stream the answer through `MessageTextRenderer` **below** the (now collapsed) timeline;
   the 9a **Sources** bar appears if the answer cited documents.
5. `stop` ends the run. Tapping the "Thought for 6s" pill **expands** the timeline, showing the full reasoning
   step (icon rail + "Thinking" header + reasoning markdown) and a terminal **"Done"** step.
6. Reopening the chat later hydrates the saved packets, **bypasses pacing**, and renders the collapsed timeline +
   answer instantly.

## Sequence of key operations

1. Stream flush appends packets to the assistant node → `usePacketProcessor` recomputes the grouped state.
2. Reducer groups by `"{turn}-{tab}"`, synthesizes `section_end` on turn-transition / `stop`, categorizes
   tool-vs-display groups, tracks `finalAnswerComing` / `stopPacketSeen` / citations / documents.
3. `groupStepsByTurn` → `TurnGroup[]`; `usePacedTurnGroups` reveals steps at 200 ms and gates the answer.
4. `AgentTimeline` derives the UI state, header text, elapsed time, expansion; renders header + (if expanded)
   `ExpandedTimelineContent`.
5. Each step → `TimelineRendererComponent` → `findRenderer` → `ReasoningRenderer` → `children([result])` →
   `StepContainer` frame. Terminal Done/Stopped step appended.
6. `pacedDisplayGroups` → final answer renderer at `FULL`; `CitedSources` below.

## Key decisions & why

- **Adopt web's render-prop `MessageRenderer<T,S>` contract exactly (not a simplified data object).** The owner
  will build the tool renderers immediately as follow-up PRs and wants **zero refactor** — porting each web
  renderer must be near-mechanical, which requires the identical `{packets, state, renderType, children(results)}`
  shape and the identical `RendererResult` fields. Mobile's existing simpler `{matches, Component}` registry
  (PR 3) is **migrated** to this contract now (including the final-answer `MessageTextRenderer`), because deferring
  the migration *is* the "refactor later" we're told to avoid.
- **Faithful `section_end` synthesis + `"{turn}-{tab}"` grouping.** A step is "complete" almost entirely via
  **client-synthesized** `section_end` (on a new `turn_index`, or on `stop`) — the backend seldom sends it. This
  is the load-bearing correctness rule; porting it verbatim is what keeps reasoning/tool steps closing correctly.
  (Codebase: `web/.../timeline/hooks/packetProcessor.ts`.)
- **The one accepted, platform-forced divergence: the two ref-during-render hooks are restructured.** Web's
  `usePacketProcessor` mutates a state ref **during render** and `usePacedTurnGroups` reads pacing refs during
  render — both **illegal** under mobile's `react-hooks/refs` lint. They're restructured to a `useMemo`
  full-recompute (grouping) + effect-driven state (pacing timer), which is **behavior-preserving** (same grouped
  output, same 200 ms cadence). This is an implementation necessity, **not** a look/structure drift — everything
  else ports 1:1. (Documented in `03`.)
- **Ship the full shell now; wire only reasoning.** Parallel-tab tabs (`ParallelTimelineTabs`) and nested/memory
  paths ship **dormant** (as in web) so parallelism, deep-research nesting, and multi-model become later **UI-only**
  follow-ups with no seam change — matching web's own "the shell already supports it" design and honoring the
  owner's "want everything, no refactor."
- **Progressive disclosure matches the industry default.** Collapse-by-default, a streaming "Thinking… (Ns)"
  summary, auto-collapse-on-answer, tap (never hover) to expand — the mainstream pattern, and exactly what web
  already does, so parity and best-practice coincide. (`digestibleux.com`, `hatchworks` agent-ux, W3C accordion.)

## What existing behavior changes

- **Assistant messages that involve thinking/tools now show a timeline above the answer** (today: only a static
  "Thinking…" shimmer with no steps). Plain, tool-free answers look the same (EMPTY → straight to answer).
- **The render path is restructured** to web's grouping/pacing/dispatch. The 9a **citations/Sources** behavior and
  the streamed markdown answer are **preserved** (the final answer is migrated to the same contract but renders
  identically). No backend, DB, or API change. No change to non-chat surfaces.
- **Two new small dependencies on timing state:** a per-message `streamingStartedAt` timestamp (for the live
  timer) is captured when a run starts; collapse/expand + a reasoning "muted markdown" variant are new UI.
