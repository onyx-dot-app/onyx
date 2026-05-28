# Opencode Serve — Empirical Test Report

Companion to [`opencode-serve-migration.md`](./opencode-serve-migration.md) and [`features/opencode-serve-client.md`](./features/opencode-serve-client.md). Records every test scenario exercised against a live `opencode serve` 1.15.7 instance in the kind cluster (pod `onyx-sandboxes/opencode-probe`) on 2026-05-22. Reproduction scripts referenced live in `/tmp/` and are inlined here where short enough to grep.

This doc is the *source of truth* for the wire grammar the migration depends on. Where it disagrees with the plan, the plan is wrong — update the plan.

## Setup

- Pod: `onyx-sandboxes/opencode-probe`, image `onyxdotapp/sandbox:dev`
- opencode version: `1.15.7` (per `/doc`)
- Listener: `opencode serve --hostname 0.0.0.0 --port 4096 --log-level INFO --print-logs`
- Started via `setsid sh -c "... nohup opencode serve ... </dev/null" &` from inside the pod, because plain `&` from `kubectl exec` dies when exec returns. Documented here so the future supervisor wrapper in the migration plan accounts for it.
- Port-forwarded: `kubectl -n onyx-sandboxes port-forward pod/opencode-probe 14096:4096`
- All probe scripts hit `http://127.0.0.1:14096`.
- `opencode.json` in `/workspace/sessions/test/` configures `openai/gpt-4o-mini` with API key, wide-open permissions for most tests, narrower permissions for the permission-flow test.

## Result summary

| Scenario | Result | Terminator path observed | Files |
|---|---|---|---|
| Multi-turn (3 prompts on one session) | ✅ all turns terminated | 2× `message.updated`, 1× `session.idle` | `/tmp/dump_multiturn.json` |
| Tool calls (bash + file ops) | ✅ | `message.updated` | `/tmp/dump_tool_calls.json` |
| Subagent / Task tool | ✅ child + parent both terminated | `message.updated` | `/tmp/dump_subagent.json` |
| Permission flow | ✅ full ask → reply → resume cycle | `message.updated` | `/tmp/test_permission2.py` |
| Abort mid-turn | ✅ aborted cleanly, session reusable | `session.error` then `session.idle` for next turn | `/tmp/dump_abort.json` |
| `/event` reconnect + gap-fill | ⚠️ **gap-fill design needs revision** — see §Gap-fill below | n/a | `/tmp/test_reconnect.py`, `/tmp/test_reconnect2.py` |
| Errors (bad model) | ✅ surfaces as `session.error` | `session.idle` | `/tmp/dump_errors.json` |
| Edit-tool field shape | ✅ field names locked | n/a | `/tmp/probe_edit_v3.py`, `/tmp/dump_edit_v2.json` |

No regressions vs. the migration plan. One material correction (gap-fill) and several smaller clarifications, captured below. The clarifications have all been folded into the design doc; the migration plan tweaks are listed in §"Plan updates needed".

## Wire grammar — locked

### Per-turn event stream (happy path)

For a simple prompt with no tool calls and no permissions, the events in order:

1. `session.created` — when the session is first created (one-time per session, not per turn)
2. `session.next.agent.switched` — informational
3. `session.next.model.switched` — informational
4. `message.updated` (role=user, `time.completed=null`) — user message recorded
5. `message.part.updated` (type=text, role=user, text=full user message) — user message part
6. `session.status` — status change
7. `message.updated` (role=assistant, `time.completed=null`) — assistant message created, empty
8. `session.diff` — workspace diff (often empty unless tools modified files)
9. `message.part.updated` (type=text, role=assistant, text="") — empty text part created
10. **`message.part.delta` × N** — per-token streamed text deltas. **This is the primary streaming source.**
11. `message.part.updated` (type=text, role=assistant, text=`<full accumulated text>`) — fires once at end of text streaming with the complete text
12. **`message.updated` (role=assistant, `time.completed=<unix-ms>`) — primary terminator**
13. `session.status` — status to idle
14. `session.idle` — backstop terminator
15. `session.updated` — informational
16. `session.diff` — informational
17. `message.updated` — informational (one more)

### Streaming text — `message.part.delta` vs. `message.part.updated`

| Source | When | Cumulative or delta? | Usable for? |
|---|---|---|---|
| `message.part.delta` (`field=text`) | Every token | Delta | Real-time UX |
| `message.part.updated` (`type=text`, intermediate) | Part creation only | Empty | Discovering new part IDs |
| `message.part.updated` (`type=text`, final) | After last delta | Cumulative full text | Verification / gap-fill |

