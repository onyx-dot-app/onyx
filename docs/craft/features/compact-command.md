# `/compact` command

A user-facing slash command in the Craft composer that compacts the current
session's context on demand — it calls opencode's `summarize` endpoint and
surfaces the result as the existing compaction marker in the transcript.

Builds on the context-window-compaction feature (the input-bar ring +
`CompactionPacket` → `CompactionMarker`). That feature surfaces opencode's
*automatic* compaction; this adds a *manual* trigger. The rendering path is
already built and unchanged — this work is about triggering compaction on
demand and surfacing it as a first-class picker command.

## Issues to Address

opencode auto-compacts near the context limit (1M for Opus 4.8 here), so a user
who wants to reclaim context *now* — before a big task, or when the ring is
amber — has no way to do it. opencode exposes `POST /session/{id}/summarize`
(`{providerID, modelID, auto?}`), which generates a summary and emits
`session.compacted`. We want to surface that as a `/compact` command in the
composer's slash picker, styled like a skill but behaving as an action.

Key subtlety: **calling `summarize` alone would not show anything.** The
compaction marker only renders when the resulting `session.compacted` /
`summary:true` events flow through `translate_opencode_event` →
`CompactionPacket` → persist/stream. So `/compact` must run as a real streaming
turn, not a fire-and-forget POST.

## Important Notes

**Decisions locked with the user:**
- Command name is `/compact` (no leading dot).
- Backend runs it as a **full interactive turn** (`kind="compact"`), reusing the
  cache-turn + background-runner + attach/resume machinery — same reliability as
  send-message, so the marker streams live *and* persists on reload.
- The picker shows a dedicated **"Commands"** group (above Skills/Apps).
- This is a real user-facing command, not just a test hook (though it also
  serves as the on-demand way to exercise compaction end-to-end).

**opencode contract (v1.15.7, verified):** `POST /session/{sessionID}/summarize`
with body `{providerID, modelID, auto: false}`. It generates an assistant
message with `info.summary === true` and publishes `session.compacted
{sessionID}`, then goes idle. Our translator already: (a) emits `CompactionPacket`
on `session.compacted`, (b) suppresses the `summary:true` message's visible text,
(c) attaches the summary text to the packet via REST. `session.idle` terminates
the stream via `_emit_terminator` exactly like a normal turn. So the entire
consume/translate/persist path is reused unchanged.

**Turn shape:** a compact turn has **no user prompt** and creates **no user
message row** — it produces only the compaction marker (and, incidentally, an
updated `ContextUsagePacket` from the summary message's token counts, which
refreshes the ring to the post-compaction value).

**Model resolution:** `summarize` requires `providerID`/`modelID`. Use the
session's stored `agent_provider` / `agent_model` (already threaded into
`_streaming.yield_sandbox_events`). If both are null (legacy rows), the command
is unavailable rather than guessing.

**Relevant existing seams:**
- Picker model + matching: `web/src/lib/skills/picker.ts` (`PickerEntry` union,
  `toPickerSections`, `filterPickerSections`, `flattenSections`,
  `detectSlashTrigger`).
- Picker render: `EntryPickerPopover`; wiring + selection in
  `CraftInputBar.tsx` (`useSlashPicker({ onSelect: addEntry })`, `activeEntries`
  chips, `handleSubmit` prefix logic, `buildEntryMenuItems` for the `+` menu).
- Turn create: `POST /build/sessions/{id}/messages` in `session/messages.py`
  → `create_interactive_turn` (`interactive_turns/state.py`) →
  `start_interactive_turn_runner` (`interactive_turns/executor.py`). FE attaches
  via `GET .../turns/{turn_id}/events` (`interactive_turns/api.py`).
- Turn drive: `executor._drive_interactive_turn` →
  `SessionManager.yield_sandbox_events` → `_streaming.yield_sandbox_events`
  (has `opencode_session_id`, `agent_provider`, `agent_model`) →
  `serve_client.send_message` / `_post_prompt_async`.
- FE turn attach/stream: `useBuildStreaming` + `useBuildSessionStore`
  (active-turn registration, `appendStreamItem`, `CompactionMarker` render).

## Implementation Strategy

### Frontend — picker command

1. **New entry variant** in `picker.ts`: `PickerCommand { kind: "command"; slug;
   name; description }`. Extend the `PickerEntry` union, add a `commands` array
   to `PickerSections`, include it in `filterPickerSections` (reuse
   `matchesQuery`) and at the front of `flattenSections` (so keyboard-nav indices
   match render order). Seed a single static `compact` command (no server fetch).
