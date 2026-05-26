# Drop the ACP layer

> **Status (post-[`brutalize-acp.md`](./brutalize-acp.md)): deferred indefinitely.** Phase 5 of the serve migration deleted the opencode-acp transport — the per-message exec'd client, the `AGENT_TRANSPORT` selector, the entrypoint idle branch. What this doc proposes — renaming `acp.schema` to an Onyx-owned module and dropping the `agent-client-protocol` PyPI dep — is a real cleanup but is now *intentionally* on ice. `acp.schema` is the internal sandbox-event protocol that `OpencodeServeClient.translate_opencode_event` produces and that every consumer reads. It's also the abstraction boundary we want for a future in-house agent harness: that harness gets its own `translate_<harness>_event` function with the same return type, and nothing else in Onyx has to change. Owning the schema ourselves becomes worth doing when (a) we need to evolve fields the upstream package doesn't, or (b) the in-house harness work actually starts. Until then, the cost of one PyPI dep and a slightly misleading module name beats touching 30 consumer files for zero behavior change. The plan below is preserved as the reference design for that eventual PR.

Follow-up to [`opencode-serve-migration.md`](./opencode-serve-migration.md). Removes the now-dead Agent Client Protocol code from the tree once `opencode serve` is the only runtime path.

## Issues to Address

After the serve migration, two things are simultaneously true:

1. **No code path in production speaks ACP anymore.** `OpencodeServeClient` is the only client behind both `KubernetesSandboxManager.send_message` and `DockerSandboxManager.send_message`. The ACP exec clients and `ACPExecClientBase` are unreachable at runtime.

