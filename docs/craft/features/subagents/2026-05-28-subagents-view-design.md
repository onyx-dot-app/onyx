# Subagents view — design

## Issues to Address

When the Onyx Craft agent dispatches a subagent via the `task` tool, the
transcript today renders a single collapsible card showing the prompt and
the subagent's final output (`web/src/app/craft/components/tool-cards/TaskBody.tsx`).
The subagent's intermediate activity — the tool calls it issues while
working — is invisible.

This is a problem for two reasons:

1. **Trust.** A subagent that runs for 30+ seconds shows no progress. The
   user has no way to know whether it's stuck, what it's doing, or how
   close to done it is. Long subagent runs feel like the app has frozen.
2. **Debuggability.** When a subagent returns a surprising or wrong
   answer, the user has no way to inspect why — they only see the parent's
   prompt and the final summary string. The intermediate steps would be
   the most useful evidence and are silently discarded.

The goal: give users a peripheral indicator of running subagents and a
fast way to open any subagent's live transcript for inspection, without
disrupting the main chat.

## Important Notes

- **This PR depends on the universal-panel refactor** that generalizes the
  side panel's transient-tab system so this PR can add a `kind: "subagent"`
  tab cleanly. Ship the refactor first.
- **Child tool calls already stream on the same SSE channel.** When the parent
  runs the `task` tool, the child session emits its own `message.updated`
  events to the same `/event` stream. Each child event's `state.metadata`
  contains `parentSessionId` and `sessionId` (child). Today the frontend
  strictly filters on parent session ID, dropping them. That filter is the
  load-bearing change.
- **The DB schema already supports nested tool calls — no migration
  needed.** Per `backend/onyx/db/models.py:2911-2970`, `tool_call` has a
  `parent_tool_call_id` self-reference (nullable) and `parent_chat_message_id`
  is nullable with an explicit comment for the nested case. Subagent
  type lives in `tool_call_arguments`; status is derivable from
  response-presence; step count is `count(*) WHERE parent_tool_call_id = X`.
- **Reference landscape.** Replit hides subagents; Lovable's subagents are
  read-only; Cursor uses a popover; Claude Code does a full chat swap.
  Onyx Craft's subagents are substantive, parallel-capable, and
  side-effectful, but the universal panel gives us a third option:
  subagent transcript lives in the side panel as a transient tab,
  keeping the main chat fully visible.

## Design

### Surface 1: agent strip

A small element rendered above `InputBar` in `ChatPanel.tsx`, in the slot
where `ConnectorBannersRow` used to live (the prep PR `craft-ui-cleanup`
already vacated that). **Not rendered when the session has zero
subagents.** When ≥1 subagent exists:

- A single horizontal row of compact pills, one per subagent
- Each pill shows: subagent-type badge (`explore`, `plan`, etc.), short
  name (from the parent's prompt summary), live status icon (pulsing
  dot for running, check for done, error for failed), and step count
- Running agents sort before completed; within each group, newest first
- The strip stays visible regardless of panel state — it's purely a
  status + launcher
- Wraps to two lines max; 5+ parallel subagents condense to a "+N"
  overflow pill that opens a popover list
- Each pill is a launcher: clicking opens (or focuses) a side-panel
  transient tab for that subagent

### Surface 2: subagent transcript as a panel tab

Clicking an agent pill creates or focuses a `kind: "subagent"`
transient tab in the side panel (introduced by the universal-panel
refactor). If the panel is closed, the click also opens it. The tab's
body renders the subagent's tool-call stream using the same
`CraftToolCard` primitives as the main transcript.

The tab label is `[badge] short-name` with a close × on hover.
Multiple subagents can be open as concurrent tabs.

The main chat stays fully visible while the panel is open — both
streams are simultaneously legible. No chat-swap. No back-arrow
banner. The agent strip pill highlights the active subagent tab; other
pills pulse on their own activity even when not the active tab, giving
peripheral awareness of all running subagents.

### State model

Extend `useBuildSessionStore.ts`:

- A `subagents` keyed map: `subagentSessionId → SubagentState`. Each
  state holds the subagent's tool-call list (`ToolCallState[]`),
  status, type, parent task-tool-call ID, step count, and timestamps.
- Extend the `PanelTab` discriminated union (introduced by the
  refactor) with `{ kind: "subagent", subagentId: string }`.
- A small `openSubagentInPanel(subagentId)` action that:
  upserts a `kind: "subagent"` entry into `panelTabs`,
  sets `activePanelTabId` to that subagent's ID,
  ensures `outputPanelOpen = true`.

### Data flow

The change pivots on how SSE events are routed in
`useBuildStreaming.ts`:

1. Stop strictly filtering events to the parent session ID. Inspect
   `state.metadata.parentSessionId` and `state.metadata.sessionId` on
   each event.
2. When the parent emits a `task` tool-call-start, create a
   `SubagentState` entry keyed by the child session ID (from the task
   tool's metadata once available; buffer events for up to ~2s if a
   child event arrives first).
