# Plan: Shared ACPExecClient base class for K8s + Docker

## Context

`backend/onyx/server/features/build/sandbox/kubernetes/internal/acp_exec_client.py`
(783 lines) and
`backend/onyx/server/features/build/sandbox/docker/internal/acp_exec_client.py`
(603 lines) are ~95% structurally identical. The ACP JSON-RPC protocol code,
state management, `send_message` loop, session lifecycle, and event
dispatch are byte-for-byte the same between them. The only real
divergence is the transport: K8s uses the `kubernetes-client`
WebSocket exec stream; Docker uses a raw multiplexed Docker exec socket.

Today, every fix or behavior change to the ACP protocol layer has to be
duplicated across two files. The current PR (docker-compose-2, #11222)
already had to land an `SSEKeepalive`-move fix and a `_recv_exact`
timeout fix; both would have been single-file changes against a shared
base. Extracting the shared protocol code into an `ACPExecClientBase`
abstract class reduces the long-term cost of every future ACP change
and shrinks the codebase by ~700 lines.

This is the natural follow-up to docker-compose-2 and lives on its own
PR (`docker-compose-3`) so the K8s code motion is reviewed
independently of the Docker functional work in the prior PR.

## Issues to Address

1. **Duplicated ACP protocol code across K8s and Docker exec clients.**
   The protocol-level methods (`_send_request`, `_send_notification`,
   `_wait_for_response`, `_initialize`, `_create_session`,
   `_list_sessions`, `_resume_session`, `_try_resume_existing_session`,
   `resume_or_create_session`, `send_message`,
   `_process_session_update`, `cancel`, `__enter__`, `__exit__`) are
   identical between the two clients except for transport details.

2. **Duplicated state management.** Both clients independently define
   `ACPSession`, `ACPClientState`, the `ACPEvent` union, the
   `DEFAULT_CLIENT_INFO` dict, `ACP_PROTOCOL_VERSION`, and the
   reader-thread + response-queue lifecycle.

3. **Future drift risk.** When K8s and Docker fix the ACP packet-loss
   issue logged in the previous PR (or any future protocol fix), it
   would have to land in two files without a base class.

## Important Notes

- The base class lives in a neutral location so neither backend imports
  the other: `backend/onyx/server/features/build/sandbox/acp/base.py`.
  This is a new top-level subdirectory under `sandbox/`.
- `SSEKeepalive` is already shared in `sandbox/base.py` from
  docker-compose-2's earlier fix. Leave it there; the new
  `ACPExecClientBase` imports it. (Don't move it again — both K8s and
  Docker exec clients already re-export it for back-compat with any
  external imports.)
- The K8s subclass's `health_check()` method (runs `echo ok` via a
  fresh exec) is K8s-specific and stays on the subclass. Docker has no
  equivalent and doesn't need one.
- `_get_k8s_client` (K8s-only) and `_recv_exact` / frame parser
  (Docker-only) stay on their respective subclasses.
- Pure code motion: no behavior change on either backend. Production
  K8s ACP path must remain byte-for-byte equivalent to its current
  behavior. Verify by reading the resulting K8s subclass + running the
  existing unit tests.
- The `logger` prefixes differ (`[ACP]` vs `[DOCKER-ACP]`) and the
  `packet_logger` `context=` argument differs (`"k8s"` vs `"docker"`).
  The base class takes a `log_prefix` and `log_context` (or wraps them
  into a single `transport_name` field that derives both) to preserve
  identical log output on each backend.

## Implementation Strategy

### New module: `backend/onyx/server/features/build/sandbox/acp/`

Two files:

- `__init__.py` (empty).
- `base.py`:
  - Module constants: `ACP_PROTOCOL_VERSION = 1`, `DEFAULT_CLIENT_INFO` (parametrize "name" via subclass override since K8s and Docker today report different client names — verify whether opencode actually uses these; if it ignores them, unify to a single value).
  - Dataclasses: `ACPSession`, `ACPClientState`.
  - `ACPEvent` type alias (the schema union).
  - `ACPExecClientBase(ABC)` with the shared protocol implementation.

### Abstract surface

Five abstract methods (minimum needed to cover the transport divergence):