The frontend `parsePacket.ts` expects per-chunk `agent_message_chunk` events. The K8s `OpencodeServeClient` should yield one `AgentMessageChunk` per `message.part.delta` event with `field=text`.

The final `message.part.updated` for the same part is a useful state reconciliation point — if a sequence of deltas was missed, the cumulative `part.text` in this event lets us recover.

### Tool calls — `message.part.updated` only (no deltas)

Tools produce a chain of `message.part.updated` events for `type=tool` parts. There are no `tool.delta` events.

Observed lifecycle for one bash call (`/tmp/dump_tool_calls.json`):

```
status=pending     input={}                                                              output=None
status=running     input={command, timeout, workdir, description}                        output=None
status=running     input=<same>                                                          output=None
status=running     input=<same>                                                          output=None
status=completed   input=<same>                                                          output='SENTINEL\n'
```

So:
- `state.status=pending` — first sighting; `state.input` is empty.
- `state.status=running` — fires multiple times during execution; `state.input` is populated.
- `state.status=completed` — final; `state.output` contains the result (string or object depending on tool).

The translator emits:
- `ToolCallStart` on first sighting of a `callID` (i.e., on the `pending` event).
- `ToolCallProgress` on every subsequent update for the same `callID`, with `status` propagated through.

### Per-tool input/output schemas (locked)

Field names confirmed empirically. Frontend reads from `rawInput`/`rawOutput`/`content` and accepts both snake_case and camelCase variants — opencode emits camelCase for the per-tool fields.

| Tool | `state.input` fields | `state.output` shape | `state.metadata` notable fields |
|---|---|---|---|
| `bash` | `command`, `timeout`, `workdir`, `description` | string (raw stdout/stderr concat) | — |
| `read` | `filePath`, `offset`, `limit` | string with XML-like wrapping: `<path>…</path><type>file</type><content>1: …\n2: …</content>` | `preview` (line-number-stripped text), `truncated`, `loaded` |
| `edit` | `filePath`, `oldString`, `newString`, `replaceAll` | `"Edit applied successfully."` | `diagnostics`, `diff` (unified-diff string), `filediff.{file, patch, additions, deletions}`, `truncated` |
| `task` | `description`, `prompt`, `subagent_type`, `task_id`, `command` | string containing `task_id: …\n\n<task_result>…</task_result>` | `parentSessionId`, `sessionId`, `model`, `truncated` |

Notes:
- All input field names are **camelCase** (`filePath`, `oldString`, `replaceAll`) — the frontend's `parsePacket.ts` already accepts these via its `file_path ?? filePath ?? path` fallback chain.
- `read.output` is a single string wrapped in XML-ish tags, with **line-numbered content**. The frontend's `extractFileContent` strips the line numbers with `replace(/^\d+\| /gm, "")` — that strip pattern works as-is on this format.
- `edit.metadata.diff` is a unified-diff string in `Index: …` format (standard `patch`-tool output). The frontend currently reads diffs from `content[].type==="diff"` items, which opencode serve does NOT emit. The translator needs to synthesize a `content[]` array from `state.input`/`state.metadata` — see "Implementation gotchas" §10 below for the exact shape.
- `task.output` uses `<task_result>…</task_result>` wrapping. The frontend's `extractTaskOutput` strips `<task_metadata>…</task_metadata>` — needs updating to also strip `<task_result>` tags, or the translator should pre-strip.

### Tool call event payload (verbatim from `/tmp/dump_tool_calls.json`)

```json
{
  "type": "message.part.updated",
  "properties": {
    "sessionID": "ses_…",
    "part": {
      "id": "prt_…",
      "messageID": "msg_…",
      "sessionID": "ses_…",
      "type": "tool",
      "tool": "bash",
      "callID": "call_…",
      "state": {
        "status": "completed",
        "input": {
          "command": "echo SENTINEL > /tmp/probe-sentinel.txt && cat /tmp/probe-sentinel.txt",
          "timeout": 30,
          "workdir": "/workspace/sessions/test",
          "description": "Test bash echo and cat"
        },
        "output": "SENTINEL\n",
        ...
      }
    },
    "time": 1779468468118
  }
}
```

Mapping to `acp.schema.ToolCallProgress` field-by-field:

| ACP field | opencode source |
|---|---|
| `tool_call_id` | `properties.part.callID` |
| `title` | derive from `properties.part.tool` (e.g. `bash` → "Running command") |
| `kind` | derive from tool name |
| `status` | `properties.part.state.status` |
| `raw_input` | `properties.part.state.input` |
| `raw_output` | **frontend expects `{output: <string>}`, but opencode gives plain string in `state.output`** — translator must wrap as `{"output": state_output}` |
| `content` | **synthesize** if needed (see §Edit tool below) |

