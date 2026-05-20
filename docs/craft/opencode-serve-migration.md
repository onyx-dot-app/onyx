# Opencode Serve Migration (ACP → HTTP)

Replace the current per-message `opencode acp` subprocess with a long-lived `opencode serve` HTTP server running inside the sandbox pod. Decouple opencode's lifetime from a single Onyx request, persist a stable opencode session ID in our DB, and rely on durable on-disk session state for crash recovery.

## Issues to Address

The current ACP integration spawns a fresh `opencode acp` process for every user message — by `kubectl exec` in production (`sandbox/kubernetes/internal/acp_exec_client.py`) and as a subprocess locally (`sandbox/local/agent_client.py`). This works but pays for that simplicity in five ways:

1. **Per-message process startup cost.** Each message pays for: pod exec/WebSocket setup → `opencode acp` cold start → ACP `initialize` handshake → `session/list` lookup on disk → `session/resume` (or `session/new`). The current code path is `KubernetesSandboxManager.send_message` (`kubernetes_sandbox_manager.py:1679`) → `_create_ephemeral_acp_client` (`:1643`) → `start` → `resume_or_create_session` (`acp_exec_client.py:511`). Even a "yes" response has ~hundreds of ms of overhead.

2. **Session lifetime is tied to a single HTTP turn.** If the user's SSE connection drops, `GeneratorExit` is caught at `kubernetes_sandbox_manager.py:1742-1761` and the opencode process is killed. There is no way for the user to reconnect and continue watching a running turn — they can only re-fetch persisted state up to the moment they disconnected. The agent's mid-flight tool call either completes silently or is lost.

3. **No supervisor for opencode.** If `opencode acp` crashes mid-turn, the consumer sees an `Error` event and the turn ends. There's no automatic restart, no health monitor, and (because the process is ephemeral) no notion of "the agent is up" outside the lifetime of one prompt.

4. **Disk-scan session discovery.** `resume_or_create_session` (`acp_exec_client.py:511-533`) lists sessions on disk per `cwd` and picks "the most recent" (`:489`). This is a heuristic to deal with multiple API server replicas sharing one pod (`_try_resume_existing_session`, `:468-509`). It works for the current single-turn model but doesn't generalize: there's no stable identifier we can pin to a `BuildSession` row.

5. **Cancellation is implicit.** There's no `POST /sessions/{id}/cancel` endpoint today. The only cancel path is the user closing their SSE stream, which triggers `GeneratorExit` and an internal `session/cancel` notification on the way down. Scheduled tasks (`scheduled_tasks/executor.py:341-353`) enforce a 30-min budget with the same disconnect-kills-the-process pattern.

Migrating to `opencode serve` collapses the per-message process lifecycle into a single per-sandbox HTTP server, which fixes 1–4 directly and gives us a clean place to wire up explicit cancel for 5.

## Important Notes

### opencode serve — what we get

