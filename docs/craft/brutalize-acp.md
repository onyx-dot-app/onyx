# Brutalize the ACP transport

Delete the `opencode acp` transport from Onyx Craft. Make `opencode serve` the only way to drive an agent. Keep `acp.schema` — it's now the internal sandbox-event protocol and the abstraction boundary for a future in-house agent harness.

**Prerequisite:** [`docker-opencode-serve.md`](./docker-opencode-serve.md) must land first. As of writing, `DockerSandboxManager.send_message` still uses `DockerACPExecClient`; that path must move to opencode-serve before the ACP transport can be deleted.

## Issues to Address

After [`opencode-serve-migration.md`](./opencode-serve-migration.md) and `docker-opencode-serve.md` land, both backends use `OpencodeServeClient`. At that point:

1. **`AGENT_TRANSPORT=acp` is unreachable in any sane prod config**, but the code path is still wired up, the env var is still in `.vscode/.env.k8s.template:114` defaulted to `acp`, and the K8s manager still branches on it in eight places (`if AGENT_TRANSPORT == AgentTransport.ACP` / `!= SERVE`). Anyone reading the code reasonably thinks ACP is a supported transport.

2. **The `ACPExecClient` (K8s) and `DockerACPExecClient` (Docker) are dead modules** sitting in `backend/onyx/server/features/build/sandbox/{kubernetes,docker}/internal/acp_exec_client.py`. They still compile, their tests still run, but nothing in `send_message` calls them.

3. **`entrypoint.sh` still has an idle branch** (`tail -f /dev/null` when `AGENT_TRANSPORT != serve`, `backend/onyx/server/features/build/sandbox/kubernetes/docker/entrypoint.sh:36,46-54`) that exists solely to be a rollback target for an ACP transport that no longer ships.

4. **The K8s manager writes per-session `opencode.json` files in the ACP branch** (`kubernetes_sandbox_manager.py:1463-1471, 1936-1947`) that serve doesn't read. Both code paths can collapse to "no per-session config; the pod-wide `OPENCODE_CONFIG_CONTENT` is authoritative."

5. **The `AgentTransport` enum and `AGENT_TRANSPORT` config exist for a one-value decision.** Eight branches, one test fixture, one pod env var, one entrypoint env read, one shell default. Net: ~150 lines of conditional control flow with no second branch.

This change deletes the transport selector and all of its branches. **The wire format (`acp.schema`) stays.** See "What we are NOT doing" below.

## Important Notes

### What `acp.schema` becomes

Today `OpencodeServeClient.translate_opencode_event` (`backend/onyx/server/features/build/sandbox/opencode/serve_client.py:330-`) translates opencode-native `/event` payloads into `AgentMessageChunk`, `ToolCallStart`, `PromptResponse`, etc. The session manager, the SSE serializer, the frontend, and the persistence layer all consume those types.

After this PR, that translation function is the *only* producer of `acp.schema` events. Which is fine: the schema is the abstraction between "whatever the agent harness is" and "Onyx's session/streaming machinery." When opencode is eventually replaced by an in-house harness, that harness's transport client implements a new `translate_<harness>_event` and the rest of Onyx is untouched.

This is the explicit reason for not doing [`drop-acp-layer.md`](./drop-acp-layer.md) in the same PR. That follow-up renames `acp.schema` to an Onyx-owned module and drops the upstream PyPI dep — a worthwhile cleanup, but one that touches ~30 files and is structurally unrelated to deleting the transport. Keep them separate. Mark `drop-acp-layer.md` as deferred-indefinitely with a one-paragraph "and here's why we now want to keep the schema" note.

### Branches that become unconditional

| File | Lines | What collapses |
|---|---|---|
| `backend/onyx/server/features/build/configs.py` | 193-214 | Delete `AgentTransport` enum and `AGENT_TRANSPORT` constant entirely |
| `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` | 560 | Pod env injection of `AGENT_TRANSPORT` removed |
| same | 1459-1515 | `opencode.json` per-session file writing in `setup_session_workspace` deleted; the function shrinks |
| same | 1933-1947 | Same in `_regenerate_session_config` (snapshot-restore path) |
| same | 2049-2060 | `send_message` dispatcher collapses to a direct call to (the renamed) `_send_message_via_serve` |
| same | 2062-2178 | `_send_message_via_acp` + helpers deleted |
| same | 1990-2024 | `_create_ephemeral_acp_client` deleted |
| same | 2196-2398 | `_wait_for_opencode_serve_ready`, `prompt_slot`, `ensure_opencode_session`, `list_subagents`, `subscribe_to_opencode_session` lose their `if AGENT_TRANSPORT != SERVE: ...` guards |
| `backend/onyx/server/features/build/sandbox/base.py` | 280-420 | Docstrings tighten ("serve-only kwargs" → just "kwargs"); `prompt_slot` and `ensure_opencode_session` default no-ops removed iff the base-class refactor from `docker-opencode-serve.md` already made these real impls |
| `backend/onyx/server/features/build/session/manager.py` | 1451-1455 | `_ensure_opencode_session_id` drops the ACP-returns-None guard |
| `backend/onyx/server/features/build/sandbox/kubernetes/docker/entrypoint.sh` | 36, 46-54 | Idle branch deleted; the script unconditionally runs `opencode serve` in a restart loop |

