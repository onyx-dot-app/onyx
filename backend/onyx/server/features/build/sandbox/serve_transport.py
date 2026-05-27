"""Shared opencode-serve transport plumbing.

Lives outside ``base.py`` so the abstract supertype doesn't have to pull in
concrete ``opencode.*`` modules — that would invert the dependency arrow
(abstract → concrete). Both ``SandboxManager`` and any future serve-using
class compose this mixin in.

What lives here:

- :class:`ServeConnectionInfo` — per-sandbox URL + password, cached at first
  use so hot paths (every prompt, every event-bus rebuild) don't re-hit
  ``docker inspect`` / ``kube get secret`` on every call.
- :class:`_ServeMixin` — the prompt slot, event-bus cache, readiness probe,
  serve send-message loop, and subscribe/list helpers. Subclasses provide
  the backend-specific ``_load_serve_connection_info``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import threading
import time
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from acp.schema import PromptResponse

from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import AGENT_TRANSPORT
from onyx.server.features.build.configs import AgentTransport
from onyx.server.features.build.configs import OPENCODE_SERVE_EVENT_READ_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVER_USERNAME
from onyx.server.features.build.sandbox.opencode.event_bus import BUS_CLOSED_SENTINEL
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus
from onyx.server.features.build.sandbox.opencode.serve_client import _TurnState
from onyx.server.features.build.sandbox.opencode.serve_client import OpencodeServeClient
from onyx.server.features.build.sandbox.opencode.serve_client import (
    translate_opencode_event,
)
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ACPEvent is a union type defined in both backend modules. Using Any here
# avoids a circular import; the real typing happens at the implementation.
ACPEvent = Any

# Hostname of the api_server process — surfaces in serve-transport logs so
# operators can tell which replica is driving a given prompt.
_API_SERVER_HOSTNAME = os.environ.get("HOSTNAME", "unknown")

# After the sandbox backend (pod/container) reports Ready, opencode-serve
# still has to finish its own boot (config parse, provider registry init,
# HTTP server bind on :4096). Empirically 1–3s warm, up to ~15s cold.
OPENCODE_SERVE_READY_TIMEOUT_SECONDS = 30
OPENCODE_SERVE_READY_POLL_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True)
class ServeConnectionInfo:
    """Per-sandbox opencode-serve connection details.

    Constant for the life of the container/pod (password is bound into env
    at startup; URL is derived from a stable container name / Service DNS).
    Cached by :class:`_ServeMixin` so we don't re-hit the backend control
    plane (docker inspect / k8s Secret read) on every prompt.
    """

    base_url: str
    # ``None`` for legacy sandboxes provisioned before HTTP Basic landed.
    # Bus then runs without auth — the warning is emitted at load time.
    password: str | None

    def auth(self) -> httpx.BasicAuth | None:
        if not self.password:
            return None
        return httpx.BasicAuth(OPENCODE_SERVER_USERNAME, self.password)


class _ServeMixin:
    """Shared opencode-serve plumbing for ``SandboxManager`` subclasses.

    Owns:

    - per-(sandbox, directory) :class:`PodEventBus` cache + tombstone
    - per-(sandbox, build_session) prompt-slot lock
    - per-sandbox :class:`ServeConnectionInfo` cache
    - the wait-for-ready probe, send-message loop, subscribe loop

    Subclasses implement :meth:`_load_serve_connection_info` (one call,
    cached forever) and supply their backend-specific abort/cleanup.
    """

    # State is initialized exactly once via ``_init_serve_state`` — called
    # from each subclass's ``_initialize`` under the singleton lock. The
    # body is also thread-safe so a contributor who forgets to call it
    # eagerly can't race two callers into creating two different lock
    # objects.
    _serve_state_init_lock = threading.Lock()

    def _init_serve_state(self) -> None:
        """Idempotent, thread-safe init for serve-transport state.

        Safe to call multiple times; second and subsequent calls are
        no-ops. The class-level lock guarantees two threads racing the
        first call cannot both initialize and end up with different
        ``_event_buses_lock`` objects.
        """
        if getattr(self, "_serve_state_initialized", False):
            return
        with _ServeMixin._serve_state_init_lock:
            if getattr(self, "_serve_state_initialized", False):
                return
            # Per-(sandbox, directory): opencode-serve scopes /event by ?directory=.
            self._event_buses: dict[tuple[UUID, str], PodEventBus] = {}
            # Tombstone: blocks late subscribe from racing a terminate.
            self._terminated_sandboxes: set[UUID] = set()
            self._event_buses_lock = threading.Lock()
            # Key on build_session_id, not opencode_session_id — see prompt_slot.
            self._prompt_locks: dict[tuple[UUID, UUID], threading.Lock] = {}
            self._prompt_locks_meta = threading.Lock()
            # Per-sandbox connection info cache; loaded on first use,
            # invalidated by terminate(). Keeps the hot path off docker
            # inspect / kube secret reads.
            self._serve_conn_info: dict[UUID, ServeConnectionInfo] = {}
            self._serve_conn_info_lock = threading.Lock()
            self._serve_state_initialized = True

    # ------------------------------------------------------------------
    # Backend hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def _load_serve_connection_info(
        self, sandbox_id: UUID
    ) -> ServeConnectionInfo | None:
        """Build the connection info for ``sandbox_id`` from the backend.

        Called at most once per sandbox per process; the result is cached
        until :meth:`_invalidate_serve_connection_info` (typically by
        ``terminate``). Return ``None`` if the sandbox doesn't exist.
        """
        ...

    # ------------------------------------------------------------------
    # ServeConnectionInfo cache
    # ------------------------------------------------------------------

    def _serve_connection_info(self, sandbox_id: UUID) -> ServeConnectionInfo:
        """Return cached info, loading on first use. Raises if the
        backend reports the sandbox is gone."""
        info = self._serve_conn_info.get(sandbox_id)
        if info is not None:
            return info
        with self._serve_conn_info_lock:
            info = self._serve_conn_info.get(sandbox_id)
            if info is not None:
                return info
            loaded = self._load_serve_connection_info(sandbox_id)
            if loaded is None:
                raise RuntimeError(
                    f"No serve connection info for sandbox {sandbox_id}; "
                    "container/pod is missing or hasn't been provisioned"
                )
            if loaded.password is None:
                logger.warning(
                    "[SANDBOX-SERVE] No opencode password for sandbox %s; "
                    "bus will run without auth (legacy sandbox — re-provision to fix)",
                    sandbox_id,
                )
            self._serve_conn_info[sandbox_id] = loaded
            return loaded

    def _invalidate_serve_connection_info(self, sandbox_id: UUID) -> None:
        """Drop cached info — call on terminate or when the backend
        reprovisions the sandbox under the same id."""
        with self._serve_conn_info_lock:
            self._serve_conn_info.pop(sandbox_id, None)

    # ------------------------------------------------------------------
    # Prompt slot
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def prompt_slot(
        self,
        sandbox_id: UUID,
        build_session_id: UUID,
    ) -> Generator[bool, None, None]:
        """Non-blocking try-acquire of a per-(sandbox, build_session) lock
        that serializes concurrent ``send_message`` calls on a build session.

        Yields ``True`` if the slot was acquired and the caller may proceed
        with the turn (lock is released on context exit), or ``False`` if a
        turn is already in flight on this build session and the caller
        should abort without side effects (no user_message persistence, no
        prompt POST).

        Why this exists: opencode-serve's ``prompt_async`` is fire-and-
        forget and not concurrent-safe — empirically, a second POST while
        a turn is in flight is silently dropped (no 409, no queue), and
        the second subscriber catches the *first* turn's terminator. Without
        serialization at this layer the user sees an empty response and a
        phantom user_message is persisted with no assistant reply.

        Keying on ``build_session_id`` (rather than ``opencode_session_id``)
        is deliberate:
          1. It's stable across opencode session id rotations triggered by
             the ``on_opencode_session_resolved`` callback — concurrent
             requests landing in the middle of a 404-then-mint sequence
             still contend on the same lock.
          2. It blocks first-turn races: two simultaneous prompts on a
             fresh build session (where ``opencode_session_id`` is NULL
             for both) both contend before each calls POST /session, so
             only one opencode session is ever created.
          3. It bounds the lock dict size to one entry per build session
             instead of one per (build_session × pod_restart_count).

        Under ``AGENT_TRANSPORT=acp`` (rollback path) this is a no-op
        (yields ``True``) — the per-message exec'd ``opencode acp``
        subprocess model has no shared state to serialize.
        """
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            yield True
            return

        key = (sandbox_id, build_session_id)
        with self._prompt_locks_meta:
            lock = self._prompt_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._prompt_locks[key] = lock

        acquired = lock.acquire(blocking=False)
        try:
            if not acquired:
                logger.warning(
                    "[SANDBOX-SERVE] prompt_slot: refused — concurrent send_message "
                    "on sandbox=%s build_session=%s",
                    sandbox_id,
                    build_session_id,
                )
            yield acquired
        finally:
            if acquired:
                lock.release()

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _session_directory(session_id: UUID) -> str:
        return f"/workspace/sessions/{session_id}"

    def ensure_opencode_session(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> str | None:
        """Return a stable opencode-serve session id for this build session.

        Used only when ``AGENT_TRANSPORT=serve``. The caller (session
        manager) persists the returned id on the ``BuildSession`` row so
        subsequent ``send_message`` calls can hit the same opencode
        session by id, eliminating the on-disk session/list heuristic
        the ACP path uses.

        Returns ``None`` under ACP — that transport has no notion of a
        persistent session id and doesn't need this preflight.

        Idempotent: calling twice for the same (sandbox, session) on serve
        returns the same id (delegated to ``OpencodeServeClient.ensure_session``).
        """
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            return None
        session_path = self._session_directory(session_id)
        logger.info(
            "[SESSION-LIFECYCLE] sandbox.ensure_opencode_session: build_session=%s "
            "sandbox=%s directory=%s (passing id=None, so client will POST /session)",
            session_id,
            sandbox_id,
            session_path,
        )
        with self._build_serve_client(sandbox_id, session_path) as client:
            return client.ensure_session(
                None,
                directory=session_path,
                title=f"build-session-{str(session_id)[:8]}",
            )

    def list_subagents(
        self,
        sandbox_id: UUID,
        parent_opencode_session_id: str,
    ) -> list[str]:
        """Child opencode session ids spawned under the parent. Empty
        under ACP (no shared event bus to track subagents)."""
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            return []
        # Walk existing buses only — don't spin up a reader thread just to list.
        with self._event_buses_lock:
            buses = [
                bus for (sid, _), bus in self._event_buses.items() if sid == sandbox_id
            ]
        for bus in buses:
            children = bus.list_children(parent_opencode_session_id)
            if children:
                return children
        return []

    # ------------------------------------------------------------------
    # Readiness probe
    # ------------------------------------------------------------------

    def _wait_for_opencode_serve_ready(
        self,
        sandbox_id: UUID,
        timeout: float = OPENCODE_SERVE_READY_TIMEOUT_SECONDS,
    ) -> bool:
        """Block until opencode-serve answers a health probe with 200.

        Backend readiness only proves the supervisor is up; opencode binds
        :4096 a few seconds later. Skipping this races the first prompt's
        bus subscribe → "stream did not become ready".
        """
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            return True

        info = self._serve_connection_info(sandbox_id)
        # One client across all polls — cheap (no real connection until first
        # request) and saves the connection-setup churn during the worst
        # phase of the probe (server actively refusing connections).
        with OpencodeServeClient(
            base_url=info.base_url, password=info.password, event_bus=None
        ) as client:
            deadline = time.time() + timeout
            last_err = "no probe completed"
            while time.time() < deadline:
                try:
                    if client.health_check():
                        logger.info(
                            "[SANDBOX-SERVE] opencode-serve ready for sandbox %s",
                            sandbox_id,
                        )
                        return True
                    last_err = "health_check returned False"
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
                time.sleep(OPENCODE_SERVE_READY_POLL_INTERVAL_SECONDS)
        logger.error(
            "[SANDBOX-SERVE] opencode-serve never became ready for sandbox %s "
            "after %.0fs (last error: %s)",
            sandbox_id,
            timeout,
            last_err,
        )
        return False

    # ------------------------------------------------------------------
    # Event bus / serve client
    # ------------------------------------------------------------------

    def _get_or_create_event_bus(self, sandbox_id: UUID, directory: str) -> PodEventBus:
        """Lazy per-(sandbox, directory) bus. Refuses to create for a terminated
        sandbox. Replaces self-closed buses so callers don't wedge on
        BUS_CLOSED_SENTINEL until restart."""
        key = (sandbox_id, directory)
        with self._event_buses_lock:
            bus = self._event_buses.get(key)
            if bus is not None and not bus.closed:
                return bus
            if bus is not None and bus.closed:
                logger.warning(
                    "[SANDBOX-SERVE] Replacing self-closed PodEventBus for "
                    "sandbox %s dir=%s (prior bus exhausted its reconnect budget)",
                    sandbox_id,
                    directory,
                )
                self._event_buses.pop(key, None)
            if sandbox_id in self._terminated_sandboxes:
                raise RuntimeError(
                    f"Sandbox {sandbox_id} has been terminated; refusing to "
                    "create a new event bus against its (deleted) backend"
                )
            info = self._serve_connection_info(sandbox_id)
            bus = PodEventBus(
                base_url=info.base_url,
                auth=info.auth(),
                directory=directory,
                event_read_timeout=OPENCODE_SERVE_EVENT_READ_TIMEOUT,
            )
            self._event_buses[key] = bus
            logger.info(
                "[SANDBOX-SERVE] Created PodEventBus for sandbox %s dir=%s",
                sandbox_id,
                directory,
            )
            return bus

    def _build_serve_client(
        self, sandbox_id: UUID, directory: str
    ) -> OpencodeServeClient:
        info = self._serve_connection_info(sandbox_id)
        bus = self._get_or_create_event_bus(sandbox_id, directory)
        return OpencodeServeClient(
            base_url=info.base_url,
            password=info.password,
            event_bus=bus,
        )

    # ------------------------------------------------------------------
    # Bus cleanup (called from terminate / cleanup_session_workspace)
    # ------------------------------------------------------------------

    def _close_session_buses(self, sandbox_id: UUID, session_id: UUID) -> None:
        """Pop and close the per-(sandbox, session) event bus.

        Call from each backend's ``cleanup_session_workspace`` — otherwise
        the bus (and its reader thread + httpx connection) survives
        session deletion and leaks until the api_server restarts.
        """
        directory = self._session_directory(session_id)
        with self._event_buses_lock:
            bus = self._event_buses.pop((sandbox_id, directory), None)
        if bus is None:
            return
        try:
            bus.close()
        except Exception:
            logger.exception(
                "[SANDBOX-SERVE] PodEventBus close failed for sandbox=%s session=%s",
                sandbox_id,
                session_id,
            )

    def _close_all_sandbox_buses(self, sandbox_id: UUID) -> None:
        """Pop every bus for ``sandbox_id``, set the tombstone, and close
        them. Call from each backend's ``terminate`` before destroying the
        container/pod so late subscribes can't race a fresh bus in."""
        with self._event_buses_lock:
            self._terminated_sandboxes.add(sandbox_id)
            doomed_keys = [k for k in self._event_buses if k[0] == sandbox_id]
            doomed_buses = [self._event_buses.pop(k) for k in doomed_keys]
        for bus in doomed_buses:
            try:
                bus.close()
            except Exception:
                logger.exception(
                    "[SANDBOX-SERVE] PodEventBus close failed during terminate for %s",
                    sandbox_id,
                )
        self._invalidate_serve_connection_info(sandbox_id)

    # ------------------------------------------------------------------
    # Send message via serve
    # ------------------------------------------------------------------

    def _send_message_via_serve(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
        opencode_session_id: str | None,
        agent_provider: str | None,
        agent_model: str | None,
        *,
        on_opencode_session_resolved: Callable[[str], None] | None = None,
    ) -> Generator[ACPEvent, None, None]:
        """Stream ACP events via the in-sandbox ``opencode serve``. Callers
        should preflight ``opencode_session_id`` with
        :meth:`ensure_opencode_session` to avoid one orphan session per turn.
        """
        packet_logger = get_packet_logger()
        session_path = self._session_directory(session_id)
        client = self._build_serve_client(sandbox_id, session_path)
        try:
            logger.info(
                "[SESSION-LIFECYCLE] _send_message_via_serve: build_session=%s "
                "caller-supplied opencode_session_id=%s",
                session_id,
                opencode_session_id,
            )
            resolved_session_id = client.ensure_session(
                opencode_session_id,
                directory=session_path,
                title=f"build-session-{str(session_id)[:8]}",
            )
            if resolved_session_id != opencode_session_id:
                # Notify caller so they persist the new id — without this we
                # orphan one opencode session per turn (lose conversation context).
                if opencode_session_id is not None:
                    logger.warning(
                        "[SANDBOX-SERVE] persisted opencode_session_id %s was "
                        "invalid; replaced with %s for session=%s",
                        opencode_session_id,
                        resolved_session_id,
                        session_id,
                    )
                if on_opencode_session_resolved is not None:
                    on_opencode_session_resolved(resolved_session_id)

            logger.info(
                "[SANDBOX-SERVE] Sending message: session=%s opencode_session=%s api_pod=%s",
                session_id,
                resolved_session_id,
                _API_SERVER_HOSTNAME,
            )
            packet_logger.log_session_start(session_id, sandbox_id, message)

            events_count = 0
            got_prompt_response = False
            try:
                for event in client.send_message(
                    resolved_session_id,
                    message,
                    directory=session_path,
                    model_provider=agent_provider,
                    model_id=agent_model,
                ):
                    events_count += 1
                    if isinstance(event, PromptResponse):
                        got_prompt_response = True
                    yield event

                logger.info(
                    "[SANDBOX-SERVE] send_message completed: session=%s events=%s got_prompt_response=%s",
                    session_id,
                    events_count,
                    got_prompt_response,
                )
                packet_logger.log_session_end(
                    session_id, success=True, events_count=events_count
                )
            except GeneratorExit:
                self._abort_and_log_turn_failure(
                    client=client,
                    session_id=session_id,
                    resolved_session_id=resolved_session_id,
                    session_path=session_path,
                    events_count=events_count,
                    packet_logger=packet_logger,
                    error="GeneratorExit",
                    log_level=logging.WARNING,
                )
                raise
            except Exception as e:
                self._abort_and_log_turn_failure(
                    client=client,
                    session_id=session_id,
                    resolved_session_id=resolved_session_id,
                    session_path=session_path,
                    events_count=events_count,
                    packet_logger=packet_logger,
                    error=f"Exception: {e}",
                    log_level=logging.ERROR,
                )
                raise
        finally:
            client.close()

    def _abort_and_log_turn_failure(
        self,
        *,
        client: OpencodeServeClient,
        session_id: UUID,
        resolved_session_id: str,
        session_path: str,
        events_count: int,
        packet_logger: Any,
        error: str,
        log_level: int,
    ) -> None:
        """Best-effort abort + structured log on a failed turn. Used by
        both GeneratorExit and Exception legs of the send-message loop.
        Swallowing the abort failure is intentional — we're already in an
        error path."""
        logger.log(
            log_level,
            "[SANDBOX-SERVE] turn failed: session=%s events=%s error=%s — sending abort",
            session_id,
            events_count,
            error,
        )
        try:
            client.abort(resolved_session_id, directory=session_path)
        except Exception as abort_err:
            logger.warning(
                "[SANDBOX-SERVE] abort failed during turn cleanup: %s", abort_err
            )
        packet_logger.log_session_end(
            session_id,
            success=False,
            error=error,
            events_count=events_count,
        )

    # ------------------------------------------------------------------
    # Subscribe stream (used by session manager for reattach/resume)
    # ------------------------------------------------------------------

    def subscribe_to_opencode_session(
        self,
        sandbox_id: UUID,
        opencode_session_id: str,
        *,
        directory: str,
        keepalive_seconds: float = 15.0,
    ) -> Generator[ACPEvent, None, None]:
        """Stream translated ACP events for an opencode session. Caller closes
        via ``GeneratorExit``. ``directory`` is required: opencode-serve scopes
        its session store per-directory, so the hydrate REST call needs it.
        """
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            return
        bus = self._get_or_create_event_bus(sandbox_id, directory)
        state = _TurnState(session_id=opencode_session_id)
        client = self._build_serve_client(sandbox_id, directory)

        def fetch_message(mid: str) -> dict[str, Any] | None:
            return client.get_message(opencode_session_id, mid, directory=directory)

        sub = bus.subscribe(opencode_session_id)
        try:
            last_event = time.monotonic()
            while True:
                try:
                    raw = sub.queue.get(timeout=1.0)
                except queue.Empty:
                    if time.monotonic() - last_event >= keepalive_seconds:
                        yield SSEKeepalive()
                        last_event = time.monotonic()
                    continue
                if raw is BUS_CLOSED_SENTINEL:
                    return
                last_event = time.monotonic()
                if raw.get("type") == "server.connected":
                    continue
                for acp_event in translate_opencode_event(
                    raw, state, fetch_message=fetch_message
                ):
                    yield acp_event
        finally:
            # Close client first so a flaky bus.unsubscribe doesn't leak the
            # connection pool. Both calls are best-effort here.
            try:
                client.close()
            except Exception:
                logger.exception(
                    "[SANDBOX-SERVE] client close failed in subscribe teardown"
                )
            try:
                bus.unsubscribe(sub)
            except Exception:
                logger.exception(
                    "[SANDBOX-SERVE] bus unsubscribe failed in subscribe teardown"
                )
