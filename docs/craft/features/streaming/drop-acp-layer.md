# Drop the ACP layer

This is a shipped historical note from the removed OpenCode serve migration
plan. Phase 1 (transport) and Phase 2
(vocabulary cleanup) shipped together. Phase 3 (inline schema types and drop
the PyPI dependency) is still deferred behind a wrapper.

## What shipped

**The `opencode acp` transport is gone.** `OpencodeServeClient` is the only
message transport behind `SandboxManager.send_message`. `AGENT_TRANSPORT`, the
`AgentTransport` enum, the per-message ACP exec clients, `ACPExecClientBase`,
and the entrypoint idle branch are deleted. Per-session `opencode.json` writes
are gone. Provider config lives at pod scope via `OPENCODE_CONFIG_CONTENT`.
Port 8081 (`AGENT_PORT`) is no longer part of the sandbox pod or image.

**The "ACP" vocabulary is gone from production call sites and non-historical
docs.** Internal symbols were renamed: `ACPEvent -> SandboxEvent`,
`_yield_acp_events -> _yield_sandbox_events`,
`_persist_acp_event -> _persist_sandbox_event`,
`[ACP-EVENT] -> [SANDBOX-EVENT]`, `ACPError -> SandboxError`, and
`_merge_acp_with_announces -> _merge_events_with_announces`. Config changed
from `ACP_MESSAGE_TIMEOUT` to `SANDBOX_TURN_TIMEOUT_SECONDS`. The remaining
upstream schema import is isolated in
`backend/onyx/server/features/build/sandbox/event_schema.py`.

## What's deferred

Inlining the schema types into Onyx-owned Pydantic models and dropping the
`agent-client-protocol>=0.7.1` PyPI dependency. The wrapper keeps this a
single-file boundary: replace the re-exports in `event_schema.py` with local
Pydantic definitions, then drop the dependency.

Why deferred:

- The wrapper hides the dependency from every consumer. Nothing reads "ACP"
  outside this historical note.
- Inlining means copying about nine Pydantic models field-for-field with
  byte-identical `model_dump(by_alias=True)` output. That is tractable, but it
  is real code review work.
- The schema is the boundary for a future in-house agent harness. When that
  work needs fields upstream does not ship, replace the wrapper contents and
  drop the dependency.

## DB-shape consumers worth noting before any inline

If/when you do swap the wrapper for inlined types:

- `tool_call_progress` and `agent_plan_update` rows in
  `BuildMessage.message_metadata` are `model_dump(by_alias=True)` JSON. Old
  rows have the aliases the upstream package shipped. New rows would have the
  aliases the inlined types ship. The frontend already reads both
  `raw_input`/`rawInput` and `tool_call_id`/`toolCallId` in `packetTypes.ts`,
  but identical aliases are the safe choice.
- All other persisted message types are custom-shaped synthesis, not raw
  schema output. This includes `user_message`, `agent_message`,
  `agent_thought`, and task output.

## Reference plan (when Phase 3 becomes worth doing)

1. **Inline the types.** In `sandbox/event_schema.py`, replace the
   `from acp.schema import ...` lines with local Pydantic v2 model
   definitions. Keep the same field names, validators, and
   `model_dump(by_alias=True)` output. Add a round-trip test that compares the
   JSON shape to a canned reference per type.

2. **Drop the dep.** Remove `agent-client-protocol>=0.7.1` from
   `pyproject.toml`. Re-lock with `uv sync`.

3. **Sweep `ee/`.** Enterprise Edition code might re-import `acp.schema`
   directly. Grep before merging.

### Risks specific to Phase 3

- **Pydantic field-shape divergence.** Easy to miss a `Field(alias=...)` or
  `model_config = ConfigDict(populate_by_name=True)`. The round-trip test
  catches the structural case. A manual Playwright pass catches the wire
  format case.
- **DB row-shape divergence** for `tool_call_progress` and
  `agent_plan_update`. Keep aliases byte-identical or backfill.

### Out of scope even for Phase 3

- Replacing the inlined types with opencode-native types on the SSE wire.
- Renaming the class names themselves, such as `AgentMessageChunk` to
  `AssistantTextDelta`. That is cosmetic and touches every consumer.
