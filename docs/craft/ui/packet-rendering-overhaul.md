# Craft Packet Rendering Overhaul

Plan for redesigning how the Craft transcript renders agent activity — text,
thinking, tool calls, todos, subagents, and skills. The current rendering is
generic across tools, ships two parallel "tool pill" implementations, and
violates the design system in a few high-visibility places. This doc captures
what we're changing, why, and how — borrowing inspiration from Claude Code,
Codex, and the opencode TUI.

## Issues to Address

1. **Two parallel tool-rendering implementations.** `ToolCallPill` (used for
   `task` and other non-working tools) and `WorkingLine` (rows inside the
   `WorkingPill` group) are 80% the same code with diverging padding, status
   styling, and expand behavior. Touching one rarely updates the other.

2. **Every tool renders the same way.** `bash`, `read`, `edit`, `glob`/`grep`,
   `webfetch`, `websearch` all collapse into the same generic header + raw
   output blob. Bash output isn't terminal-styled, search results aren't a
   clickable list, web results don't show titles/URLs, fetches don't show
   status codes.

3. **`ThinkingCard` defaults to open** (`ThinkingCard.tsx:26`). The thinking
   block is the loudest, least-scannable item in the transcript and yet it
   starts expanded.

4. **Design-system violations in tool surfaces.** `DiffView` uses hardcoded
   `#fafafa` / `#151617` / `green-100` / `red-100` and raw `dark:` modifiers
   (`DiffView.tsx:172-263`). `RawOutputBlock` does the same. Both break the
   color-token rules in `web/CLAUDE.md`. The diff also forces a unified view —
   side-by-side is missing for hunks where it would read much better.

5. **Subagents (`task` tool) are awkward.** Today the parent's `ToolCallPill`
   shows the subagent's prompt, and the subagent's text gets emitted as a
   stray `StreamItem` into the parent transcript
   (`useBuildStreaming.ts:287-296`). There's no way to view the subagent's
   own activity — its tool calls, thinking, and message stream are
   invisible. A subagent event-stream endpoint would let us render this
   as a panel; that endpoint is not yet built.

6. **Skills are not first-class.** Skill invocations currently look like any
   other tool call. There's no badge, no namespace hint, no visual cue that
   "this came from a skill."

7. **Raw output silently truncates.** `RawOutputBlock` caps at `maxHeight` and
   becomes a scroll container with no indication that there's more, no
   click-to-expand affordance, and no copy button.

8. **Past Working groups auto-collapse, but the latest stays expanded.** This
   is fine while one tool is running but feels noisy once a turn has 5+
   completed tools — you have to manually scan and collapse.

## Important Notes

### Existing code surface

- `web/src/app/craft/components/` is where all transcript-side components
  live. Current files relevant to this overhaul:
  - `BuildMessageList.tsx` — switch-statement renderer for `StreamItem`s.
    Routes `working_group` → `WorkingPill`, non-working `tool_call` →
    `ToolCallPill`, `text` → `TextChunk`, etc.
  - `ToolCallPill.tsx`, `WorkingLine.tsx`, `WorkingPill.tsx` — current tool
    rendering.
  - `ThinkingCard.tsx` — thinking block, defaults open.
  - `DiffView.tsx`, `RawOutputBlock.tsx` — shared body renderers.
  - `TodoListCard.tsx` — todo rendering (leave largely alone; already its
    own specialized renderer).
- `web/src/app/craft/types/displayTypes.ts` defines `ToolCallState`. It
  already carries `kind`, `title`, `description`, `command`, `rawOutput`,
  `subagentType`, `isNewFile`, `oldContent`, `newContent`. We do not need
  to broaden this shape much — most per-tool data is already present.
- `web/src/app/craft/utils/parsePacket.ts` is the single funnel that turns
  ACP packets into `ToolCallState`s. Any new fields (skill name, exit code,
  bytes fetched, etc.) get extracted here.

### Design-system rules to follow

`web/CLAUDE.md` is binding. Highlights relevant to this PR series:

- **Opal first**, refresh-components as fallback. Existing craft code is
  already on `@opal/utils` / `@opal/icons`. Where new components want
  buttons or text or layouts, prefer Opal: `Button` from
  `@opal/components/buttons/button/components`, `Text` from `@opal/components`,
  `Content` / `ContentAction` from `@opal/layouts`.
- **No raw `dark:` modifiers.** The color system handles dark mode via CSS
  vars — using `dark:bg-...` directly breaks it. `DiffView` and
  `RawOutputBlock` currently violate this; fixing is part of the overhaul.
- **No raw Tailwind colors.** Use tokens (`background-neutral-01`,
  `status-success-05`, `text-03`, etc.).
- **Icons only from `@opal/icons` or `web/src/icons/`.** No `lucide-react`
  or `react-icons`.
- **No raw `<button>` / `<input>` / `<textarea>`.** Use Opal `Button`.
  The existing craft code uses raw `<button>` via Radix `Collapsible`'s
  `asChild` pattern, which is fine since the button comes from Radix —
  keep that pattern but the surrounding chrome should use Opal where it
  fits.

### Backend hooks we'll lean on

