# Drop the ACP layer

Follow-up to [`opencode-serve-migration.md`](./opencode-serve-migration.md). Two phases — Phase 1 (transport) and Phase 2 (vocabulary cleanup) shipped together. Phase 3 (inline the schema types + drop the PyPI dep) is deferred indefinitely behind a wrapper.

## What shipped

**The `opencode acp` transport is gone.** `OpencodeServeClient` is the only path behind `KubernetesSandboxManager.send_message` and `DockerSandboxManager.send_message`. `AGENT_TRANSPORT` env var, the `AgentTransport` enum, the per-message ACP exec clients (`ACPExecClient`, `DockerACPExecClient`), `ACPExecClientBase`, and the entrypoint idle branch are deleted. Per-session `opencode.json` writes are gone — provider config lives at pod/container scope via `OPENCODE_CONFIG_CONTENT`. Port 8081 (`AGENT_PORT`) cleared from the pod/service/Dockerfile.

**The "ACP" vocabulary is gone from production code, tests, deployment, and non-historical docs.** Internal symbols renamed: `ACPEvent → SandboxEvent`, `_yield_acp_events → _yield_sandbox_events`, `_persist_acp_event → _persist_sandbox_event`, `[ACP-EVENT] → [SANDBOX-EVENT]`, `ACPError → SandboxError`, `_merge_acp_with_announces → _merge_events_with_announces`. Config: `ACP_MESSAGE_TIMEOUT → SANDBOX_TURN_TIMEOUT_SECONDS`. Frontend: `ACPEvent → SandboxEvent`, `ACPErrorEvent → SandboxErrorEvent`, `ACPBaseEvent → SandboxEventBase`, `ACPErrorPacket → SandboxErrorPacket`. Every `from acp.schema import …` now routes through `backend/onyx/server/features/build/sandbox/event_schema.py` — a thin re-export wrapper, the only place `acp.schema` is mentioned in the tree.

## What's deferred

Inlining the schema types into Onyx-owned Pydantic models and dropping the `agent-client-protocol>=0.7.1` PyPI dep. The wrapper makes this a single-file change — replace the re-exports in `event_schema.py` with local Pydantic definitions, drop the dep, done.

Why deferred:

- The wrapper hides the dep from every consumer. Nothing reads "ACP" anywhere in the codebase, so the dep doesn't leak conceptually.
- Inlining means copying ~9 Pydantic models field-for-field with byte-identical `model_dump(by_alias=True)` output. Tractable but a real code review burden.
- The schema is the abstraction boundary for a future in-house agent harness. When that work starts and we need to evolve fields the upstream doesn't ship, *that's* the trigger — replace the wrapper's contents, drop the dep, evolve freely.

## DB-shape consumers worth noting before any inline

If/when you do swap the wrapper for inlined types:

- `tool_call_progress` and `agent_plan_update` rows in `BuildMessage.message_metadata` are `model_dump(by_alias=True)` JSON. Old rows have whatever aliases the upstream package shipped; new rows would have whatever the inlined types ship. The frontend already defensively reads both `raw_input`/`rawInput` and `tool_call_id`/`toolCallId` in `packetTypes.ts`, so minor drift is survivable — but identical aliases are the safe play.
- All other persisted message types (`user_message`, `agent_message`, `agent_thought`, task output) are custom-shaped synthesis, not raw schema output. Orthogonal to the inline.

## Reference plan (when Phase 3 becomes worth doing)

1. **Inline the types.** In `sandbox/event_schema.py`, replace the `from acp.schema import …` lines with local Pydantic v2 model definitions. Same field names, same validators, same `model_dump(by_alias=True)` output. Add a round-trip test that asserts the JSON shape matches a canned reference per type — locks the wire contract.

2. **Drop the dep.** Remove `agent-client-protocol>=0.7.1` from `pyproject.toml`. Re-lock with `uv sync`.

3. **Sweep `ee/`.** Enterprise Edition code might re-import `acp.schema` directly. Grep before merging.

### Risks specific to Phase 3

- **Pydantic field-shape divergence.** Easy to miss a `Field(alias=…)` or `model_config = ConfigDict(populate_by_name=True)`. The round-trip test catches the structural case; manual Playwright pass on at least one Craft session catches the wire-format case.
- **DB row-shape divergence** for `tool_call_progress` and `agent_plan_update`. Keep aliases byte-identical or backfill.

### Out of scope even for Phase 3

- Replacing the inlined types with opencode-native types on the SSE wire.
- Renaming the class names themselves (`AgentMessageChunk` → `AssistantTextDelta` etc.) — cosmetic, touches every consumer.