### Files that get deleted outright

- `backend/onyx/server/features/build/sandbox/kubernetes/internal/acp_exec_client.py`
- `backend/onyx/server/features/build/sandbox/docker/internal/acp_exec_client.py`
- `backend/tests/unit/onyx/server/features/build/sandbox/test_docker_acp_exec_client.py`
- The `internal/` directories under both `kubernetes/` and `docker/` may become empty after the deletion; remove or repurpose accordingly.

### Files NOT deleted

- `backend/onyx/server/features/build/sandbox/acp/base.py` — defines the `ACPEvent` type alias and `ACPExecClientBase`. The type alias is still imported widely; the base class is unreachable but its deletion lives in [`drop-acp-layer.md`](./drop-acp-layer.md). Keep both for now.
- Anything under `acp.schema` (the PyPI package) — still our wire format.

### Things that look like ACP but aren't

These references stay because they're talking about the schema, not the transport:

- Log prefixes like `[SANDBOX-ACP]` in `_send_message_via_acp` go away with the function; `[SANDBOX-SERVE]` prefixes stay.
- Docstrings in `api/packets.py:3-24` ("ACP events are passed through directly from acp.schema") stay — that's the schema reference and remains accurate.
- `packet_logger.log_acp_event` / `log_acp_event_yielded` / `log_acp_client_*` — the names refer to the event schema, not the transport. Rename if desired, but it's out of scope; not load-bearing for this change.

### Image versioning