From the public docs ([opencode.ai/docs/server](https://opencode.ai/docs/server/), [opencode.ai/docs/sdk](https://opencode.ai/docs/sdk/), and deepwiki for sst/opencode):

- **Command:** `opencode serve --hostname 127.0.0.1 --port 4096` (defaults). Headless, no TUI.
- **Surface:** OpenAPI 3.1 spec served live at `GET /doc`. Endpoints include `POST /session`, `GET /session/:id`, `DELETE /session/:id`, `GET /session/:id/message`, `POST /session/:id/message`, `POST /session/:id/prompt_async`, plus `session.abort`, `share/unshare`, and `revert/unrevert` via the SDK.
- **Streaming:** **Out-of-band**. `POST /session/:id/message` returns the *complete* assembled response when the turn finishes. Live deltas are broadcast on a separate SSE stream at `GET /event` (instance-wide). Clients must subscribe to `/event` and correlate by `sessionID`. This is intentional and not going to change ([issue #13416](https://github.com/anomalyco/opencode/issues/13416) closed "not planned").
- **Persistence:** SQLite (Drizzle, WAL mode, FKs) at `$XDG_DATA_HOME/opencode/opencode.db` for sessions/messages/parts/permissions, plus JSON blobs in `$XDG_DATA_HOME/opencode/storage/`. Survives process restart.
- **Auth:** HTTP Basic only, opt-in via `OPENCODE_SERVER_PASSWORD` env var (`OPENCODE_SERVER_USERNAME` optional). No tokens. Localhost-bound by default.
- **TS SDK:** `@opencode-ai/sdk` with `createOpencodeClient()` plus `event.subscribe()` as an async iterable over `/event`. No first-party Python SDK — generate one from `/doc` with `openapi-python-client`, or hand-write a thin wrapper.
- **Concurrency:** Designed for multiple concurrent clients. Single `opencode serve` process per data dir; do *not* run two pointed at the same `opencode.db`.

### Known opencode bugs we must design around

- **No SSE replay.** `/event` does not honor `Last-Event-ID` ([#25657](https://github.com/anomalyco/opencode/issues/25657)). On reconnect, we lose deltas from the disconnect window. **Mitigation:** on reconnect, call `GET /session/:id/message` to snapshot current state, then re-subscribe to `/event`. Persist deltas into our DB the moment we see them so the user-facing replay path stays in Onyx.
- **REST subagent flows can hang.** [#6573](https://github.com/anomalyco/opencode/issues/6573): when an agent spawns subagents via the Task tool, the REST path can stall with `session.status = busy` forever. **Mitigation:** enforce our existing `ACP_MESSAGE_TIMEOUT` (currently 900s, `configs.py:128`) as a wall clock; on timeout, call `POST /session/:id/abort` and surface an error event. Verify the subagent path explicitly in integration tests before turning on for production.
- **Heartbeat mismatch.** [#17769](https://github.com/anomalyco/opencode/issues/17769): server-side heartbeat (~30s) vs typical client expectation (15s) causes premature disconnects after laptop sleep. **Mitigation:** we already emit our own SSE keepalive every 15s (`SSE_KEEPALIVE_INTERVAL`, `configs.py:120`) to the *browser*. Between Onyx API server and `opencode serve`, use a long httpx timeout and tolerate `/event` reconnects.

### Existing scaffolding we get to keep

- **Sidecar daemon already runs persistently in the pod** on port 8731 (`sandbox/kubernetes/docker/sandbox_daemon/server.py`, started by `sidecar-entrypoint.sh`). Pattern proven: long-lived HTTP server inside the pod, Ed25519-signed requests from the API server, health checked by k8s. `opencode serve` slots into the same pattern in the `sandbox` container.
- **Snapshots already capture `.opencode-data`** (`sandbox_daemon/snapshot.py:60-63, 76`). Whatever storage opencode persists there will be carried by snapshots without code changes, modulo a sequencing fix during restore (see Risks).
- **The Dockerfile already installs opencode** (`Dockerfile:85-91`). Port 8081 is already declared `EXPOSE`d "for OpenCode ACP HTTP server" — re-purpose it for serve.
- **`SandboxManager.send_message` returns a `Generator[ACPEvent, …]`** (`sandbox/base.py:280-302`). Callers (`session/manager.py:_yield_acp_events`, `_stream_cli_agent_response`, `scheduled_tasks/executor.py`) and the SSE encoding to the browser stay unchanged as long as the new HTTP client yields the same ACP schema event types. The `acp.schema` Pydantic models are our internal protocol; we keep them.
- **`acp.schema` event types map cleanly** to opencode `message.part.updated` / `message.updated` / `permission.asked` events. The mapping table lives in §Implementation Strategy.

### Things that will need careful handling

- **One `opencode serve` per pod, never two.** With current ephemeral processes, accidentally running two at once would corrupt the on-disk session DB — exactly the reason the ephemeral pattern exists (`kubernetes_sandbox_manager.py:1687-1693`). With serve, the supervisor (a small wrapper in `entrypoint.sh`) is the *only* thing that can start opencode, and only ever runs one.
- **opencode `sessionID` vs Onyx `build_session_id`.** Today we treat the ACP session as ephemeral and rediscover it via `session/list` per cwd. With serve, we want a 1:1 mapping: persist `opencode_session_id` on the `BuildSession` row, populated on first message. This eliminates the "pick first session" heuristic and works correctly across API replicas.
- **Multi-replica still works trivially.** Both API replicas hit the same in-pod HTTP server. SQLite handles internal concurrency. There is no `session/list` race anymore. The `_try_resume_existing_session` logic gets deleted.
- **Local backend.** `LocalSandboxManager` keeps a `dict[(UUID, UUID), ACPAgentClient]` cache of subprocesses (`local_sandbox_manager.py:93`). Migrating to serve means one `opencode serve` subprocess per local sandbox dir (or one global serve with multiple sessions). Lower stakes — pick whichever is simpler for dev.

## Implementation Strategy

The transition is a transport swap behind `SandboxManager.send_message`. Everything above the sandbox manager (session manager, persistence, SSE encoding, approvals, interception, scheduled tasks, packet logger's ACP-event level) is untouched. Everything below the sandbox manager (pod spec, image, entrypoint, supervisor) changes.

### Target architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Pod: sandbox-{id}                                                │
│ shareProcessNamespace: false                                     │
│                                                                  │
│ ┌─────────────────────────────────┐ ┌─────────────────────────┐ │
│ │ Container: sandbox              │ │ Container: sidecar      │ │
│ │                                 │ │                         │ │
│ │  - supervisor (entrypoint.sh)   │ │  - daemon :8731         │ │
│ │     ├─ opencode serve :4096     │ │    push / snapshot      │ │
│ │     │   (restarts on exit)      │ │  (unchanged)            │ │
│ │     └─ Next.js dev servers      │ │                         │ │
│ │                                 │ │  IRSA → S3              │ │
│ │  ENV: OPENCODE_SERVER_PASSWORD  │ │                         │ │
│ │  ENV: XDG_DATA_HOME =           │ │                         │ │
│ │       /workspace/.opencode-data │ │                         │ │
│ └─────────────────────────────────┘ └─────────────────────────┘ │
│                                                                  │
│ Volumes: workspace (rw both), managed (rw sidecar, ro sandbox)   │
└──────────────────────────────────────────────────────────────────┘

api-server ── HTTP :4096 ── (kubectl port-forward via k8s API) ──► opencode serve
api-server ── HTTP :8731 ── (signed) ───────────────────────────► sidecar daemon
```

The API server reaches `opencode serve` over the cluster network. Options, in preference order:

1. **`ClusterIP` Service per pod** with selector `pod=sandbox-{id}` exposing port 4096. Simple, debuggable, requires one Service object per sandbox (manageable: we already create one Pod per sandbox).
2. **Port-forward via the k8s API** (analogous to `k8s_stream` exec). Avoids Service objects. Slightly more code in the HTTP client.
3. **Pod DNS / pod IP direct.** Workable since both run in the same namespace, no auth boundary. This is what the existing sidecar push daemon does (`kubernetes_sandbox_manager.py` resolves pod IP and POSTs to `:8731`). **Recommend reusing the same pattern.**

We will use option 3 — direct pod-IP HTTP. Same as the push daemon. Auth via `OPENCODE_SERVER_PASSWORD` so any in-cluster lateral movement can't drive the agent.

### New client: `OpencodeServeClient`

Replaces both `ACPExecClient` (k8s) and `ACPAgentClient` (local). Lives at `sandbox/opencode/serve_client.py` (the empty `opencode/` directory already exists at `sandbox/opencode/`).

Public surface mirrors the existing clients enough to keep the sandbox managers simple:

```
class OpencodeServeClient:
    def __init__(self, base_url: str, password: str, ...): ...

    def health_check(self) -> bool: ...

    def ensure_session(self, opencode_session_id: str | None, cwd: str) -> str:
        """Return existing session_id if alive; else create via POST /session."""

    def send_message(
        self,
        opencode_session_id: str,
        message: str,
        timeout: float = ACP_MESSAGE_TIMEOUT,
    ) -> Generator[ACPEvent, None, None]:
        """
        1. Open SSE subscription to GET /event (filtered/correlated by session_id).
        2. POST /session/:id/prompt_async (don't wait for full response inline).
        3. For each /event:
             - decode opencode event types
             - translate to our acp.schema event types (mapping below)
             - yield typed events to caller
           Yield PromptResponse when message.updated carries the terminal part
           OR when permission.asked arrives (consumer decides).
        4. On caller cancel / GeneratorExit, POST /session/:id/abort.
        """

    def abort(self, opencode_session_id: str) -> None: ...

    def list_messages(self, opencode_session_id: str) -> list[Message]:
        """Used on reconnect to fill the gap between disconnect and re-subscribe."""
```

Notes:

- **Subscribe-before-send.** Subscribe to `/event` *before* `POST /session/:id/prompt_async` so we don't drop the first events. This is critical because of the side-channel streaming model.
- **`prompt_async` over `message`.** `POST /session/:id/message` blocks until the turn finishes — we want streaming, so we fire `prompt_async` (returns 204) and consume `/event`. Completion is signalled by a terminal `message.updated` for the assistant turn.
- **Correlate by session_id.** `/event` is instance-wide; the same client may have multiple sessions open. Filter inside the generator.
- **Wall-clock timeout.** Reuse `ACP_MESSAGE_TIMEOUT` (`configs.py:128`); on timeout, call `abort` and yield `Error`. Same shape as today.
- **Reconnect inside `send_message`.** If `/event` drops mid-turn, call `list_messages` to fast-forward state, re-subscribe, and continue. This is new capability vs. the current ephemeral model.

### Event type mapping

| Onyx `acp.schema` event | Opencode event(s) on `/event` |
|---|---|
| `AgentMessageChunk` | `message.part.updated` where `part.type=text` and role=assistant |
| `AgentThoughtChunk` | `message.part.updated` where `part.type=reasoning` (or `thinking`, verify in `/doc`) |
| `ToolCallStart` | `message.part.updated` where `part.type=tool` and `state.status=running` (first sighting) |
| `ToolCallProgress` | `message.part.updated` for the same `part.id` with subsequent `state` |
| `AgentPlanUpdate` | (no direct equivalent — opencode tracks plan as session state, not deltas) |
| `CurrentModeUpdate` | (no direct equivalent — `mode` is on session record) |
| `PromptResponse` | terminal `message.updated` for the assistant turn (stop_reason on message) |
| `Error` | `session.error` or HTTP error response to `prompt_async` |
| `RequestPermissionRequest` | `permission.asked` (then `permission.replied` for the response) |

`AgentPlanUpdate` and `CurrentModeUpdate` are emitted only in V0 of the agent today and aren't load-bearing for any current consumer — confirm with a grep of consumers and either drop them or synthesize from `session.updated` if needed. The mapping must be verified against the live `/doc` before implementation; ship a small probe script (next to `local/try_agent_client.py`) that prints raw `/event` traffic during an exercised turn.

### Persistence model

Add one nullable column to `build_session`:

```
opencode_session_id: str | None
```

Populated by `OpencodeServeClient.ensure_session` on first message. After that, every subsequent message hits the same opencode session by ID — no disk scan, no `session/list` heuristic. Delete `_try_resume_existing_session` and `_list_sessions` from the old ACP client (they're not needed once we have a persisted mapping).

On `BuildSession` delete, call `DELETE /session/:id` to clean up opencode's state (the SQL cascade in opencode's DB also deletes child sessions and messages).

### Sandbox manager changes

`KubernetesSandboxManager.send_message` (`kubernetes_sandbox_manager.py:1679-1807`) shrinks dramatically:

```python
def send_message(self, sandbox_id, session_id, message):
    pod_ip = self._get_pod_ip(sandbox_id)
    client = OpencodeServeClient(
        base_url=f"http://{pod_ip}:{OPENCODE_SERVE_PORT}",
        password=self._get_serve_password(sandbox_id),
    )
    opencode_session_id = build_session_repo.get_opencode_session_id(session_id) \
        or client.ensure_session(None, cwd=f"/workspace/sessions/{session_id}")
    # If we just created it, persist back
    if not build_session_repo.has_opencode_session_id(session_id):
        build_session_repo.set_opencode_session_id(session_id, opencode_session_id)
    yield from client.send_message(opencode_session_id, message)
```

No more ephemeral process spawn. No more `kubectl exec` per message. No more `_create_ephemeral_acp_client`.

`LocalSandboxManager` follows the same pattern but with a local `opencode serve` subprocess (one per sandbox dir, managed by `process_manager.py`) instead of a pod-IP HTTP target.

### Pod / image changes

1. **Entrypoint becomes a supervisor.** `entrypoint.sh` in the `sandbox` container currently is a trivial sleep-loop (per `sidecar-reimplementation.md` Phase 3). Replace with a small supervisor that:
   - Sets `XDG_DATA_HOME=/workspace/.opencode-data` (so SQLite lives on the shared volume and survives container restart within the same pod, and is captured by snapshots).
   - Sets `OPENCODE_SERVER_PASSWORD=$ONYX_OPENCODE_SERVE_PASSWORD` (pod-unique secret, injected like `ONYX_PAT`).
   - Runs `opencode serve --hostname 0.0.0.0 --port 4096` in a loop with exponential backoff on exit. Logs stderr/stdout.
   - Optionally runs a tiny `/health` proxy if we don't want to expose `opencode serve`'s `GET /` directly for k8s probes.
2. **Pod spec.** Declare `containerPort: 4096` (`OPENCODE_SERVE_PORT`) in the `sandbox` container. Add a readiness probe on `GET /doc` (returns the spec quickly without authentication).
3. **Pre-flight on `setup_session_workspace`.** After workspace setup, call `OpencodeServeClient.health_check`; fail provisioning if not green.
4. **Dockerfile.** Pin the opencode version. `RUN curl -fsSL https://opencode.ai/install | bash` is currently unpinned (`Dockerfile:85-91`); add `OPENCODE_VERSION=…` so a new release can't quietly break the protocol. Reduce `EXPOSE 3000 8081 8731` to `EXPOSE 3000 4096 8731` (drop 8081, add 4096) — 8081 was speculative.

### Cancellation (small but real win)

Add `POST /sessions/{session_id}/cancel` to the Onyx API. Handler:

```python
client = OpencodeServeClient(...)
client.abort(opencode_session_id)
```

Frontend wires a "stop" button to this. Scheduled tasks call it on timeout instead of relying on `GeneratorExit` plumbing.

### Migration phases

**Phase 0 — probe.** Build a small script (`sandbox/opencode/try_serve_client.py`) that runs `opencode serve` locally, exercises every event type we care about, and dumps the `/event` payload. Use to lock the mapping in §"Event type mapping" before writing the production client.

**Phase 1 — client library.** Land `OpencodeServeClient` with full unit tests against a fake `opencode serve` (httpx mock + canned SSE). Do not call from sandbox managers yet. Add `OPENCODE_SERVE_PORT`, `OPENCODE_SERVER_PASSWORD_ENV`, `ACP_TRANSPORT={"acp","serve"}` configs.

**Phase 2 — local backend behind a flag.** Swap `LocalSandboxManager` to use serve when `ACP_TRANSPORT=serve`. Default off. Validate end-to-end on dev laptops.

**Phase 3 — image + pod spec changes.** Build a new sandbox image (`onyxdotapp/sandbox:v0.2.x`) with the supervisor entrypoint, pinned opencode version, port 4096 exposed, password env var. Roll out via the standard image bump.

**Phase 4 — k8s backend behind a flag.** Swap `KubernetesSandboxManager.send_message` to use serve when `ACP_TRANSPORT=serve`. Default off in prod, default on in staging. Add `opencode_session_id` migration.

**Phase 5 — cutover.** Flip default to `serve` in prod after one week of staging soak. Keep the ACP path callable for two weeks of safety net, then delete `acp_exec_client.py`, `agent_client.py` (except its docstring/example value), and the `_try_resume_existing_session` heuristic.

Each phase is independently revertable.

## Risks

- **Snapshot/restore sequencing with a live serve.** Today snapshots include `.opencode-data`, but the writer is short-lived (the ephemeral `opencode acp` exits after each message). With serve running continuously, a snapshot taken mid-turn could capture a half-written SQLite WAL. **Mitigation:** snapshot/restore go through the sidecar daemon already (`sandbox_daemon/snapshot.py`); have it `POST /session/:id/abort` for the session being snapshotted and wait for `session.status != busy` before tarring. On restore, the supervisor restarts `opencode serve` so it re-opens the freshly extracted DB.
- **`/event` reconnect gaps.** Mitigated by `list_messages` snapshot-and-resume, but adds complexity in `OpencodeServeClient.send_message`. Add a metric for "events recovered via gap fill" so we can see if it ever fires in prod.
- **Subagent / Task tool flakiness over REST** ([#6573](https://github.com/anomalyco/opencode/issues/6573)). Verify with an integration test that drives a Task-tool flow end-to-end before defaulting on in prod. If it reproduces, hold on Phase 5 and either contribute a fix upstream or gate Task-tool usage.
- **Auth bypass if password leaks.** `OPENCODE_SERVER_PASSWORD` lives in the sandbox container env. An agent that exfiltrates the env can drive itself, but it's already running inside its own sandbox — blast radius is the same as the agent calling its own tools. Document this; do not consider it a security boundary.
- **Single-process bottleneck.** All API replicas drive one in-pod `opencode serve`. opencode is designed for this (multi-client) but if turnaround latency degrades under load, fall back to per-session sub-processes via the SDK's session model. Not expected at our load.
- **Loss of `kubectl exec` debugging affordance.** Today engineers can run `kubectl exec ... opencode acp` manually to repro. With serve, debugging is `kubectl port-forward sandbox-… 4096:4096 && curl localhost:4096/doc`. Document in the runbook.

## Tests

Prefer external-dependency-unit and integration tests; opencode is not mockable in a meaningful sense at the protocol level.

**External-dependency-unit tests** (`backend/tests/external_dependency_unit/craft/`):

- `test_opencode_serve_client.py` — spin up a real `opencode serve` in a tmp data dir, exercise `ensure_session`, `send_message` (assert ordered ACP event sequence), `abort`, `list_messages`. Use a tiny stub model provider, or a no-tools prompt to keep deterministic.
- `test_opencode_serve_client_reconnect.py` — start a message, sever the `/event` stream mid-turn, verify the client snapshots via `list_messages` and resumes correctly.
- `test_opencode_serve_client_abort.py` — issue prompt, abort mid-stream, verify next prompt on same session starts cleanly.

**Integration tests** (`backend/tests/integration/tests/craft/`):

- `test_messages_api_with_serve.py` — variant of existing `test_messages_api.py` with `ACP_TRANSPORT=serve`; identical assertions on SSE event shape leaving the API server. Frontend invariant: nothing about the public event shape changes.
- `test_scheduled_tasks_serve.py` — drive a scheduled task to completion via serve; assert that approval-gating still pauses correctly and budget timeout still aborts.
- `test_subagent_task_tool.py` — explicitly drive a prompt that triggers the Task tool. Currently flaky upstream; this test is the gate on Phase 5.

**Playwright** (`web/tests/e2e/`):

- One full session: create build session → send 3 messages → reload page → assert message history and live deltas still arrive. Verifies reconnect path through the full stack.

**Unit tests** (`backend/tests/unit/`):

- `test_opencode_event_mapping.py` — given canned `/event` payloads, assert exact ACP-event translation. Cheap, fast, locks the wire contract.

## Out of scope

- Replacing `acp.schema` types with opencode-native types in the SSE wire to the browser. Doable later; not load-bearing for this migration. Frontend doesn't care which transport produced the events.
- Multi-tenancy of a single `opencode serve` across sandboxes. We continue to run one per pod.
- Sharing the opencode session DB across pod restarts in different pods (e.g. sandbox migration). Snapshot/restore already covers this; opencode reads SQLite on startup and is happy.
- Hardening the sidecar reimplementation against IRSA leakage. Tracked separately in `sidecar-reimplementation.md`.