```python
class ACPExecClientBase(ABC):
    transport_name: ClassVar[str]  # "k8s" or "docker" — drives log_prefix + packet_logger context

    @abstractmethod
    def _open_transport(self, cwd: str) -> None: ...

    @abstractmethod
    def _close_transport(self) -> None: ...

    @abstractmethod
    def _is_transport_open(self) -> bool: ...

    @abstractmethod
    def _write_line(self, line: str) -> None:
        """Write one already-newline-terminated JSON-RPC line to the transport."""

    @abstractmethod
    def _read_responses_loop(self) -> None:
        """Long-running reader. Pulls from the transport, parses JSON lines,
        calls self._enqueue_message(msg) for each. Respects self._stop_reader."""
```

### Shared lifecycle (on the base)

`start(cwd, timeout)`:
1. Call `self._open_transport(cwd)` (subclass-specific).
2. Clear `self._stop_reader`.
3. Spawn reader thread targeting `self._read_responses_loop`.
4. `time.sleep(0.5)` to let opencode boot.
5. Call `self._initialize(timeout)`.
6. On any exception, `self.stop()` then re-raise.

`stop()`:
1. Set `self._stop_reader`.
2. Call `self._close_transport()`.
3. Join reader thread (timeout=2s), null it out.
4. Reset `self._state = ACPClientState()`.

`_enqueue_message(msg)` (helper for subclass readers):
- Log via `packet_logger.log_jsonrpc_raw_message("IN", msg, context=self.transport_name)`.
- Put on `self._response_queue`.

`__enter__` / `__exit__` shared.

### Shared protocol methods (on the base)

These move verbatim from either current implementation, with two
mechanical substitutions:

- `self._ws_client.write_stdin(...)` and `self._socket.sendall(...)`
  → `self._write_line(...)`.
- `self._ws_client.is_open()` and `self._socket is None` checks
  → `self._is_transport_open()`.

Methods:
- `_get_next_id`
- `_send_request`
- `_send_notification`
- `_wait_for_response`
- `_initialize`
- `_create_session`
- `_list_sessions`
- `_resume_session`
- `_try_resume_existing_session`
- `resume_or_create_session`
- `send_message`
- `_process_session_update`
- `_send_error_response`
- `cancel`
- `is_running` (returns `self._is_transport_open()`)

Log prefixes use `self.transport_name`: `[%s-ACP]` uppercased, so K8s
sees `[K8S-ACP]` and Docker sees `[DOCKER-ACP]`. (Small visual change
from `[ACP]` → `[K8S-ACP]` — worth flagging in the PR description.)

### K8s subclass (in `kubernetes/internal/acp_exec_client.py`)

Drops to ~150 lines. Keeps:
- `__init__` taking `pod_name`, `namespace`, `container`,
  `client_info`, `client_capabilities`. Calls `super().__init__(...)`.
- `_get_k8s_client` (lazy K8s API client).
- `_open_transport`: builds the `XDG_DATA_HOME=... exec opencode acp
  --cwd ...` command, calls `k8s_stream(connect_get_namespaced_pod_exec, ...)`,
  stores `self._ws_client`.
- `_close_transport`: `self._ws_client.close()`, null it.
- `_is_transport_open`: `self._ws_client is not None and
  self._ws_client.is_open()`.
- `_write_line`: `self._ws_client.write_stdin(line)`.
- `_read_responses_loop`: the existing K8s reader (uses
  `ws_client.update`/`read_stdout`/`read_stderr`), with the body of the
  inner `try` block replaced by `self._enqueue_message(message)`.
- `health_check` (K8s-only, kept).
- `transport_name = "k8s"`.

### Docker subclass (in `docker/internal/acp_exec_client.py`)

Drops to ~120 lines. Keeps:
- `__init__` taking `docker_client`, `container_name`, `user`,
  `client_info`, `client_capabilities`. Calls `super().__init__(...)`.
- `_open_transport`: `exec_create + exec_start(socket=True)` →
  `_unwrap_socket` → set 0.5s socket timeout. Store `self._socket`.
- `_close_transport`: shutdown(RDWR) + close, null the socket.
- `_is_transport_open`: `self._socket is not None`.
- `_write_line`: `self._socket.sendall(line.encode("utf-8"))` with the
  existing `_socket_lock`.
- `_read_responses_loop`: the existing Docker reader (frame parser via
  `_recv_exact`), with the body replaced by `self._enqueue_message(message)`.
- `_recv_exact` (kept — Docker-specific).
- `transport_name = "docker"`.