2. **Render the "Commands" group** in `EntryPickerPopover` above Skills/Apps,
   with the `SvgFold` icon (shared with the marker) to read as an action.
3. **Selection = action, not chip.** In `CraftInputBar`, branch the picker's
   `onSelect`: if `entry.kind === "command" && entry.slug === "compact"`, invoke
   a new `onCompact` prop (from `ChatPanel`) instead of `addEntry`. Do the same
   in the paste path and (optionally) the `+` menu via `buildEntryMenuItems`.
4. **Availability:** gate the command out (or disabled with a tooltip) when
   there's no `opencode_session_id` yet (before the first turn), when a turn is
   running (`isRunning`), or when the model is unknown.

### Frontend — trigger + attach

5. `ChatPanel.onCompact` → `POST /build/sessions/{id}/compact`, which returns the
   same turn shape as send-message; then register the active turn and attach to
   `turns/{turn_id}/events` through the **existing** `useBuildStreaming` path so
   the marker streams in and persists — no new streaming code on the FE.
6. Show a transient "Compacting context…" affordance while the turn runs (reuse
   the running/interrupt affordance), clearing on the terminator.

### Backend — compact turn (`kind="compact"`)

7. **Turn model:** add `kind: Literal["prompt", "compact"] = "prompt"` to
   `InteractiveTurn` (`state.py`) + `create_interactive_turn`, and to
   `_save_turn`/`_load_turn` serialization.
8. **Route:** `POST /build/sessions/{id}/compact` in `session/messages.py`,
   mirroring the send-message create path but with `kind="compact"`, empty
   prompt, next `turn_index`, and returning the same response shape. Reuse the
   active-turn lock + runner start. Reject when `opencode_session_id` or the
   model is missing.
9. **Drive:** thread `kind` from `executor._drive_interactive_turn` into
   `SessionManager.yield_sandbox_events` → `_streaming.yield_sandbox_events`.
   When `kind == "compact"`, call a new `serve_client.compact()` instead of
   `send_message`, and **skip user-message persistence**.
10. **`serve_client.compact()`:** a generator mirroring `send_message` —
    subscribe to the pod event bus, wait for `/event` readiness, then
    `POST /session/{id}/summarize {providerID, modelID, auto: false}` (new
    `_post_summarize`, sibling to `_post_prompt_async`), then
    `_consume_from_bus` through `translate_opencode_event` until the terminator.
    No translator changes: `session.compacted` → `CompactionPacket`, summary
    suppression, and `session.idle` termination already work.

### No changes needed
- `translate_opencode_event`, `CompactionPacket`, `CompactionMarker`,
  persistence, and reload (`convertMessagesToStreamItems`) are already built and
  handle the compaction events identically whether compaction was auto or manual.

## UX

- `/compact` appears in a dedicated **Commands** group at the top of the slash
  popover, `SvgFold` icon, label "Compact context", description "Summarize
  earlier context to free up space". Matches on `/comp…`.
- Selecting it fires immediately (no chip, no inserted text), shows a brief
  "Compacting context…" state, then the understated compaction divider appears
  in the transcript (with the "View summary" disclosure) and the ring drops to
  its post-compaction value.
- Unavailable before the first turn, while a turn runs, or when the model is
  unknown — so it never produces a confusing no-op.

## Tests

- **External Dependency Unit / unit (backend):** `serve_client.compact()` posts
  to `/session/{id}/summarize` with the right `{providerID, modelID, auto}` and
  yields the translated `CompactionPacket` on a canned `session.compacted`
  (extends the existing `test_translate_opencode_event` fixtures; the
  compaction/suppression translation is already covered). A routing test that
  `kind="compact"` drives `compact()` not `send_message` in
  `_streaming.yield_sandbox_events`.
- **Frontend unit:** `picker.ts` — the command appears in sections, filters on
  `/comp`, and orders first in `flattenSections`; `CraftInputBar` routes a
  `command` selection to `onCompact` (not `addEntry`); availability gating.
- **Playwright (one flow):** open `/` → Commands group shows Compact → select →
  assert a compact turn starts and the compaction marker renders. Only add if
  the FE↔backend attach needs end-to-end coverage; otherwise the above suffice.