### Subagent / Task tool — works fine

Observed in `/tmp/dump_subagent.json`:
- Parent session runs the `task` tool. Child session runs the actual work (bash in this case).
- **Both sessions emit events to the same `/event` stream.** Filtering strictly by parent's sessionID drops child events; that's fine because the parent's task tool completion contains a summarized `state.output` that already includes the child's findings.
- `state.metadata` for the task tool includes `parentSessionId`, `sessionId` (child), `model`, `truncated` — useful for debugging.
- The migration plan's mention of opencode issue #6573 (subagent flows can hang) **did not reproduce** with 1.15.7 / gpt-4o-mini on a simple subagent. Doesn't mean the issue is fixed — keep the timeout/abort safety net the plan calls for.

Task tool `state.input` and `state.output` shapes (verbatim):

```json
"state.input": {
  "description": "List files in /workspace/sessions/test directory",
  "prompt": "Please list all files and directories in /workspace/sessions/test.",
  "subagent_type": "general",
  "task_id": "",
  "command": "List files in /workspace/sessions/test"
},
"state.output": "task_id: ses_… (for resuming…)\n\n<task_result>\n…\n</task_result>"
```

The frontend `extractTaskOutput` already strips `<task_metadata>…</task_metadata>` from `rawOutput.output`. Since opencode's task output uses `<task_result>` instead, the existing strip pattern may need updating during the migration — verify against the frontend before defaulting on.

### Permission flow — full grammar locked

Triggered when a tool's input matches a permission rule with `ask` action. Observed via `/tmp/test_permission2.py`.

**Event: `permission.asked`** (verbatim):
```json
{
  "type": "permission.asked",
  "properties": {
    "id": "per_…",                         // permission id
    "sessionID": "ses_…",
    "permission": "external_directory",    // permission type
    "patterns": ["/tmp/*"],                // patterns matched
    "metadata": {},
    "always": ["/tmp/*"],                  // patterns we can grant "always" for
    "tool": {
      "messageID": "msg_…",
      "callID": "call_…"                   // tool call this gates
    }
  }
}
```

**Respond:** `POST /session/{sessionID}/permissions/{permissionID}` with body:
```json
{"response": "once"}      // or "always"
```
Returns `200` with body `true`.

**Event: `permission.replied`** (verbatim):
```json
{
  "type": "permission.replied",
  "properties": {
    "sessionID": "ses_…",
    "requestID": "per_…",     // ⚠️ same id as the .asked event, but named `requestID` not `id`
    "reply": "once"           // or "always"
  }
}
```

Then the gated tool resumes and the turn completes normally via `message.updated`.

**Frontend implication:** `parsePacket.ts` does **not** currently have a `permission_asked` packet type. The migration plan defers `RequestPermissionRequest` ("deferred — wire after Phase 1") in the design doc's mapping table. Two paths:
- **Path A (Phase 1):** OpencodeServeClient auto-denies all permission asks, surfaces as `Error` to the consumer. Matches today's behavior (ACP didn't have a permission round-trip either; opencode was configured to never need it).
- **Path B (Phase 1.5):** Pass `permission.asked` through as a new SSE event type the frontend handles. Requires frontend work — `parsePacket.ts` would gain a `permission_required` case, and a new UI affordance for the user to allow/deny.

Path A is the load-bearing minimum to ship Phase 1 without regressing today's behavior.

### Abort mid-turn

`POST /session/{id}/abort` body `{}` returns `200`. The next event on `/event` is `session.error`:
```json
{
  "type": "session.error",
  "properties": {
    "sessionID": "ses_…",
    "error": {
      "name": "MessageAbortedError",
      "data": {"message": "Aborted"}
    }
  }
}
```
Followed by `session.status` → `session.idle` and the assistant `message.updated` with `info.error` set to the same shape.

Next turn on the same session works normally. No teardown needed.

### Error: bad model

`prompt_async` returns `204` (opencode accepted the request). Then `session.error`:
```json
{
  "type": "session.error",
  "properties": {
    "sessionID": "ses_…",
    "error": {
      "name": "UnknownError",
      "data": {"message": "Model not found: openai/this-model-does-not-exist."}
    }
  }
}
```

Followed by a **second** `session.error` with the same name but a full stack trace in `data.message`. The translator should prefer the first (clean message) and either drop the second or relegate it to debug logging.

After the errors, `session.idle` still fires — session is reusable.

### Error: bad session id

`POST /session/{badid}/prompt_async` → `404` with body:
```json
{"name":"NotFoundError","data":{"message":"Session not found: ses_does_not_exist"}}
```