- A subagent event-stream endpoint (e.g.
  `GET /sessions/{id}/subagents/{child_opencode_id}/events`) is **not
  yet built** — it's a prerequisite for the SubagentPanel work and is
  flagged in the Deferred section below. The current `TaskBody` renders
  the subagent prompt + final output inline without the live stream.
- Skill invocations come through the same `tool_call_start` /
  `tool_call_progress` packets but with a `skills.<name>` tool name (or a
  similar namespacing convention — to confirm during Phase 1 by spot-
  checking what comes through `parsePacket.ts`).

## Implementation Strategy

### A. The `CraftToolCard` foundation

Replace `ToolCallPill` + `WorkingLine` with a single entry point that
composes the main-chat timeline primitives:

- `CraftToolCard` — composes `TimelineRow` + `TimelineSurface` from
  `web/src/app/app/message/messageComponents/timeline/primitives/`,
  renders a status-aware rail icon, an inline header (title +
  description + optional `SkillBadge` + chevron), and a per-tool body
  via a collapsible content slot. `railVariant` chooses between
  `"rail"` (top-level, default), `"spacer"` (nested under a parent
  rail), and `"none"` (no left column — used inside `WorkingPill`).
- `SkillBadge` — small chip rendered in the header when `toolCall`
  originated from a skill namespace.

Callers (`BuildMessageList`, `WorkingPill`) wrap their card lists in
`TimelineRoot` so the shared timeline CSS variables resolve. The body
of the card is a slot; per-tool body components render into it.

### B. Per-tool body components

Lives under `web/src/app/craft/components/tool-cards/`:

| Tool kind            | Body component   | Inspiration & behavior                                                                                                                                    |
| -------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bash` (`execute`)   | `BashBody`       | Terminal-styled output block (dark, monospace, ANSI-aware later). Header pins the command even when collapsed. Footer shows exit code badge + duration.   |
| `read`               | `ReadBody`       | File-card preview: file icon + path + first ~10 lines with line numbers. "Open full file" expands to a side preview (or full scrollable block).           |
| `edit` / `write`     | `DiffBody`       | Rebuilt diff using design tokens (replaces `DiffView`). Unified by default. Toggle to side-by-side for hunks >20 lines or via user pref. Stats in footer. |
| `glob` / `grep`      | `SearchBody`     | Result list as clickable `file:line` rows with snippet preview. Result count badge. No syntax highlighting on the list itself.                            |
| `websearch`          | `WebSearchBody`  | Result cards: title (link) + domain + URL + 2-line snippet. Cribbed from Perplexity / Claude Code's search rendering.                                     |
| `webfetch`           | `WebFetchBody`   | URL header + status code + content-type. Body collapsed by default behind "Show response."                                                                |
| `task` (subagent)    | `TaskBody`       | Subagent label + "View transcript →" that opens `SubagentPanel`. Drops the current behavior of dumping subagent text into the parent transcript.          |
| `todowrite`          | (use existing `TodoListCard`, light polish) | Already specialized. Leave alone except for visual-token cleanup.                                                              |
| `other` / `unknown`  | `GenericBody`    | Falls back to today's behavior (raw output block, no specialization). Safety net so we never render nothing.                                              |

`SubagentPanel` (in `tool-cards/subagent/`) would host its own
`BuildMessageList` — recursive, since a subagent can itself spawn
subagents. It would subscribe to a subagent event-stream endpoint
via a new hook (e.g. `useSubagentStream`). `SubagentFooter` would
give prev/next navigation across sibling subagents within the same
parent turn, mirroring the opencode TUI. This is **deferred** until
the backend endpoint exists.

### C. Cross-cutting polish

1. **Default-collapse completed tool cards.** Header alone gives enough
   information for the common case. `WorkingPill` itself can stay open
   while in progress, then collapse on completion.
2. **Thinking starts collapsed.** Flip the default in `ThinkingCard.tsx`.
   Add a one-line summary like "Thinking · 312 tokens" so users can see
   the size without expanding.
3. **`DiffView` / `RawOutputBlock` rewrite.** Both move into
   `tool-cards/` and use Opal tokens. `RawOutputBlock` gains a
   "truncated · expand" affordance and a copy button.
4. **Text coalescing across tools.** When the agent emits text → tool →
   text inside the same assistant turn, collapse those into one text
   bubble in `BuildMessageList.tsx` so the prose reads as one
   continuous voice.
5. **Turn-grouping visual rail.** Optional Phase 4 — wrap each agent
   turn in a card with a subtle left-rail so users can scan turn
   boundaries.

### D. Migration plan (single branch, split into stacked PRs later)

This branch (`craft-ui-overhaul`) gets all four phases. After it's
working end-to-end we use `ez` to split into a stack:

- **Phase 1** — `ToolCard` foundation, `BashBody`, `DiffBody`,
  retire `WorkingLine`, keep `ToolCallPill` as fallback for any tool
  kind that doesn't have a body yet.
- **Phase 2** — `ReadBody`, `SearchBody`.
- **Phase 3** — `WebSearchBody`, `WebFetchBody`, `TaskBody`.
- **Phase 4** — Cross-cutting polish: thinking default flip,
  default-collapse completed Working pills, retire `ToolCallPill`,
  `WorkingLine`, old `DiffView`.

Phase boundaries are clean: each phase compiles and ships independently
because unimplemented tools always fall back to `GenericBody`.

### E. What landed and what's deferred

**Landed in this branch:**

- `web/src/app/craft/components/tool-cards/` — `SkillBadge` plus body
  components: `BashBody`, `DiffBody`, `ReadBody`, `SearchBody`,
  `WebSearchBody`, `WebFetchBody`, `TaskBody`, `GenericBody`.
- `CraftToolCard.tsx` as the single entry point. Routes on
  `toolName` first (to distinguish `websearch` / `webfetch` inside
  the broader `search` / `other` kinds), then on `kind`.
- Tool-card chrome now composes the main-chat timeline primitives
  (`TimelineRow` + `TimelineSurface` from
  `web/src/app/app/message/messageComponents/timeline/primitives/`)
  so Craft and `/app` share rail / connector visual identity.
  `BuildMessageList` and `WorkingPill` wrap their children in
  `TimelineRoot` so the timeline CSS variables resolve; top-level
  cards default to `railVariant="rail"`, while children nested
  inside the `WorkingPill` use `railVariant="none"` because the
  pill provides its own visual container. The legacy
  `ToolCard.tsx` and `ToolCardHeader.tsx` were retired in this
  migration.
- `parsePacket.ts` skill detection (`detectSkillName`) — matches
  `skills.X`, `skills:X`, `superpowers.X`, `superpowers:X`.
- `ToolCallState` gained `toolName`, `taskOutput`, and `skillName`.
- `useBuildStreaming.ts` no longer emits a stray text `StreamItem`
  for task output — it's stored on the tool call and rendered by
  `TaskBody`.
- `ThinkingCard` defaults to collapsed with a token-count summary,
  auto-opens during streaming.
- `WorkingPill` auto-collapses once all contained tools terminate.
- Retired files: `ToolCallPill.tsx`, `WorkingLine.tsx`, `DiffView.tsx`,
  `tool-cards/ToolCard.tsx`, `tool-cards/ToolCardHeader.tsx`.

**Deferred:**

- **SubagentPanel + SubagentFooter**: requires an SSE endpoint at
  `GET /sessions/{id}/subagents/{cid}/events` that does not yet
  exist. The current `TaskBody` renders the subagent's prompt and
  final output as a clean inline card — enough to remove the stray
  parent-transcript text dumps — but does not yet expose the
  subagent's own tool calls / thinking stream. Add the SSE endpoint
  on the backend, then build the panel in a follow-up.
- **Text coalescing across tools**: collapsing consecutive text
  bubbles within a single assistant turn requires a refactor of
  `useBuildStreaming.ts` text accumulation. Not blocking the rest
  of the overhaul; revisit if the visual rhythm still feels choppy
  in real use.
- **`RawOutputBlock` truncation affordance + copy button**:
  `RawOutputBlock` is still in place under `GenericBody`; the
  "expand to full" affordance and copy button are nice-to-haves
  rather than load-bearing for the overhaul.
- **Turn-grouping visual rail**: optional polish from the original
  plan, left for a future iteration.
- **`WorkingPill` as a `StepContainer`**: the pill itself could be
  modeled as a parent rail row with nested children at
  `railVariant="spacer"`. Today the pill stays a bordered container
  and its children render with `railVariant="none"`. Worth doing
  if/when we unify the working-pill chrome with the rest of the
  timeline.

### Rationale: bypassing `TimelineStepContent`

`CraftToolCard` composes `TimelineRow` + `TimelineSurface` directly
rather than going through `StepContainer` / `TimelineStepContent`.
The primitive's header layout exposes collapse as a dedicated
`Button onClick={onToggle}` chevron on the right, with only the
button itself as the click target. Craft's interaction model is
whole-row-click via Radix `Collapsible asChild` — wrapping the
entire header in a `CollapsibleTrigger`'d `<button>`. Threading
that through `TimelineStepContent` would require either changing
the primitive's API or fighting against it; composing one level
deeper keeps both interaction models intact without churn in
shared code.

## Tests

This is a frontend rendering overhaul, so the cheapest high-value
coverage is Playwright e2e — they exercise the real packet stream end
to end.

- **Playwright (primary).** One e2e test that drives a chat session
  through each tool kind and asserts the new body component renders.
  Lives at `web/tests/e2e/craft/tool-cards.spec.ts`. Covers: bash
  (exit code badge), edit (diff stats), read (file preview), grep
  (clickable rows), websearch (result cards), webfetch (status code),
  task (panel opens and shows subagent's own tool calls). Skill badge
  asserted on at least one skill-namespaced invocation.
- **Unit tests for `parsePacket.ts` additions only.** If we add new
  field extraction (skill name, exit code, bytes fetched), cover those
  in `web/src/app/craft/utils/__tests__/parsePacket.test.ts`. Don't
  unit-test the React components — they're shallow enough that
  Playwright is the right tool.

No backend tests required. No integration tests required.