3. Subsequent events with a `parentSessionId` matching the active
   Craft session route to the appropriate `SubagentState`, not the
   parent transcript.
4. The parent's `task` tool card subscribes to its child's
   `SubagentState` to render the brief live-status line on the card.

### Persistence

Subagent inner tool calls persist as `tool_call` rows with
`parent_tool_call_id` set to the parent task call's ID and
`parent_chat_message_id = NULL` (per the schema's existing convention
for nested calls). No schema changes.

Derivable from existing columns:
- **Subagent type** — `tool_call_arguments.subagent_type` on parent.
- **Status** — same response-presence heuristic the existing renderer
  uses.
- **Step count** — `count(*) WHERE parent_tool_call_id = X`, or from
  the loaded list in memory.

Writer path: child SSE events persist as `tool_call` rows via the
existing tool-call persistence path, with `parent_tool_call_id` set.

Reader path: on session load, the existing `tool_call` query returns
nested rows. Group by `parent_tool_call_id` to rebuild the in-memory
`subagents` map.

### Components

New / changed:

- **`AgentStrip.tsx`** (new) — conditional element above `InputBar`.
  Returns `null` if no subagents in session.
- **`AgentPill.tsx`** (new) — one pill; click calls
  `openSubagentInPanel`.
- **`SubagentTab.tsx`** (new) — body component for `kind: "subagent"`
  tabs. Renders the subagent's tool-call list using `CraftToolCard`.
- **`ChatPanel.tsx`** (changed) — mount `AgentStrip` above
  `InputBar` (the `ConnectorBannersRow` slot, already cleared by
  the prep PR).
- **`TaskBody.tsx`** (changed) — slimmed: badge + prompt summary +
  live step count + final result. Clicking anywhere on the card
  triggers `openSubagentInPanel` for the same destination.
- **`useBuildSessionStore.ts`** (changed) — add `subagents` map,
  extend `PanelTab` union with `kind: "subagent"`, add
  `openSubagentInPanel` action.
- **`useBuildStreaming.ts`** (changed) — route events by session ID
  metadata; stop dropping non-parent events; create / update
  `SubagentState` entries.
- **`parsePacket.ts`** (changed) — surface `parentSessionId` and
  `sessionId` from `state.metadata`.
- **`OutputPanel.tsx`** (changed, lightly) — extend the tab-row
  rendering and body switch to handle `kind: "subagent"`. Tab chrome
  shows the subagent type badge instead of a file icon.
- **`backend/onyx/chat/...`** (changed) — wherever tool calls are
  persisted during streaming, persist subagent children as
  `tool_call` rows with `parent_tool_call_id` set. Exact file
  depends on the existing persistence path; nested writes should
  already be supported per the schema's prior design.

### Edge cases

- **Subagent that produces zero tool calls.** Subagent tab shows only
  the final result, no step list. Pill shows step count = 0.
- **Subagent that fails or times out.** Pill shows error indicator;
  tab body renders an error surface above whatever children executed.
- **Subagent whose session ID isn't known yet.** First child event
  tells us; buffer events for up to ~2s if a child event arrives
  before the parent's task-start metadata is populated.
- **Session restore (page reload mid-run).** `subagents` map
  restores from the `tool_call` table on session load. Live updates
  resume from the SSE stream. Panel tab state persists per the
  refactor's existing behavior.
- **Click a pill whose subagent is no longer running.** Opens the
  tab normally; transcript fully populated; step count final.
- **Many parallel subagents (4+).** Strip wraps to two lines max;
  further agents condense into a "+N" overflow pill that opens a
  popover list.
- **No subagents in session.** Strip not rendered; chat layout
  unchanged.
- **A different subagent updates while one is the active tab.**
  The other subagent's pill pulses in the strip; its panel tab (if
  open) pulses too. No automatic switch; user clicks to switch.

## Tests

Single layer: **Playwright E2E**. The behavior under test spans backend
streaming, store routing, persistence, and UI rendering across two
surfaces (strip + panel) — anything below E2E mocks the most
interesting part of the system.

`web/tests/e2e/craft-subagents-view.spec.ts` — drive a Craft
conversation that dispatches a subagent (the
`test_subagent_task_tool.py` integration prompt is a good source).
Assert:

1. A `task` card appears in the main transcript with a live status
   line.
2. The `AgentStrip` appears above the input bar with a pill for the
   subagent.
3. Clicking the pill opens the side panel (if closed) and adds a
   transient `kind: "subagent"` tab; tab activates; subagent
   transcript renders.
4. The main chat stays visible and continues to scroll normally.
5. The subagent's tool calls populate the panel tab as they stream.
6. Closing the tab (× on hover) removes the tab but keeps the
   subagent in the strip (so the user can reopen).
7. Reloading the page mid-conversation restores the strip and lets
   the user reopen the subagent's transcript from the DB.
8. On the subagent's completion, the pill shows a checkmark and the
   final step count.

No unit tests proposed: the SSE routing change is too thin to be
worth a unit harness. No external-dependency unit tests proposed:
the persistence path is straightforward DB writes the E2E exercises
end-to-end.