Same shape for `GET /session/{badid}/message`. **The error JSON is opencode's standard error envelope** — the translator should detect `name` + `data.message` and surface as `Error(code=404, message=data.message)`.

### Server heartbeats

`opencode serve` emits a `server.heartbeat` event on the `/event` stream periodically (observed at ~10s intervals when idle). The migration plan's design doc doesn't mention these — log at DEBUG and ignore.

## Gap-fill design — needs revision

The migration plan says:

> on reconnect, call `GET /session/:id/message` to snapshot current state, then re-subscribe to `/event`. Persist deltas into our DB the moment we see them so the user-facing replay path stays in Onyx.

The empirical reality (`/tmp/test_reconnect2.py`):

| t (s into turn) | live deltas accumulated | snapshot text |
|---|---|---|
| 1.0 | 0 chars | 0 chars |
| 3.0 | 194 chars | 0 chars |
| 5.0 | 423 chars | 0 chars |
| 7.0 | 563 chars | 0 chars |
| post-terminator (~10) | 1104 chars | 1104 chars |

**`part.text` in `GET /session/{id}/message` is only populated AFTER the terminator fires.** During streaming, the snapshot's `text` field is empty. So:

1. **The plan's gap-fill technique does not work mid-turn.** If `/event` drops at t=3 (with 194 chars of deltas locally), reconnecting and snapshotting at t=4 returns `text=""` — no gap-fill data is available.
2. **There is still a viable recovery path** using `message.part.updated` events: each text part eventually emits one final `message.part.updated` with the full accumulated text. If we missed deltas, the next `message.part.updated` (which carries cumulative state) lets us reconcile.

### Revised gap-fill algorithm (recommend for the design doc)

Inside `OpencodeServeClient`'s reader, maintain per-partID accumulators (`local_text[partID] = ""`).

On `message.part.delta` (`field=text`):
- `local_text[partID] += delta`
- Yield `AgentMessageChunk(text=delta)`.

On `message.part.updated` (`type=text`):
- `expected = properties.part.text`
- `local = local_text[partID]`
- If `len(expected) > len(local)`:
  - **Gap-fill**: extract the missing tail `gap = expected[len(local):]`
  - Yield `AgentMessageChunk(text=gap)` to fill it
  - `local_text[partID] = expected`
- If they match, no-op.
- If `len(expected) < len(local)`: log a warning (shouldn't happen unless there's a model retry).

On `/event` reconnect:
- Don't snapshot via `GET /session/{id}/message` *yet*. The next `message.part.updated` (which fires reliably for every text part) will be the gap-fill source.
- If the turn already completed during the disconnect window, the next event on the new stream will be `session.idle` or stale; in that case, *now* call `GET /session/{id}/message` (which is post-terminator and has the full text) and synthesize one final `AgentMessageChunk` with the unseen tail.

This is more robust than the original plan because it doesn't depend on snapshot timing — it converges on `message.part.updated`, which opencode emits reliably.

### Persistence implication

Onyx's `_persist_acp_event` in `session/manager.py:_save_pending_chunks` accumulates all `AgentMessageChunk` texts into one message-level blob per turn. As long as the reconciliation above is applied, the persisted blob matches the canonical `part.text` from opencode's perspective. **No DB schema changes needed.**

## Implementation gotchas captured

These are smaller findings that didn't warrant their own section but should be fixed before/during Phase 1 of the migration.

