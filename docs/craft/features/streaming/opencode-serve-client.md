# Design: `OpencodeServeClient`

## Context

Companion to [`docs/craft/opencode-serve-migration.md`](../opencode-serve-migration.md). The migration plan covers the *why* (transport-level fix for the ACP terminator-drop bug + four architectural wins), the pod-spec changes, persistence-model changes, and rollout phases. **This doc covers the implementation of the Phase-1 deliverable only: the in-process Python client (`OpencodeServeClient`) that replaces `ACPExecClient` / `DockerACPExecClient` behind `SandboxManager.send_message`.**

The public contract (`Generator[ACPEvent, None, None]` returned by `send_message`) is unchanged from the existing ACP clients. Callers (`session/manager.py`, `scheduled_tasks/executor.py`, SSE encoding to the browser, packet logger) require no changes.

File: `backend/onyx/server/features/build/sandbox/opencode/serve_client.py` (the empty `sandbox/opencode/` directory already exists).

## Scope

In scope:
- Class structure, method signatures, internal threading model, queue + correlation strategy.
- Event translation from opencode `/event` types to `acp.schema` event types.
- Reconnect / gap-fill on `/event` drops.
- Cancel / abort.
- Auth (`OPENCODE_SERVER_PASSWORD`).

Out of scope (covered in the migration plan):
- Pod spec, entrypoint supervisor, Dockerfile changes.
- `BuildSession.opencode_session_id` column and persistence.
- Wire-up to `KubernetesSandboxManager.send_message` / `DockerSandboxManager.send_message`.
- Phase-2/3/4/5 rollout machinery.

## Public surface

```python
class OpencodeServeClient:
    """Thin Python client over a single in-pod `opencode serve` instance.

    One client = one opencode HTTP target. Lifetime is per-call inside
    `SandboxManager.send_message`; the underlying serve process is
    long-lived (managed by the pod's entrypoint supervisor).
    """

    def __init__(
        self,
        base_url: str,                     # "http://10.0.0.42:4096"
        password: str | None,              # None in dev; required in cluster
        *,
        client_info: dict[str, Any] | None = None,
        timeouts: ClientTimeouts | None = None,
    ) -> None: ...

    # --- session lifecycle -------------------------------------------------

    def health_check(self) -> bool:
        """GET /doc with short timeout. Returns True iff 200."""

    def ensure_session(
        self,
        opencode_session_id: str | None,
        *,
        directory: str,
        title: str | None = None,
    ) -> str:
        """Return a known-good opencode session id.

        - If ``opencode_session_id`` is provided, ``GET /session/{id}`` to
          verify it still exists. Return it on 200, fall through on 404.
        - Otherwise ``POST /session`` to create one and return the new id.

        Idempotent. Safe to call from any API replica."""

    def delete_session(self, opencode_session_id: str, *, directory: str) -> bool:
        """Best-effort DELETE /session/{id}. Returns false on failure; Onyx
        session deletion must not depend on this cleanup succeeding."""

    # --- the load-bearing method ------------------------------------------

    def send_message(
        self,
        opencode_session_id: str,
        message: str,
        *,
        timeout: float = ACP_MESSAGE_TIMEOUT,
    ) -> Generator[ACPEvent, None, None]:
        """Send a prompt, stream ACP events, yield ``PromptResponse`` (or
        ``Error``) as the terminator.

        Internally:
          1. Open SSE subscription to ``GET /event``. Wait for the first
             ``server.connected`` event (or short timeout) to confirm.
          2. Optimistically buffer events arriving for THIS session id.
          3. ``POST /session/{id}/prompt_async`` (returns 204). Do NOT
             wait for the body — all turn state arrives via /event.
          4. For each event correlating to this session id:
               - translate to ``acp.schema`` type (see "Event translation")
               - yield to caller
               - on the primary terminator (``message.updated`` for the
                 assistant message with non-null ``info.time.completed``),
                 yield ``PromptResponse`` and return.
          5. On ``GeneratorExit`` (caller closed the stream): ``POST
             /session/{id}/abort``, then re-raise.
          6. On wall-clock timeout: ``POST /session/{id}/abort``, yield
             ``Error(code=-1, message="Timeout waiting for response")``,
             return.
          7. On ``/event`` disconnect mid-turn: enter the gap-fill reconnect
             path (see "Reconnect & gap-fill"). Never yield a partial event
             twice; never silently drop one.

        Yields ``SSEKeepalive`` markers when ``/event`` is idle for more
        than ``SSE_KEEPALIVE_INTERVAL`` seconds — same contract as the
        existing ACP clients, so the SSE encoder upstream needs no change.
        """

    # --- cancel from outside the generator --------------------------------

    def abort(self, opencode_session_id: str) -> None:
        """POST /session/{id}/abort. Safe to call concurrently with an
        in-flight send_message generator on the same session — opencode
        treats the inbound abort as a session-status flip; the generator
        sees the terminator on /event and yields a synthesized ``Error``."""

    # --- reconnect helper, exposed for tests ------------------------------

    def list_messages(self, opencode_session_id: str) -> list[Message]:
        """GET /session/{id}/message. Used internally on /event reconnect
        to fast-forward state; exported so tests can assert the gap-fill
        produces the same accumulator as the live stream."""
```