Removing the `AGENT_TRANSPORT` env read in `entrypoint.sh` means the image no longer responds to that env var. An old image talking to a new api_server is fine (the env var just isn't read). A new image talking to an old api_server is also fine — the api_server might still pass `AGENT_TRANSPORT=serve` for a release or two; the entrypoint ignores it. **No image bump is required**, but bumping to `v0.1.45` is good hygiene since the entrypoint changed.

### Helm / network policy

`deployment/helm/charts/onyx/templates/network-policy-sandbox-push.yaml:38-39` has a comment mentioning `AGENT_TRANSPORT=serve`. The egress rule already permits port 4096; the only change is the comment. Mechanical.

### `.env` templates

`.vscode/.env.k8s.template:113-114` defaults `AGENT_TRANSPORT=acp`. Delete the two lines. Search prod / staging configmaps for explicit `AGENT_TRANSPORT=` settings; if any tenant has it set, removing the env var has no effect (it just stops being read) but flag it in the rollout note.

### What if a prod tenant still has `AGENT_TRANSPORT=acp` in their config?

Before merge, grep the prod environment for explicit `AGENT_TRANSPORT=acp` and force a switch to `serve` (or unset) in those configs first. After this PR, the env var is unread; `acp` becomes a silent no-op rather than a behavior switch. The risk is a tenant who *thinks* they're on ACP, sees serve behavior, and is confused by the discrepancy. One-line release note resolves this.

## Implementation Strategy

This is structurally a deletion PR. The discipline is "don't refactor; just delete the dead branch and let the surviving code stand on its own."

### Order of operations

1. **Verify the docker→serve prerequisite has landed and soaked.** `DockerSandboxManager.send_message` must call `OpencodeServeClient`. Grep for `DockerACPExecClient` in `docker_sandbox_manager.py` — must return zero matches before starting this PR.

2. **Inline the K8s serve dispatch.** In `kubernetes_sandbox_manager.py:send_message`, delete the `if AGENT_TRANSPORT == AgentTransport.SERVE:` check; the body becomes a direct call to the (now-renamed) `_send_message_via_serve`. Rename it to `send_message`'s body. Delete `_send_message_via_acp` and `_create_ephemeral_acp_client`.

3. **Delete the ACP exec clients.** `rm` both `acp_exec_client.py` files and the docker test. Run mypy / pytest collection to catch any straggler imports.

4. **Remove `AGENT_TRANSPORT` from configs.** Delete the `AgentTransport` enum and the `AGENT_TRANSPORT` constant from `configs.py`. Every `from onyx.server.features.build.configs import AGENT_TRANSPORT` becomes an import error — fix each call site by deleting the guard, not by adding an `if True:`. The grep is the to-do list.

5. **Inline the remaining guards.** For each `if AGENT_TRANSPORT != SERVE: return ...` / `if AGENT_TRANSPORT == ACP: ...`, delete the guard and (for the latter) the entire ACP branch body. The lists in "Branches that become unconditional" above is the manifest.

6. **Collapse per-session `opencode.json` writing.** In `setup_session_workspace` and `_regenerate_session_config`, the `opencode_json_write_line` indirection goes away; the `printf > opencode.json` shell snippet is deleted entirely. AGENTS.md writing stays. The pod-wide `OPENCODE_CONFIG_CONTENT` is the only config opencode-serve sees.

7. **Strip `entrypoint.sh`.** Delete the `if [ "$TRANSPORT" != "serve" ]` branch and the `TRANSPORT="${AGENT_TRANSPORT:-acp}"` line. The script becomes a straight supervisor loop around `opencode serve`. Keep the SIGTERM trap and the exponential backoff.

8. **Update docs and templates.** `.vscode/.env.k8s.template`, `deployment/helm/charts/onyx/templates/network-policy-sandbox-push.yaml` comment, `docs/craft/opencode-serve-migration.md` (mark Phase 5 done), `docs/craft/issues/opencode-serve-deploy-gotchas.md` and `opencode-serve-event-stream-pitfalls.md` (drop conditional language), `docs/craft/drop-acp-layer.md` (deferred-indefinitely note plus the "we now keep the schema deliberately" paragraph).

### Why these are separable commits within one PR

Each step is independently revertable up to the previous one:

- Step 1 (verification) is free.
- Step 2 doesn't change behavior — `send_message` already routed to serve in prod.
- Steps 3–4 reveal compile errors that step 5 fixes; landing them together makes the diff readable.
- Step 6 is the only one that touches a script `setup_session_workspace` runs in the pod; verify it works end-to-end in kind before merging.
- Step 7 changes container behavior on next pod create. No existing pod is affected. Safe.
- Step 8 is doc-only.

### What doesn't change

- `send_message`'s public signature on `SandboxManager` (the `opencode_session_id` / `agent_provider` / `agent_model` / `on_opencode_session_resolved` kwargs). Frozen by `acp.schema`-emitting tests and the session manager's call site.
- The SSE event shape leaving the api_server to the browser. Frontend is untouched.
- The `BuildSession.opencode_session_id` DB column. Stays nullable for backwards-compat with rows from the migration window.
- Snapshot/restore tar format. Same files in, same files out.

## Tests

**Tests deleted:**
- `backend/tests/unit/onyx/server/features/build/sandbox/test_docker_acp_exec_client.py`
- The `AGENT_TRANSPORT=ACP` branch test in `backend/tests/unit/onyx/server/features/build/sandbox/test_prompt_slot.py:132` (the test asserting ACP no-ops the slot lock — meaningless after this PR).
- Any `monkeypatch.setattr(..., "AGENT_TRANSPORT", AgentTransport.SERVE)` fixtures in `test_opencode_serve_streaming.py` and `test_prompt_slot.py` — they exist because the default is ACP. After this PR there is no `AGENT_TRANSPORT` to set; remove the fixtures and the imports.

**Tests that must continue to pass unchanged:**
- `backend/tests/external_dependency_unit/craft/test_opencode_serve_streaming.py` — the streaming behavior under serve. This is the regression net.
- `backend/tests/integration/tests/craft/test_messages_api.py` — full end-to-end. Was already running with serve in CI; verify the env-var removal didn't break the fixture wiring.
- `backend/tests/external_dependency_unit/craft/test_snapshot_restore.py` — snapshots already capture `.opencode-data`; this PR doesn't touch that path but pod entrypoint did change. Run it.

**New test (small, mechanical):**
- A grep-based unit test asserting no production code outside `tests/` and `docs/` references `AGENT_TRANSPORT` or imports `ACPExecClient` / `DockerACPExecClient` / `_send_message_via_acp`. Belt-and-suspenders against a future re-import via copy-paste from an old branch. Pre-commit hook is also fine.

**No new integration or playwright tests.** This is a deletion; the existing serve coverage is the proof of correctness.

## Out of scope

- Renaming `acp.schema` and dropping the `agent-client-protocol` PyPI dep. Deliberately deferred — see [`drop-acp-layer.md`](./drop-acp-layer.md), which gets an update in this PR explaining the schema is now the long-term abstraction boundary for a future in-house agent harness.
- Renaming `packet_logger.log_acp_event` and friends. The names refer to the event schema, which stays.
- Replacing `acp.schema` with opencode-native types on the SSE wire to the browser. Possible follow-up; orthogonal to this change.
- Refactoring the K8s/Docker serve plumbing into a single shared mixin. The factoring belongs in [`docker-opencode-serve.md`](./docker-opencode-serve.md); if it didn't happen there, do it as a separate follow-up rather than smuggling it into this deletion PR.