1. **`prompt_async` 204** returns empty body. Do NOT call `r.json()` on it; check status alone.
2. **`/event` is instance-wide.** Always filter by `sessionID`. Sub-sessions (subagent's child) also emit on this stream; ignoring child events is the correct default — the parent task tool already aggregates them.
3. **`server.connected`** is emitted once per subscriber at the moment of subscription. Useful as a "ready" signal before `prompt_async`.
4. **Multiple terminator signals.** In one of three multi-turn runs, `session.idle` arrived *before* `message.updated assistant completed`. The backstops in the design doc are load-bearing — emit `PromptResponse` on whichever arrives first.
5. **Permission ID inconsistency.** `permission.asked.properties.id` vs `permission.replied.properties.requestID` — same id, different field name across the two events. Reader must alias.
6. **`session.error` may fire twice.** First with clean message, second with stack trace. Translator should prefer the first.
7. **`state.output` shape varies by tool**:
   - `bash`: string (`"SENTINEL\n"`)
   - `task`: string with `<task_result>…</task_result>` wrapping
   - Other tools not exercised here; verify before defaulting on.
8. **Backgrounding `opencode serve` from `kubectl exec`.** Plain `&` dies when exec returns. Need `setsid` + `nohup` + `</dev/null` for the supervisor entrypoint. Document in the pod/image plan.
9. **Tool input has different field names than ACP.** opencode's bash input has `command`, `timeout`, `workdir`, `description`. ACP's `raw_input` matches — pass through unchanged. But the frontend's `parsePacket.ts` looks for `file_path` / `filePath` / `path` for read/write — verify opencode tools that touch files use those names, or add aliases at the translator level.
10. **Frontend `parsePacket.ts` reads `content[]` with `{type: "diff"}` items for edit kind.** Opencode serve doesn't emit a `content` array — diffs need to be synthesized at the translator level. Exact synthesis from the empirical edit-tool payload:

    ```python
    content = [{
        "type": "diff",
        "path": state.input.filePath,
        "oldText": state.input.oldString,
        "newText": state.input.newString,
    }]
    ```

    For the read-tool path, also synthesize:

    ```python
    content = [{
        "type": "content",
        "content": {"type": "text", "text": state.output},  # already line-numbered
    }]
    ```

    The frontend's `extractFileContent` / `extractDiffData` then work unchanged.

## Plan updates needed

In `opencode-serve-migration.md`:
- §Empirical validation already lists `message.part.delta` for streaming. Add a sub-bullet that `message.part.updated` (cumulative state on the same part) is the gap-fill anchor — not `GET /session/:id/message` during streaming.
- §Known opencode bugs we must design around → update the `/event` reconnect mitigation to point at the revised gap-fill (using `message.part.updated` as the reconcile point) instead of `list_messages`.
- §Important Notes → add a callout that `server.heartbeat` exists and can be passed through transparently as our `SSEKeepalive`.

In `features/opencode-serve-client.md`:
- §Reconnect & gap-fill — replace the existing algorithm with the revised one above. The plan's `list_messages` strategy is wrong during streaming.
- §Event translation mapping table — note `session.heartbeat` (translates to nothing, ignored).
- §Edit tool / content synthesis — add a callout that for edit-kind tool calls, the translator may need to fabricate the `content[]` array of `{type: "diff", oldText, newText, path}` from `state.input`/`state.output` to match what the frontend expects today.
- §Open questions — add: "Should we pass through `permission.asked` as a new SSE type, or auto-deny in Phase 1 to keep frontend untouched?" This is now a deliberate decision rather than a deferred TODO.

## Frontend changes

**Phase 1 path = zero frontend PRs.** Decision: auto-handle permissions in the client (Path A — see [`features/opencode-serve-client.md`](./features/opencode-serve-client.md) §Decisions #1). The SSE wire format to the browser is unchanged. Existing `parsePacket.ts` handles every event type the migrated client emits (`agent_message_chunk`, `agent_thought_chunk`, `tool_call_start`, `tool_call_progress`, `prompt_response`, `error`).

There are two small *backend-side* translator-layer changes the test report unearthed that don't reach the frontend wire but do affect the translator code in `OpencodeServeClient`:

1. **Edit-tool `content` synthesis.** Opencode serve doesn't emit `content[]` arrays for tool parts; the translator synthesizes `{type: "diff", path, oldText, newText}` from `state.input.{filePath, oldString, newString}` so `parsePacket.ts:extractDiffData` works unchanged. Field-name table in the design doc §Tool-call content synthesis.
2. **Task tool output stripping.** `state.output` for the task tool is wrapped in `<task_result>…</task_result>`. The frontend's `extractTaskOutput` currently strips `<task_metadata>` only. Either update the frontend's regex OR pre-strip in the translator. Recommend the latter (translator), since it keeps the frontend untouched.

Frontend Path B (surface permission asks to the user) is a product feature, not a migration requirement. Tracked as a possible follow-up.

## Repro scripts (preserved in `/tmp/`)

For future reference / CI integration when Phase 0 lands in-tree:

| Path | Purpose |
|---|---|
| `/tmp/serve_harness.py` | Reusable scenario runner (`python serve_harness.py <name> [dump.json]`). Has 7 scenarios. |
| `/tmp/test_permission2.py` | Permission ask + reply round-trip + terminator. |
| `/tmp/test_reconnect.py` | Reconnect with mid-turn snapshot (proves snapshot is empty during streaming). |
| `/tmp/test_reconnect2.py` | Snapshot timing — proves `part.text` only populated after terminator. |
| `/tmp/test_terminator_payload.py` | Shape of the terminating `message.updated` + last `message.part.updated`. |

When Phase 0 lands as `sandbox/opencode/try_serve_client.py`, port these scripts wholesale; they're the empirical contract.