`ClientTimeouts` is a small dataclass with three named timeouts:
- `connect_timeout` (default 5s) — TCP/TLS handshake to serve
- `request_timeout` (default 30s) — per-request HTTP for non-streaming endpoints
- `event_read_timeout` (default 60s) — `/event` SSE idle timeout; client reconnects after this

## Internal architecture

### Threading model

`send_message` is a Python generator. Its caller (one of the sandbox managers, which the session manager iterates synchronously) consumes it on a single thread. But opencode's `/event` stream is push-based: a background reader is unavoidable.

```
┌─────────────────────────┐                ┌─────────────────────┐
│ caller thread           │                │ /event reader       │
│   for ev in send_msg(): │ <── ACPEvent ──│ thread (daemon)     │
│       yield ev          │     via Queue   │  - httpx.stream    │
│                         │                │  - parse SSE        │
│                         │                │  - translate +      │
│                         │                │    enqueue          │
└─────────────────────────┘                └─────────────────────┘
```

- One `queue.Queue[ACPEvent | _ReaderError | _ReaderEnded]` per `send_message` call.
- Reader thread is started inside `send_message` and torn down on exit (success, error, or `GeneratorExit`). It does not outlive a single call.
- Reader correlates events by `sessionID` before enqueueing — `/event` is instance-wide.
- Reader puts a sentinel (`_ReaderEnded(reason)`) on the queue when its SSE connection closes or when it sees a terminator and exits cleanly. **The caller-thread loop checks for this sentinel on every dequeue**, so a dead reader can never cause the caller to hang indefinitely. (This is the fix for "Bug A" in the prior packets-dropped investigation — applied here at the design level, never to be a regression target.)

### Event flow inside the reader thread

```
                                  ┌─────────────────────────────┐
GET /event ─── SSE chunks ──►    │ buffer until "\n\n"         │
                                  └──────────────┬──────────────┘
                                                 │  one event
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │ json.loads(data line)        │
                                  └──────────────┬───────────────┘
                                                 │
                            evt.properties.info.sessionID  ── filter ──┐
                                                 │                     │
                                                 ▼                     ▼
                                  ┌──────────────────────────────┐   drop
                                  │ translate (see below)        │
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │ queue.put(ACPEvent)          │
                                  └──────────────────────────────┘
```

### Why a reader thread, not asyncio

The existing `SandboxManager.send_message` contract is a synchronous generator and the callers (FastAPI sync endpoints, scheduled-task workers) are sync. Pulling asyncio into this path means painting every caller; not justified for one client. `httpx.stream` + a daemon thread is the same pattern the ACP clients use today.

