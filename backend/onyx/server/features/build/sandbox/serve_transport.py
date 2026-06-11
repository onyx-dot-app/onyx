"""Shared opencode-serve transport plumbing.

Lives outside ``base.py`` so the abstract supertype doesn't import concrete
``opencode.*`` modules (would invert the dependency arrow). ``SandboxManager``
composes ``_ServeMixin`` in.
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

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.features.build.configs import OPENCODE_SERVE_EVENT_READ_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVER_USERNAME
from onyx.server.features.build.configs import SANDBOX_TURN_TIMEOUT_SECONDS
from onyx.server.features.build.db.sandbox import get_sandbox_by_id
from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.sandbox.event_schema import AgentThoughtChunk
from onyx.server.features.build.sandbox.event_schema import PromptResponse
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

SandboxEvent = Any

# Tags serve-transport logs with the api_server replica handling the prompt.
_API_SERVER_HOSTNAME = os.environ.get("HOSTNAME", "unknown")

# opencode-serve boot lags backend Ready by ~1–3s warm, up to ~15s cold.
OPENCODE_SERVE_READY_TIMEOUT_SECONDS = 30
OPENCODE_SERVE_READY_POLL_INTERVAL_SECONDS = 0.25

# How long a new turn waits for the previous turn's slot before giving up.
PROMPT_SLOT_ACQUIRE_TIMEOUT_SECONDS = 10.0

# Live attach streams are UI-facing. Coalesce adjacent text deltas just long
# enough to avoid one React update per tiny opencode token burst, while keeping
# control packets and final/error packets effectively immediate.
LIVE_TEXT_COALESCE_SECONDS = 0.04


@dataclass(frozen=True)
class ServeConnectionInfo:
    """Per-sandbox opencode-serve URL + Basic-auth password. Constant for
    the life of the container/pod; cached by ``_ServeMixin``."""

    base_url: str
    # ``None`` for legacy sandboxes — bus then runs without auth.
    password: str | None

    def auth(self) -> httpx.BasicAuth | None:
        if not self.password:
            return None
        return httpx.BasicAuth(OPENCODE_SERVER_USERNAME, self.password)


class _ServeMixin:
    """Shared opencode-serve plumbing for ``SandboxManager`` subclasses.

    Subclasses implement :meth:`_load_serve_connection_info`; the mixin
    handles caching, the prompt slot, the event-bus map + tombstone, the
    readiness probe, the send-message loop, and the subscribe stream.
    """

    # Class-level so racing first-callers across instances can't both
    # initialize and end up with different ``_event_buses_lock`` objects.
    _serve_state_init_lock = threading.Lock()

    def _init_serve_state(self) -> None:
        """Idempotent, thread-safe init for serve-transport state."""
        if getattr(self, "_serve_state_initialized", False):
            return
        with _ServeMixin._serve_state_init_lock:
            if getattr(self, "_serve_state_initialized", False):
                return
            # opencode-serve scopes /event by ``?directory=``, so one bus per session dir.
            self._event_buses: dict[tuple[UUID, str], PodEventBus] = {}
            # Tombstone: blocks late subscribe from racing a terminate.
            self._terminated_sandboxes: set[UUID] = set()
            self._event_buses_lock = threading.Lock()
            self._serve_conn_info: dict[UUID, ServeConnectionInfo] = {}
            self._serve_conn_info_lock = threading.Lock()
            self._serve_state_initialized = True

    @abstractmethod
    def _load_serve_connection_info(
        self, sandbox_id: UUID
    ) -> ServeConnectionInfo | None:
        """Build connection info from the backend. Called once per sandbox;
        cached until ``_invalidate_serve_connection_info``. Return ``None``
        if the sandbox doesn't exist."""
        ...

    def _serve_connection_info(self, sandbox_id: UUID) -> ServeConnectionInfo:
        """Cached getter; loads on first use, raises if backend reports gone."""
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
        """Drop cached info; call on terminate / re-provision."""
        with self._serve_conn_info_lock:
            self._serve_conn_info.pop(sandbox_id, None)

    def _reload_serve_connection_info(self, sandbox_id: UUID) -> ServeConnectionInfo:
        """Drop the local cache and reload from the source of truth. The 401
        self-heal path: a peer api_server pod re-provisioned the sandbox and
        rotated the password, so local invalidation alone never reaches us."""
        self._invalidate_serve_connection_info(sandbox_id)
        return self._serve_connection_info(sandbox_id)

    def _serve_health_check_base_url(self, sandbox_id: UUID) -> str | None:  # noqa: ARG002
        """Override to probe a different URL during the readiness wait than the
        persistent ``base_url``. Default ``None`` → use ``base_url``."""
        return None

    @contextlib.contextmanager
    def prompt_slot(
        self,
        sandbox_id: UUID,
        build_session_id: UUID,
    ) -> Generator[bool, None, None]:
        """Serialize turns for a build session across replicas via the cache.

        opencode-serve's ``prompt_async`` isn't concurrent-safe, so a second
        in-flight POST corrupts session state. Yields False if a turn is
        already in flight (caller aborts without side effects); fails open if
        the cache is down. Auto-expires after a turn's max length. Keyed on
        ``build_session_id``, which (unlike the opencode id) is stable per turn.
        """
        # Tenant isolation is handled by the cache backend's key-prefixing.
        try:
            lock = get_cache_backend().lock(
                f"buildpromptslot_{sandbox_id}_{build_session_id}",
                timeout=SANDBOX_TURN_TIMEOUT_SECONDS,
            )
            acquired = lock.acquire(
                blocking=True, blocking_timeout=PROMPT_SLOT_ACQUIRE_TIMEOUT_SECONDS
            )
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning(
                "[SANDBOX-SERVE] prompt_slot: cache unreachable (%s) — failing open "
                "on sandbox=%s build_session=%s",
                e,
                sandbox_id,
                build_session_id,
            )
            yield True
            return

        try:
            if not acquired:
                logger.warning(
                    "[SANDBOX-SERVE] prompt_slot: refused — concurrent turn in flight "
                    "for sandbox=%s build_session=%s",
                    sandbox_id,
                    build_session_id,
                )
            yield acquired
        finally:
            if acquired:
                try:
                    lock.release()
                except CACHE_TRANSIENT_ERRORS as e:
                    logger.warning(
                        "[SANDBOX-SERVE] prompt_slot: lock release failed (%s) on "
                        "sandbox=%s build_session=%s — relying on TTL",
                        e,
                        sandbox_id,
                        build_session_id,
                    )

    @staticmethod
    def _session_directory(session_id: UUID) -> str:
        return f"/workspace/sessions/{session_id}"

    def ensure_opencode_session(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        opencode_session_id: str | None = None,
    ) -> str | None:
        """Idempotent preflight to mint (or look up) the opencode-serve
        session id for this build session. Caller persists it so later
        turns hit the same session by id."""
        session_path = self._session_directory(session_id)
        logger.info(
            "[SESSION-LIFECYCLE] sandbox.ensure_opencode_session: build_session=%s "
            "sandbox=%s directory=%s caller-supplied opencode_session_id=%s",
            session_id,
            sandbox_id,
            session_path,
            opencode_session_id,
        )
        with self._build_serve_client(
            sandbox_id,
            session_path,
            with_event_bus=False,
        ) as client:
            return client.ensure_session(
                opencode_session_id,
                directory=session_path,
                title=f"build-session-{str(session_id)[:8]}",
            )

    def list_subagents(
        self,
        sandbox_id: UUID,
        parent_opencode_session_id: str,
    ) -> list[str]:
        """Child opencode session ids spawned under the parent."""
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

    def _wait_for_opencode_serve_ready(
        self,
        sandbox_id: UUID,
        timeout: float = OPENCODE_SERVE_READY_TIMEOUT_SECONDS,
    ) -> bool:
        """Block until opencode-serve answers ``GET /doc`` with 200 (opencode
        binds :4096 a few seconds after the pod is Ready). Probes the Service
        ``base_url`` first, then the pod-IP health-check URL; succeeds as soon
        as either answers.

        On a 401 the cached password is stale (pod re-provisioned with a fresh
        Secret); reload it and rebuild the probe clients once. Provision-time
        counterpart to the per-request heal in ``_request`` /
        ``PodEventBus._refresh_auth_on_401``, which run only after readiness."""
        info = self._serve_connection_info(sandbox_id)

        def _build_clients(
            conn: ServeConnectionInfo,
        ) -> list[tuple[str, OpencodeServeClient]]:
            urls: list[str] = []
            for url in (conn.base_url, self._serve_health_check_base_url(sandbox_id)):
                if url is not None and url not in urls:
                    urls.append(url)
            return [
                (
                    url,
                    OpencodeServeClient(
                        base_url=url, password=conn.password, event_bus=None
                    ),
                )
                for url in urls
            ]

        clients = _build_clients(info)
        password_reset_done = False
        try:
            deadline = time.time() + timeout
            last_err = "no probe completed"
            while time.time() < deadline:
                for url, client in clients:
                    try:
                        status = client.health_check_status()
                        if status == 200:
                            logger.info(
                                "[SANDBOX-SERVE] opencode-serve ready for sandbox %s "
                                "via %s",
                                sandbox_id,
                                url,
                            )
                            return True
                        if status == 401 and not password_reset_done:
                            password_reset_done = True
                            refreshed = self._reload_serve_connection_info(sandbox_id)
                            if refreshed.password != info.password:
                                logger.warning(
                                    "[SANDBOX-SERVE] opencode-serve returned 401 for "
                                    "sandbox %s; reloaded password and retrying probe "
                                    "with the current credentials",
                                    sandbox_id,
                                )
                                info = refreshed
                                for _, c in clients:
                                    c.close()
                                clients = _build_clients(info)
                                break
                        last_err = f"health_check returned status={status} for {url}"
                    except Exception as e:
                        last_err = f"{url}: {type(e).__name__}: {e}"
                time.sleep(OPENCODE_SERVE_READY_POLL_INTERVAL_SECONDS)
        finally:
            for _, client in clients:
                client.close()
        logger.error(
            "[SANDBOX-SERVE] opencode-serve never became ready for sandbox %s "
            "after %.0fs (last error: %s)",
            sandbox_id,
            timeout,
            last_err,
        )
        return False

    def _get_or_create_event_bus(self, sandbox_id: UUID, directory: str) -> PodEventBus:
        """Lazy per-(sandbox, directory) bus. Refuses to create for a sandbox
        with no live backend pod (terminated / failed / sleeping); replaces
        self-closed buses so callers don't wedge on BUS_CLOSED_SENTINEL until
        restart."""
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
            with get_session_with_current_tenant() as db_session:
                sandbox = get_sandbox_by_id(db_session, sandbox_id)
            if sandbox is not None and (
                sandbox.status.is_terminal() or sandbox.status.is_sleeping()
            ):
                raise RuntimeError(
                    f"Sandbox {sandbox_id} is {sandbox.status.value} (no live "
                    "backend per DB); refusing to create a new event bus "
                    "against its (deleted) backend"
                )
            info = self._serve_connection_info(sandbox_id)
            bus = PodEventBus(
                base_url=info.base_url,
                auth=info.auth(),
                directory=directory,
                event_read_timeout=OPENCODE_SERVE_EVENT_READ_TIMEOUT,
                # Self-heal a 401 mid-stream (peer pod rotated the password).
                reload_auth=lambda: self._reload_serve_connection_info(
                    sandbox_id
                ).auth(),
            )
            self._event_buses[key] = bus
            logger.info(
                "[SANDBOX-SERVE] Created PodEventBus for sandbox %s dir=%s",
                sandbox_id,
                directory,
            )
            return bus

    def _build_serve_client(
        self,
        sandbox_id: UUID,
        directory: str,
        *,
        with_event_bus: bool = True,
    ) -> OpencodeServeClient:
        info = self._serve_connection_info(sandbox_id)
        bus = (
            self._get_or_create_event_bus(sandbox_id, directory)
            if with_event_bus
            else None
        )
        return OpencodeServeClient(
            base_url=info.base_url,
            password=info.password,
            event_bus=bus,
            # Self-heal a 401 on any unary call (peer pod rotated the password).
            reload_password=lambda: self._reload_serve_connection_info(
                sandbox_id
            ).password,
        )

    def _close_session_buses(self, sandbox_id: UUID, session_id: UUID) -> None:
        """Release the per-(sandbox, session) bus. Call from
        ``cleanup_session_workspace`` — without this the reader thread +
        httpx connection survive session deletion."""
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
        """Tombstone + pop + close every bus for ``sandbox_id``. Call from
        ``terminate`` before destroying the container/pod so late subscribes
        can't race a fresh bus in."""
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
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        """Stream sandbox events via the in-sandbox ``opencode serve``. Preflight
        ``opencode_session_id`` via :meth:`ensure_opencode_session` to avoid
        one orphan session per turn."""
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
                # Caller must persist the new id or we orphan one opencode
                # session per turn and lose conversation context.
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

            events_count = 0
            got_prompt_response = False
            try:
                for event in client.send_message(
                    resolved_session_id,
                    message,
                    directory=session_path,
                    model_provider=agent_provider,
                    model_id=agent_model,
                    should_interrupt=should_interrupt,
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
            except GeneratorExit:
                self._abort_and_log_turn_failure(
                    client=client,
                    session_id=session_id,
                    resolved_session_id=resolved_session_id,
                    session_path=session_path,
                    events_count=events_count,
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
                    error=f"Exception: {e}",
                    log_level=logging.ERROR,
                )
                raise
        finally:
            client.close()

    def delete_opencode_session(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        opencode_session_id: str,
    ) -> bool:
        session_path = self._session_directory(session_id)
        client = self._build_serve_client(
            sandbox_id,
            session_path,
            with_event_bus=False,
        )
        try:
            return client.delete_session(opencode_session_id, directory=session_path)
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
        error: str,
        log_level: int,
    ) -> None:
        """Best-effort abort + structured log on a failed turn. Abort
        failures are swallowed — we're already in an error path."""
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

    def send_subagent_message_via_serve(
        self,
        sandbox_id: UUID,
        parent_session_id: UUID,
        subagent_opencode_session_id: str,
        message: str,
        agent_provider: str | None = None,
        agent_model: str | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        """Stream a follow-up turn against an existing subagent (child)
        opencode session.

        The child session runs in the SAME directory as its parent build
        session, so we anchor the serve client at the parent's session
        directory. Unlike :meth:`_send_message_via_serve` this does NOT call
        ``ensure_session`` (the child id is supplied and already exists). It
        passes the parent session's ``agent_provider``/``agent_model`` so the
        follow-up uses the same model as the parent (not the child session's
        own default).
        """
        session_path = self._session_directory(parent_session_id)
        client = self._build_serve_client(sandbox_id, session_path)
        try:
            logger.info(
                "[SANDBOX-SERVE] send_subagent_message: parent_build_session=%s "
                "subagent_opencode_session=%s api_pod=%s",
                parent_session_id,
                subagent_opencode_session_id,
                _API_SERVER_HOSTNAME,
            )

            events_count = 0
            try:
                for event in client.send_message(
                    subagent_opencode_session_id,
                    message,
                    directory=session_path,
                    model_provider=agent_provider,
                    model_id=agent_model,
                ):
                    events_count += 1
                    yield event
            except GeneratorExit:
                self._abort_and_log_turn_failure(
                    client=client,
                    session_id=parent_session_id,
                    resolved_session_id=subagent_opencode_session_id,
                    session_path=session_path,
                    events_count=events_count,
                    error="GeneratorExit",
                    log_level=logging.WARNING,
                )
                raise
            except Exception as e:
                self._abort_and_log_turn_failure(
                    client=client,
                    session_id=parent_session_id,
                    resolved_session_id=subagent_opencode_session_id,
                    session_path=session_path,
                    events_count=events_count,
                    error=f"Exception: {e}",
                    log_level=logging.ERROR,
                )
                raise
        finally:
            client.close()

    def subscribe_to_opencode_session(
        self,
        sandbox_id: UUID,
        opencode_session_id: str,
        *,
        directory: str,
        keepalive_seconds: float = 15.0,
    ) -> Generator[SandboxEvent, None, None]:
        """Stream translated sandbox events for an opencode session. Caller closes
        via ``GeneratorExit``. ``directory`` is required: opencode-serve scopes
        its session store per-directory, so the hydrate REST call needs it.
        """
        bus = self._get_or_create_event_bus(sandbox_id, directory)
        state = _TurnState(session_id=opencode_session_id)
        client = self._build_serve_client(sandbox_id, directory)

        def fetch_message(mid: str) -> dict[str, Any] | None:
            return client.get_message(opencode_session_id, mid, directory=directory)

        sub = bus.subscribe(opencode_session_id)
        try:
            last_event = time.monotonic()
            pending_text_event: SandboxEvent | None = None
            pending_text_started_at = 0.0
            while True:
                now = time.monotonic()
                if (
                    pending_text_event is not None
                    and now - pending_text_started_at >= LIVE_TEXT_COALESCE_SECONDS
                ):
                    yield pending_text_event
                    pending_text_event = None
                    continue

                queue_timeout = 1.0
                if pending_text_event is not None:
                    queue_timeout = max(
                        0.0,
                        LIVE_TEXT_COALESCE_SECONDS - (now - pending_text_started_at),
                    )
                try:
                    raw = sub.queue.get(timeout=queue_timeout)
                except queue.Empty:
                    if pending_text_event is not None:
                        yield pending_text_event
                        pending_text_event = None
                        continue
                    if time.monotonic() - last_event >= keepalive_seconds:
                        yield SSEKeepalive()
                        last_event = time.monotonic()
                    continue
                if raw is BUS_CLOSED_SENTINEL:
                    if pending_text_event is not None:
                        yield pending_text_event
                    return
                last_event = time.monotonic()
                if raw.get("type") == "server.connected":
                    continue
                for sandbox_event in translate_opencode_event(
                    raw,
                    state,
                    fetch_message=fetch_message,
                    parent_resolver=bus.parent_of,
                    children_resolver=bus.list_children,
                    fetch_message_by_session=lambda session_id,
                    message_id: client.get_message(
                        session_id, message_id, directory=directory
                    ),
                ):
                    if pending_text_event is not None:
                        merged = _merge_text_chunk(pending_text_event, sandbox_event)
                        if merged is not None:
                            pending_text_event = merged
                            continue

                        yield pending_text_event
                        pending_text_event = None

                    if (
                        isinstance(
                            sandbox_event, (AgentMessageChunk, AgentThoughtChunk)
                        )
                        and getattr(sandbox_event.content, "type", None) == "text"
                    ):
                        pending_text_event = sandbox_event
                        pending_text_started_at = time.monotonic()
                        continue

                    yield sandbox_event
        finally:
            # Close client first so a flaky unsubscribe doesn't leak the pool.
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


def _merge_text_chunk(
    pending: SandboxEvent,
    incoming: SandboxEvent,
) -> SandboxEvent | None:
    if type(pending) is not type(incoming):
        return None
    if not isinstance(pending, (AgentMessageChunk, AgentThoughtChunk)):
        return None

    pending_content = pending.content
    incoming_content = incoming.content
    if (
        getattr(pending_content, "type", None) != "text"
        or getattr(incoming_content, "type", None) != "text"
    ):
        return None

    pending_text = getattr(pending_content, "text", None)
    incoming_text = getattr(incoming_content, "text", None)
    if not isinstance(pending_text, str) or not isinstance(incoming_text, str):
        return None

    if getattr(pending_content, "field_meta", None) != getattr(
        incoming_content, "field_meta", None
    ) or getattr(pending_content, "annotations", None) != getattr(
        incoming_content, "annotations", None
    ):
        return None

    return pending.model_copy(
        update={
            "content": pending_content.model_copy(
                update={"text": pending_text + incoming_text}
            )
        }
    )