2. **The codebase still claims to speak ACP all over the place.** Six files outside `sandbox/acp/` import from `acp.schema` (the upstream `agent-client-protocol` PyPI package's Pydantic schema):
   - `backend/onyx/server/features/build/session/manager.py` — 8 imports, the load-bearing consumer
   - `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` — 1 import (`PromptResponse`)
   - `backend/onyx/server/features/build/scheduled_tasks/executor.py` — 1 import (`RequestPermissionRequest`)
   - `backend/onyx/server/features/build/api/packets.py` — docstring reference only
   - `backend/tests/external_dependency_unit/craft/test_streaming_persistence.py` — 5 imports
   - `backend/tests/external_dependency_unit/craft/test_kubernetes_sandbox.py` — 5 imports

   Plus `sandbox/acp/base.py` itself (the now-dead `ACPExecClientBase`) and the two `acp_exec_client.py` subclasses (K8s + Docker) which are unreachable but still compile.

3. **The `agent-client-protocol>=0.7.1` PyPI dep is still pinned** in `pyproject.toml` for the schema types only. We're paying for a transitive dep we no longer use as a protocol — just as a Pydantic schema bag.

4. **The `acp.schema` name lies.** New contributors reading `from acp.schema import AgentMessageChunk` reasonably expect Onyx to be speaking ACP somewhere. After serve, it isn't.

## Important Notes

### Type ownership is the load-bearing change

The current arrangement is: `agent-client-protocol` PyPI package defines the types → Onyx imports them → Onyx's `OpencodeServeClient` translates opencode-native events into them → consumers read them. After this PR, Onyx defines the types itself.

This is a transcription, not a redesign. The Pydantic field shapes that `session/manager.py` reads (`event.content.text`, `event.tool_name`, `event.status`, `event.stopReason`, etc.) must stay byte-for-byte identical or every consumer breaks.

The reason to do it anyway: these types ARE Onyx's internal event protocol now. Owning them ourselves means we can evolve them without coordinating with an upstream package whose actual protocol we've abandoned. We can also drop fields we never use.

### Types Onyx actually consumes

Enumerated from the imports above:

| Type | Used by | Fields read by Onyx code |
|---|---|---|
| `AgentMessageChunk` | session manager, tests | `content` (which has `type`, `text`) |
| `AgentThoughtChunk` | session manager, tests | `content` |
| `ToolCallStart` | session manager, tests | `tool_call_id`, `title`, `kind`, `raw_input`, `status`, `content`, `locations` |
| `ToolCallProgress` | session manager, tests | `tool_call_id`, `title`, `status`, `content`, `raw_input`, `raw_output` |
| `AgentPlanUpdate` | session manager | `entries` (V0-era, possibly removable — verify) |
| `CurrentModeUpdate` | session manager | `current_mode_id` (V0-era, possibly removable — verify) |
| `PromptResponse` | session manager, K8s sandbox manager, tests | `stop_reason` |
| `Error` (aliased `ACPError`) | session manager, tests | `code`, `message` |
| `RequestPermissionRequest` | scheduled tasks | (verify field usage) |

The exact field shape comes from grepping each consumer; do this at PR time, not in the doc, since the answer is in code.

### What the upstream package gives us that we'd lose

`agent-client-protocol` ships:
- Pydantic schema models (the ones above).
- A Python ACP server/client implementation we don't use (we have our own in `sandbox/acp/`).
- Validation logic baked into the Pydantic models (`field_validator`s, etc.).

Only (1) is load-bearing for us. (2) is dead code. (3) we get for free by re-defining the models as Pydantic ourselves — same validation behavior.

### Naming

Pick one and rename consistently. Recommend `sandbox_events.schema`:

```python
# before
from acp.schema import AgentMessageChunk

# after
from onyx.server.features.build.sandbox.events.schema import AgentMessageChunk
```

Module location: `backend/onyx/server/features/build/sandbox/events/schema.py`.

Class names stay the same (`AgentMessageChunk`, `ToolCallStart`, etc.) — the rename is module-level. The cost of also renaming classes is ~30 more touch sites for ~zero clarity gain at this stage; leave class-name evolution to a later pass once usage stabilizes.

The `acp/` package directory under `sandbox/` is deleted in this PR — see "Deletions" below.

## Implementation Strategy

### Order of operations

1. **Inline the types.** Create `sandbox/events/schema.py` with the subset Onyx uses. Copy field-for-field from `acp.schema` — Pydantic v2 models, same field names, same validators, same `model_dump(by_alias=True)` behavior. Add `__all__` listing the public names.

2. **Migrate consumers, one file per commit.** Each commit swaps `from acp.schema import X` → `from onyx.…events.schema import X`. Six files of production code + tests. Stable atomic changes — each one is a search-and-replace plus a `mypy` pass.

3. **Update `OpencodeServeClient`'s translation layer.** Its mapping function (`translate_opencode_event` in [`features/opencode-serve-client.md`](./features/opencode-serve-client.md)) currently returns `acp.schema` types — repoint to `sandbox.events.schema`. Single file change.

4. **Delete the ACP code.** Once nothing imports from `acp.schema` anymore:
   - `rm -rf backend/onyx/server/features/build/sandbox/acp/`
   - `rm backend/onyx/server/features/build/sandbox/kubernetes/internal/acp_exec_client.py`
   - `rm backend/onyx/server/features/build/sandbox/docker/internal/acp_exec_client.py`
   - `rm backend/tests/unit/onyx/server/features/build/sandbox/test_docker_acp_exec_client.py`

5. **Drop the PyPI dep.** Remove `agent-client-protocol>=0.7.1` from the project's `pyproject.toml`. Re-lock. `uv sync` to confirm no transitive consumer relies on it.

6. **Sweep stragglers.** Search for the literal string `ACP` across the codebase:
   - Comments (`# ACP event …`) — update to "sandbox event" / "agent stream event".
   - Log prefixes (`[K8S-ACP]`, `[DOCKER-ACP]`, `[SANDBOX-ACP]`) — already gone with the client files, but verify.
   - Docstring references (`api/packets.py:10` mentions "ACP events passed through from acp.schema") — rewrite.
   - Variable names (`acp_event`, `acp_session_id`, `_yield_acp_events`, `_persist_acp_event`) — rename to `sandbox_event` / `opencode_session_id` (the latter already exists from the migration's persistence change).

   Keep this sweep mechanical; no behavior changes here.

### Why steps 2–5 are separate commits, not one big PR

The migration is intrinsically search-and-replace, but doing it as one 30-file commit makes review impossible. Each consumer is independent — its commit changes one file, lint passes, tests pass. The PR-level diff stays large but per-commit diffs are reviewable on their own.

### What can be cut on the way through

The migration is also a chance to drop fields/classes Onyx genuinely doesn't use:

- **`AgentPlanUpdate` and `CurrentModeUpdate`** are V0-era. The migration plan notes they may not be load-bearing for any current consumer. Grep at PR time; if no real consumer, drop from the inlined schema.
- **Anything not in the "Types Onyx actually consumes" table** is provably unused and stays in the upstream package only.

If unsure about a type, keep it — the cost of an unused Pydantic model is essentially zero.

### Static type safety

Run `mypy` (or pyright; check the repo's linter config) after each consumer migration. The renamed types should be drop-in compatible, so any mypy error indicates either:
- A field that we copied wrong (Pydantic shape doesn't match).
- A consumer using `isinstance(event, AgentMessageChunk)` checks across the type boundary (the new class is a different Python class than the old one, even with identical fields). Find all `isinstance` checks ahead of time and migrate them with the import line.

## Tests

This is a refactor, not a behavior change. Test goals:

1. **No behavior regression.** The existing test suite — particularly `test_streaming_persistence.py` and `test_kubernetes_sandbox.py` — must pass byte-for-byte after the rename. If it doesn't, the inlined types diverge from upstream and that's a real bug to fix.
2. **No `acp` references survive.** Add a CI check (or pre-commit hook) that fails if anyone reintroduces `from acp` or `import acp.` outside the `.venv`. Single grep, one line of shell. Belt-and-suspenders against accidental re-import via copy-paste from old branches.
3. **Schema round-trip.** Add a unit test that constructs each inlined Pydantic type with sample fields, calls `model_dump(by_alias=True, mode="json")`, and asserts the JSON shape matches a canned reference. Locks the wire contract so a future refactor can't silently break the browser SSE encoding.

No new external-dependency-unit or integration tests are needed; this PR doesn't touch runtime behavior.

## Risks

- **Subtle Pydantic field shape divergence.** Easy to miss a `Field(alias=…)` or a `model_config = ConfigDict(populate_by_name=True)`. Mitigation: copy the source verbatim and diff against the upstream package post-rename. The round-trip schema test catches the obvious cases; fields with `by_alias` semantics need explicit attention.
- **Hidden consumer in `ee/`.** Enterprise Edition code (`backend/ee/`) might import `acp.schema`. The initial grep didn't find any, but verify before deleting the PyPI dep — `ee/` is sometimes not in the default grep scope.
- **Browser SSE field-name regression.** The web frontend deserializes the SSE payload by field name. The Pydantic `by_alias=True` serialization is what produces those field names. If the inlined types use different aliases, the frontend breaks silently (fields go missing, not type-error). The round-trip schema test (Tests §3) is the structural fix; manual Playwright pass on at least one Craft session is the soak test.
- **Re-import via cargo-cult.** Once `agent-client-protocol` is gone from `pyproject.toml`, anyone copying code from a pre-migration branch will hit an import error. That's fine — they'll fix it. But add a `Migrated from acp.schema` note to the new `events/schema.py` module docstring so the import is greppable from history.

## Out of scope

- Replacing the inlined types with opencode-native types from a generated SDK. This is the more aggressive "Option B" from the design conversation: instead of Onyx owning the schema, consumers read opencode's native `Message`/`MessagePart`/etc. directly. Eliminates the translation layer in `OpencodeServeClient` but touches every consumer. Decide after this PR ships and we have a feel for how stable the inlined types are.
- Renaming the class names themselves (`AgentMessageChunk` → `AssistantTextDelta`, etc.) to match opencode's vocabulary. Out of scope for the same reason — every consumer changes. Cosmetic; defer.
- Removing the `acp.schema` references from comments in `web/` (frontend). Browser-side cleanup is its own (small) PR.
- The `_try_resume_existing_session` heuristic and related session-list scaffolding. Already deleted in the serve migration (Phase 5), nothing left here to remove.