## Event translation

A pure function (no I/O, no `self`) so it's trivially testable:

```python
def translate_opencode_event(
    raw: dict[str, Any],
    session_id: str,
    state: _TurnState,
) -> Iterable[ACPEvent]:
    """Translate one opencode /event payload into 0..N ACPEvents.

    Returns an iterable because a single opencode event can imply two
    ACP events (e.g. a `message.updated` with `time.completed` set both
    finalizes streaming AND emits PromptResponse). Pure — call it from
    tests with hand-rolled dicts."""
```

`_TurnState` is the per-turn accumulator the reader thread maintains (last seen part IDs, partial text buffers if needed for delta merging, tool-call ID → ToolCallStart emitted yes/no). It exists to deduplicate `ToolCallStart` (we emit it only on the first sighting per `part.id`) and to correlate `message.part.delta` to a known assistant text part.

### Mapping table (source of truth for the function)

| opencode event type | filter | emit |
|---|---|---|
| `server.connected` | always | nothing — just sets a "stream-ready" flag |
| `session.created` | match session_id | nothing |
| `session.next.agent.switched` | match | nothing |
| `session.next.model.switched` | match | nothing |
| `message.part.delta` | match, target part role=assistant, type=text | `AgentMessageChunk(content=TextContent(text=delta))` |
| `message.part.delta` | match, target part role=assistant, type=reasoning | `AgentThoughtChunk(content=TextContent(text=delta))` |
| `message.part.updated` | match, type=tool, status=pending, FIRST sighting of part.id | `ToolCallStart(...)` |
| `message.part.updated` | match, type=tool, subsequent | `ToolCallProgress(... status=running|completed)` |
| `message.part.updated` | type=text | nothing (token stream came on `delta`) |
| `message.updated` | match, role=assistant, time.completed non-null | yield buffered events, then `PromptResponse(stopReason=...)` |
| `session.idle` | match | backstop terminator: if PromptResponse not yet yielded, emit it now |
| `session.status` | match, status=idle | backstop terminator: same |
| `session.error` | match | `Error(code=..., message=...)` |
| `permission.asked` | match | **auto-allow** via `POST /session/.../permissions/{id}` body `{"response": "once"}`. Emit nothing to the consumer. Log WARN with permission/patterns + metric (`opencode_unexpected_permission_ask`). See §Decisions #1. |
| `permission.replied` | match | nothing (informational) |
| `server.heartbeat` | always | nothing (or pass through as `SSEKeepalive` to upper layers) |
| `session.diff`, `session.updated` (post-terminator) | match | nothing |
| anything else | — | log at DEBUG, ignore |

Backstops are **defense in depth against the ACP terminator-drop bug recurring at the serve layer**. The empirical data from Phase 0 says all three terminator signals fire reliably; the code emits `PromptResponse` on whichever arrives first and ignores the others.

### Tool-call content synthesis (translator logic)

The frontend's `parsePacket.ts` reads diff data from `content[].type==="diff"` and file content from `content[].type==="content"`. Opencode serve doesn't emit a `content` array on tool parts — only `state.input` / `state.output` / `state.metadata`. The translator synthesizes the `content` array so the frontend stays unchanged. Field-name mapping is locked from the test report:

**For `edit` tool** (`state.status` reaches `completed`):
```python
content = [{
    "type": "diff",
    "path": state.input["filePath"],
    "oldText": state.input["oldString"],
    "newText": state.input["newString"],
}]
```

**For `read` tool** (`state.status` reaches `completed`):
```python
content = [{
    "type": "content",
    "content": {"type": "text", "text": state.output},  # opencode returns line-numbered string
}]
# frontend's extractFileContent strips line numbers via /^\d+\| /gm regex — works as-is.
```

**For `bash` and `task` tools:** no `content` synthesis needed. The frontend reads `rawOutput.output` (after wrapping `state.output` string in `{output: state.output}` — see `raw_output` row in the field mapping below).