The currently-shared `_FRAME_HEADER_BYTES`, `_FRAME_STDOUT`, `_FRAME_STDERR`
constants are already re-exported from `exec_helpers.py`; nothing to
move.

### Files to modify

- **New**:
  `backend/onyx/server/features/build/sandbox/acp/__init__.py`
  `backend/onyx/server/features/build/sandbox/acp/base.py`
- **Modified**:
  `backend/onyx/server/features/build/sandbox/kubernetes/internal/acp_exec_client.py`
  `backend/onyx/server/features/build/sandbox/docker/internal/acp_exec_client.py`
- **Possibly affected** (verify imports still resolve):
  `backend/onyx/server/features/build/session/manager.py` (imports
  `SSEKeepalive` from `sandbox.base` — unchanged).
  `backend/onyx/server/features/build/sandbox/docker/docker_sandbox_manager.py`
  (imports `DockerACPExecClient`, `ACPEvent` — both still exported from
  the same module).
  `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py`
  (imports `ACPExecClient`, `ACPEvent` — both still exported).

## Tests

This is pure code motion — no new behavior to test. Verification is:

- **Existing unit tests must still pass**, especially
  `backend/tests/unit/onyx/server/features/build/sandbox/test_docker_acp_exec_client.py`
  (which exercises Docker's `start` + initialize round-trip via a fake
  framed socket and asserts `is_running` flips correctly on `stop`).
- **K8s unit test sweep**: run anything under
  `backend/tests/unit/onyx/server/features/build/sandbox/` to confirm
  no K8s-specific assertions regress.
- **Ty + ruff**: the codebase's pre-commit hooks must pass cleanly on
  both subclasses and the base.
- **Manual smoke (optional but recommended given K8s code motion)**:
  run the Docker smoke script
  `backend/scripts/manual_test_docker_sandbox.py` to confirm `start`,
  `initialize`, and `stop` lifecycle still work end-to-end against a
  real Docker daemon. We don't have an equivalent K8s smoke script —
  rely on code review for the K8s side.

No new tests required. If desired, a small unit test for the base
class's `_send_request` / `_wait_for_response` against a fake
transport could be added, but it would duplicate the framing test that
`test_docker_acp_exec_client.py` already provides.

## PR Mechanics

- New branch stacked on `docker-compose-2` via
  `ez create docker-compose-3 --from docker-compose-2`.
- One commit: `refactor(craft): shared ACPExecClient base across K8s + Docker`.
- PR title should call out: "no behavior change; pure code motion".
- PR body should include the line-count delta (~1380 → ~870 across the
  three files) and an explicit callout that the K8s production path
  has been touched.

## Implementation Status (2026-05-20)

Landed as `d94321e924 refactor(craft): shared ACPExecClient base across K8s + Docker` on `docker-compose-3` (PR #11225, open).

### Actual line counts (vs. estimated)

| File | Plan estimate | Actual |
| --- | --- | --- |
| `sandbox/acp/base.py` (new) | — | 639 |
| `kubernetes/internal/acp_exec_client.py` | ~150 | 220 |
| `docker/internal/acp_exec_client.py` | ~120 | 237 |
| **Total across 3 files** | **~870** | **1096** |
| **Total before refactor (2 files)** | 1386 | 1386 |
| **Net reduction** | ~510 | ~290 |

The reduction was smaller than the plan estimated because more transport-adjacent helpers (frame parsing context, packet logging, reader-loop scaffolding) stayed on the subclasses than expected. Still a meaningful win — every future ACP protocol fix is now a one-file change.

### Divergences from the plan

- **Subclasses are larger than estimated.** Plan said ~150 (K8s) / ~120 (Docker); actual is 220 / 237. Reader loops and transport-open/close paths needed more subclass-specific scaffolding than the abstract surface anticipated.
- **`SSEKeepalive` stayed in `sandbox/base.py`** as the plan required — no second migration.
- **Log prefix change shipped.** `[ACP]` → `[K8S-ACP]` is live on the K8s path. Worth flagging in any review of K8s log diffs.
- **No new tests added.** As planned, the refactor relies on existing `test_docker_acp_exec_client.py` + ty/ruff + manual Docker smoke. Manual K8s smoke was not run; review-only verification.

### Still TODO

- Merge of `docker-compose-3` (#11225) once `docker-compose-2` (#11222) lands.