**`raw_input` / `raw_output` field-name mapping** (so the frontend's existing `getRawInput` / `getRawOutput` helpers work unchanged):

| ACP field | Opencode source | Translator action |
|---|---|---|
| `raw_input` | `state.input` (already camelCase like the frontend's `filePath`/`oldString`/etc. fallback chain) | pass through unchanged |
| `raw_output` | `state.output` (plain string or object) | wrap: `{"output": state.output}` if string; pass dict through if dict |

Tool-name → ACP `title` and `kind`: derive at the translator level using a small lookup matching the frontend's `NAME_MAP` and `TOOL_KIND_MAP`. No new state needed.

### Why the per-turn state object exists

Three things require state across events:

1. **`ToolCallStart` is "first sighting of part.id"** — opencode emits multiple `message.part.updated` for the same tool part as its `state.status` transitions. We need to know whether we've already yielded `ToolCallStart` for this part. A `set[str]` of seen tool-part-ids on the turn state suffices.
2. **Idempotent terminator** — once we yield `PromptResponse`, any subsequent terminator signal (one of the three backstops) is a no-op. A single bool on the turn state.
3. **Per-text-part accumulator for gap-fill** — `local_text: dict[str, str]` mapping `partID → cumulative text we've yielded`. Read by the gap-fill reconciliation on `message.part.updated`. See §Reconnect & gap-fill.

Anything not requiring cross-event correlation stays out of state.

## Reconnect & gap-fill

`/event` does **not** honor `Last-Event-ID` ([opencode #25657](https://github.com/anomalyco/opencode/issues/25657)). Plain TCP retry loses every event during the disconnect window.

The original plan used `GET /session/:id/message` as the snapshot source. Empirical testing (see [`../opencode-serve-test-report.md`](../opencode-serve-test-report.md) §Gap-fill) disproved that: `part.text` in the snapshot is **empty during streaming** and only populated after the turn terminator. So the snapshot is useless for mid-turn recovery.

The reliable reconcile point is the `message.part.updated` event itself. For each text part, opencode emits at least two of these on the live stream: once at part creation (empty `text`) and once at part finalization (`text` = full accumulated content). Plus any intermediate updates triggered by tool boundaries. Each carries cumulative `part.text`. If we missed deltas in a disconnect window, the next `message.part.updated` for that part will let us recover what we missed by comparing accumulated length.

### Algorithm

Inside the reader thread, keep a `local_text: dict[str, str]` mapping `partID → accumulated text`.

On every `message.part.delta` (`field == "text"`):
- `local_text[partID] += delta`
- Yield `AgentMessageChunk(text=delta)`.

On every `message.part.updated` (`type == "text"`):
- `expected = properties.part.text`
- `local = local_text.get(partID, "")`
- If `len(expected) > len(local)` — we missed deltas. Emit `AgentMessageChunk(text=expected[len(local):])` as a gap-fill chunk, then set `local_text[partID] = expected`.
- If `expected == local` — no-op (the steady-state case).
- If `len(expected) < len(local)` — log warning, leave `local` (shouldn't happen unless opencode rewinds; treat as data integrity issue).

On `httpx.stream` raise / connection end without server-side close:
- Don't snapshot `GET /session/{id}/message`. It won't help mid-turn.
- Backoff and reconnect to `/event` (1s, 2s, 4s; max 3 attempts).
- Wait for `server.connected`.
- The next `message.part.updated` for any in-flight part fills the gap automatically via the reconciliation above. No special "gap-fill mode" needed.

Edge case: **turn completed during the disconnect window.** No more events for this turn will arrive on the new stream. After `MAX_GAP_WAIT_SECONDS=10` of silence post-reconnect, fall back to `GET /session/{id}/message` (which *is* fully populated post-terminator), find the assistant message, and emit one synthesized `AgentMessageChunk` with whatever text we don't yet have, then yield `PromptResponse(stopReason=…)` from the snapshot's `info.finish`.

Edge case: **reconnect itself fails.** After 3 attempts, push `_ReaderError("event stream lost")` onto the queue and exit. The caller-thread loop catches the sentinel and yields `Error`.

Gap-fill logic lives in `_reconcile_text_part()` (per-event hook) and `_post_disconnect_snapshot()` (the rare post-terminator fallback). Unit-test the reconciliation in isolation with canned `(local, expected)` pairs — pure function.

## Cancel paths

Three distinct triggers, one mechanism (`POST /session/{id}/abort`):

1. **Caller closes the SSE stream → `GeneratorExit` inside `send_message`.** Wrap the main `yield` in a `try/except GeneratorExit:`; abort and re-raise.
2. **External `/cancel` API endpoint** (new in this migration). Calls `client.abort(session_id)` directly. The in-flight `send_message` generator sees `session.status` change and emits `Error` (or in opencode 1.15.7's behavior, just a synthesized backstop terminator — verify in Phase-2 test).
3. **Wall-clock timeout inside the generator.** Same code path: `abort`, then yield `Error(code=-1)`, return.

The current ACP path's reliance on `GeneratorExit` propagating into a `cancel()` call lives in the sandbox-manager layer; here, it moves inside `send_message`. That centralization means scheduled tasks no longer need their own `GeneratorExit` plumbing — they just call `abort` directly.

## Auth + config

Required env on the API server side:
- `OPENCODE_SERVE_PORT` (default `4096`)
- `OPENCODE_SERVER_PASSWORD_SOURCE` — where to read the per-pod password from. Two options, pick one:
  - From a Kubernetes Secret per pod (matches the existing `ONYX_PAT` pattern).
  - Derived deterministically from a cluster-wide secret + sandbox-id (cheaper; same security boundary since the pod env is the secret store either way).

The client takes `password` in its constructor — the *sandbox manager* is responsible for sourcing it. Keep `OpencodeServeClient` ignorant of where the password came from.

HTTP details:
- `Authorization: Basic ${base64(username:password)}` where `username` defaults to `"onyx"` (opencode accepts any non-empty username when password is set).
- `Accept: text/event-stream` on `/event`; `Accept: application/json` otherwise.
- `Content-Type: application/json` on POST/PATCH.

## Error surfacing

Two layers of error:

| Source | How the client surfaces it |
|---|---|
| Non-2xx from `POST /session/{id}/prompt_async` | `Error(code=http_status, message=body[:200])` yielded before terminator; reader thread shuts down. |
| `session.error` event on `/event` | `Error(code=-2, message=event.properties.message)` yielded; if the event also carries `info.time.completed`, treat as terminator. |
| Reader thread crash (httpx exception, JSON parse, etc.) | Synth `Error(code=-3, message="event stream error: {e}")` via `_ReaderError` sentinel. |
| Wall-clock timeout | `Error(code=-1, message="Timeout waiting for response")`. |
| Abort initiated by caller | No yield — `GeneratorExit` propagates after `POST /abort`. |

All error events also append the opencode `requestID` (if present in the event) to the message for cross-correlation with `opencode serve` logs.

## Testing

(See migration plan §Tests for the higher-level test plan; this section calls out what specifically exercises `OpencodeServeClient`.)

External-dependency-unit tests against a real `opencode serve` (subprocess in tmp dir; tests live in `backend/tests/external_dependency_unit/craft/`):

- `test_serve_client_basic.py` — `ensure_session`, three back-to-back prompts on one session, assert ordered events and exactly-one `PromptResponse` per turn.
- `test_serve_client_terminator_backstops.py` — drive a turn, then *delete* `message.updated` from the captured stream by injecting a proxy that drops it. Assert the client still terminates via `session.idle` and yields exactly one `PromptResponse`. (Phase 0 says this race is rare on serve, but the backstop is load-bearing — test it.)
- `test_serve_client_reconnect.py` — sever the `/event` proxy mid-turn, verify reconnect + gap-fill produce the same final accumulator as a non-severed run.
- `test_serve_client_abort.py` — issue prompt, abort 100ms in, verify generator yields `Error(-1)` (or `GeneratorExit` propagates, depending on cancel path) and the next prompt on the same session starts cleanly.
- `test_serve_client_tool_call.py` — drive a bash-tool prompt, assert `ToolCallStart` exactly once per tool part and `ToolCallProgress` with status cycling to `completed`.

Unit (pure function) tests in `backend/tests/unit/`:

- `test_translate_opencode_event.py` — canned dicts in, ACPEvents out. Asserts the full mapping table. Includes the `message.part.delta` vs `message.part.updated` distinction so future contributors can't regress that.
- `test_gap_fill_diff.py` — canned snapshot + canned "events already emitted" → assert synthesized events match what the live stream would have produced.

The unit tests are the load-bearing wire-contract lock. The external-dependency-unit tests are the integration safety net against opencode upgrades changing behavior.

## Code shape (skeleton)

```python
# backend/onyx/server/features/build/sandbox/opencode/serve_client.py
class OpencodeServeClient:
    def __init__(self, base_url, password, *, event_bus, client_info=None, timeouts=None):
        self._base_url = base_url.rstrip("/")
        self._auth = (
            httpx.BasicAuth("onyx", password) if password else None
        )
        self._timeouts = timeouts or ClientTimeouts()
        # Unary-only client. ``request_timeout`` bounds GET/POST against /session,
        # /prompt_async, /abort, etc. The long-lived ``/event`` SSE stream lives on
        # the shared per-pod PodEventBus, which owns its own httpx.stream with
        # ``event_read_timeout`` — that way the bus's per-frame idle timeout is
        # not capped by this client's unary read timeout.
        self._http = httpx.Client(
            base_url=self._base_url,
            auth=self._auth,
            timeout=httpx.Timeout(
                connect=self._timeouts.connect_timeout,
                read=self._timeouts.request_timeout,
                write=self._timeouts.request_timeout,
                pool=self._timeouts.connect_timeout,
            ),
        )

    def send_message(self, opencode_session_id, message, *, timeout=ACP_MESSAGE_TIMEOUT):
        q: queue.Queue[ACPEvent | _ReaderError | _ReaderEnded] = queue.Queue()
        stop = threading.Event()
        state = _TurnState(session_id=opencode_session_id)

        reader = threading.Thread(
            target=self._reader_loop, args=(opencode_session_id, q, stop, state),
            daemon=True,
        )
        reader.start()
        try:
            self._wait_for_stream_ready(q)
            self._post_prompt_async(opencode_session_id, message)
            yield from self._consume_until_terminator(q, state, timeout)
        except GeneratorExit:
            self._post_abort_quiet(opencode_session_id)
            raise
        finally:
            stop.set()
            reader.join(timeout=2.0)

    # ... _reader_loop, _consume_until_terminator, _gap_fill_from_snapshot, etc.
```

The `_reader_loop` and `_consume_until_terminator` together implement the dead-reader fail-fast: each `q.get(timeout=1.0)` in `_consume_until_terminator` checks for a `_ReaderEnded` sentinel; if it sees one before the terminator, it synthesizes an `Error` and returns. This is the structural fix that prevents the 15-minute hang from ever existing in this code path.

## Decisions (resolved 2026-05-22)

The earlier "open questions" section is now decided. Each decision is paired with the rationale and what code-level change it implies.

### 1. Permission flow — Path A (auto-handle, wire-format frozen)

`OpencodeServeClient` handles `permission.asked` internally. **It does not surface to the frontend**, and it does not yield a `RequestPermissionRequest` event to the consumer.

In production, Onyx-generated `opencode.json` already pins `*: allow` for every tool category we use (`sandbox/util/opencode_config.py:build_opencode_config`). Permission asks therefore should never fire. If one does, that means opencode has introduced a new permission category we haven't configured yet — treat it as a config-drift bug.

Behavior:
- **Default response:** auto-allow (`POST /session/.../permissions/{id}` body `{"response": "once"}`). Matches today's ACP-path behavior (opencode never asked because everything was wide open).
- **Telemetry:** log at WARN with the permission type and patterns, plus an ERROR-level metric increment. This gives us a loud signal that `opencode_config.py` needs updating.
- **Internal method:** `OpencodeServeClient._auto_respond_permission(permission_id)` — private; not part of the public API.

Path B (real user approvals UI) is a product feature, not a migration requirement. Defer.

### 2. `OPENCODE_SERVER_PASSWORD` source — per-pod K8s Secret

Each sandbox pod gets its own Secret containing a freshly generated password, mounted as `OPENCODE_SERVER_PASSWORD` env on the `sandbox` container. The sandbox manager generates the password and creates the Secret as part of `provision()`, alongside the existing `ONYX_PAT` Secret it already manages.

Why not a cluster-wide derived secret:
- Lateral movement: if an agent inside one sandbox can exfiltrate the cluster secret, it knows every sandbox's password. Per-pod containment limits the blast radius to one sandbox.
- We already do per-pod Secret provisioning for `ONYX_PAT`; reusing the pattern keeps the K8s manager symmetric.
- Operational overhead is ~10 lines of `kubernetes.client.V1Secret` creation, and the existing cleanup path (pod delete cascades to Secret) handles teardown.

`OpencodeServeClient`'s constructor accepts `password: str | None` (None for dev/local). Where the password comes from is the sandbox manager's problem, not the client's.

### 3. Multi-replica concurrency — no lock; handle 409 in client

Realistic concurrent paths are rare (two-tab user; scheduled task vs. user). Opencode's `session.status: busy` state strongly implies its `prompt_async` endpoint serializes per-session — it'll either queue the second prompt or reject with 409.

The client's `send_message` handles a non-2xx from `prompt_async` as a soft signal:
- `409 Conflict` (session busy) → wait for the next `session.idle` event on the `/event` stream (max 30s), then retry `prompt_async` once. After one retry, surface as `Error`.
- Any other non-2xx → yield `Error(code=status, message=body)` and end.

Add a counter metric `opencode_serve_busy_retries` so we can see if this ever fires in prod. If it does fire often, upgrade to a Redis lock — but defer until empirical signal demands it.

### 4. Token usage / cost capture — new `LLMFlow.OPENCODE_TURN` span

The terminator `message.updated` payload carries everything needed for cost observability:

```json
"cost": 0.00107985,
"tokens": {"total": ..., "input": ..., "output": ..., "reasoning": ..., "cache": {"read": ..., "write": ...}},
"modelID": "gpt-4o-mini",
"providerID": "openai"
```

Implementation:
1. Add `OPENCODE_TURN` to `LLMFlow` enum in `backend/onyx/tracing/flows.py`.
2. In `send_message`, open a generation span via `traced_llm_call(flow=LLMFlow.OPENCODE_TURN, model=…, provider=…)` at the start of the turn. `model`/`provider` come from `opencode.json` config (passed into the client by the sandbox manager) or are filled in from the first `session.next.model.switched` event.
3. On terminator, set span attributes `cost`, `tokens.input`, `tokens.output`, `tokens.total`, `tokens.reasoning`, `tokens.cache.read`, `tokens.cache.write` and close.
4. No span fields for per-token latency — opencode is making the underlying LLM call, not us. Aggregate cost/tokens is the observability we have.

This is a parallel work item: doesn't block the client library landing behind the `ACP_TRANSPORT=serve` flag, but must land before flipping the flag on in prod (otherwise we lose cost telemetry during the transition).

## Open questions remaining

None for the client library itself. The remaining decisions are out of scope (e.g., when to flip the flag, when to delete the ACP code per [`drop-acp-layer.md`](../drop-acp-layer.md)).
