"""Per-pod opencode-serve event bus.

One long-lived ``GET /event`` SSE subscription per opencode-serve process,
fanned out to per-session subscriber queues. opencode-serve does not
support ``Last-Event-ID`` (sst/opencode#25657), so subscribers reconcile
gaps via the cumulative ``part.text`` field on ``message.part.updated``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from queue import Empty
from queue import Full
from queue import Queue
from typing import Any

import httpx

from onyx.utils.logger import setup_logger

logger = setup_logger()


BUS_CLOSED_SENTINEL = None


@dataclass
class _Subscription:
    session_id: str
    queue: "Queue[dict[str, Any] | None]" = field(
        default_factory=lambda: Queue(maxsize=500)
    )
    dropped_count: int = 0


class PodEventBus:
    """Single-pod opencode-serve event multiplexer."""

    _RECONNECT_BACKOFF_INITIAL = 1.0
    _RECONNECT_BACKOFF_MAX = 30.0
    # Give up after this many consecutive failed reconnects — the pod is
    # almost certainly gone (eviction, OOMKill, GC) and continuing to
    # retry leaks a thread + httpx client per orphan pod.
    _RECONNECT_MAX_CONSECUTIVE_FAILURES = 20

    _SUBSCRIBER_QUEUE_MAXSIZE = 500

    def __init__(
        self,
        base_url: str,
        auth: httpx.Auth | None,
        *,
        directory: str | None = None,
        connect_timeout: float = 10.0,
        event_read_timeout: float | None = None,
        reload_auth: Callable[[], httpx.Auth | None] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        # Re-fetch auth on a /event 401 — a peer pod rotated the password.
        self._reload_auth = reload_auth
        # Opencode-serve's Instance.provide middleware scopes /event per
        # ?directory= query param. Without it, the SSE stream only sees the
        # default Instance (server.connected, server.heartbeat) — session
        # events are routed to the per-directory Instance.
        self._directory = directory
        self._connect_timeout = connect_timeout
        # Per-read inactivity timeout for the SSE /event stream. ``None`` means
        # block indefinitely between server frames (legacy behavior); a float
        # bounds how long httpx will wait for the next byte before raising
        # ReadTimeout, which the reader loop translates into a reconnect.
        self._event_read_timeout = event_read_timeout

        self._stop = threading.Event()
        self._closed = False
        self._lock = threading.Lock()

        self._subscribers: dict[str, list[_Subscription]] = {}
        # list (not set): ``list_children`` returns spawn order, which
        # frontends use for next/previous subagent nav.
        self._parent_to_children: dict[str, list[str]] = {}
        self._child_to_parent: dict[str, str] = {}

        self._reader_thread: threading.Thread | None = None
        self.stream_ready = threading.Event()

    @property
    def closed(self) -> bool:
        """True once the bus has either been explicitly closed or self-closed
        after exhausting its reconnect budget. Callers that cache buses
        (e.g. ``KubernetesSandboxManager._event_buses``, keyed by
        ``(sandbox_id, directory)``) should check this before reusing a bus —
        a closed bus will only deliver ``BUS_CLOSED_SENTINEL`` to
        subscribers."""
        return self._closed

    def subscribe(self, session_id: str) -> _Subscription:
        sub = _Subscription(
            session_id=session_id,
            queue=Queue(maxsize=self._SUBSCRIBER_QUEUE_MAXSIZE),
        )
        with self._lock:
            if self._closed:
                sub.queue.put_nowait(BUS_CLOSED_SENTINEL)
                return sub
            self._subscribers.setdefault(session_id, []).append(sub)
        self._ensure_reader_started()
        return sub

    def unsubscribe(self, sub: _Subscription) -> None:
        with self._lock:
            subs = self._subscribers.get(sub.session_id)
            if not subs:
                return
            try:
                subs.remove(sub)
            except ValueError:
                pass
            if not subs:
                self._subscribers.pop(sub.session_id, None)

    def list_children(self, parent_session_id: str) -> list[str]:
        """Child sessionIDs in spawn order."""
        with self._lock:
            return list(self._parent_to_children.get(parent_session_id, ()))

    def parent_of(self, child_session_id: str) -> str | None:
        with self._lock:
            return self._child_to_parent.get(child_session_id)

    def close(self) -> None:
        """Stop the reader and signal subscribers. Idempotent."""
        self._stop.set()
        self._signal_subscribers_closed()
        # Don't self-join if called from the reader thread (give-up path).
        if (
            self._reader_thread is not None
            and self._reader_thread.is_alive()
            and threading.get_ident() != self._reader_thread.ident
        ):
            self._reader_thread.join(timeout=5.0)
            if self._reader_thread.is_alive():
                logger.warning(
                    "PodEventBus reader thread did not exit within 5s on close"
                )

    def _signal_subscribers_closed(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscribers = [sub for subs in self._subscribers.values() for sub in subs]
            self._subscribers.clear()
        for sub in subscribers:
            try:
                sub.queue.put_nowait(BUS_CLOSED_SENTINEL)
            except Full:
                # Drop head to make room; slow consumers must not block close.
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(BUS_CLOSED_SENTINEL)
                except Empty:
                    pass

    def _ensure_reader_started(self) -> None:
        with self._lock:
            if self._reader_thread is not None or self._closed:
                return
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name=f"opencode-event-bus-{id(self):x}",
                daemon=True,
            )
            self._reader_thread.start()

    def _reader_loop(self) -> None:
        backoff = self._RECONNECT_BACKOFF_INITIAL
        consecutive_failures = 0
        while not self._stop.is_set():
            had_successful_read = False
            healed_401 = False
            try:
                self._read_one_stream()
                had_successful_read = self.stream_ready.is_set()
                if not self._stop.is_set():
                    logger.info(
                        "opencode /event stream ended; reconnecting in %.1fs",
                        backoff,
                    )
            except Exception as e:
                # Cached password was stale (pod re-provisioned with a new
                # Secret) — re-attach immediately with the rotated credential.
                # Still counts against the failure budget so a Secret source
                # that keeps rotating to wrong credentials can't spin forever.
                healed_401 = (
                    isinstance(e, httpx.HTTPStatusError)
                    and e.response.status_code == 401
                    and self._refresh_auth_on_401()
                )
                if not healed_401:
                    logger.warning(
                        "opencode /event stream error: %s; reconnecting in %.1fs",
                        e,
                        backoff,
                    )
            finally:
                self.stream_ready.clear()

            if had_successful_read:
                consecutive_failures = 0
                backoff = self._RECONNECT_BACKOFF_INITIAL
            else:
                consecutive_failures += 1
                if consecutive_failures >= self._RECONNECT_MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "PodEventBus giving up after %d consecutive reconnect "
                        "failures against %s; bus will self-close",
                        consecutive_failures,
                        self._base_url,
                    )
                    self._stop.set()
                    self._signal_subscribers_closed()
                    return

            if healed_401:
                continue
            if self._stop.wait(backoff):
                return
            backoff = min(backoff * 2.0, self._RECONNECT_BACKOFF_MAX)

        logger.info("PodEventBus reader exiting (stop signaled)")

    def _read_one_stream(self) -> None:
        timeout = httpx.Timeout(
            self._connect_timeout,
            read=self._event_read_timeout,
            write=10.0,
            pool=10.0,
        )
        params = {"directory": self._directory} if self._directory else None
        with httpx.stream(
            "GET",
            f"{self._base_url}/event",
            auth=self._auth,
            params=params,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            self.stream_ready.set()
            logger.info(
                "PodEventBus connected to %s/event?directory=%s (status=%s)",
                self._base_url,
                self._directory,
                response.status_code,
            )
            buf = ""
            for chunk in response.iter_text():
                if self._stop.is_set():
                    return
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    evt = _parse_sse_block(block)
                    if evt is None:
                        continue
                    self._dispatch(evt)

    def _refresh_auth_on_401(self) -> bool:
        """Reload auth after a 401; True if the credential actually rotated.
        Unchanged credential (genuine auth failure) or a failed reload keeps
        the current auth and returns False."""
        if self._reload_auth is None:
            return False
        try:
            new_auth = self._reload_auth()
        except Exception as e:
            logger.warning("PodEventBus reload_auth failed after 401: %s", e)
            return False
        if _auth_token(new_auth) == _auth_token(self._auth):
            return False
        self._auth = new_auth
        logger.info("PodEventBus reloaded auth after 401 on %s/event", self._base_url)
        return True

    def _dispatch(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        props = event.get("properties") or {}
        session_created_parent_id: str | None = None

        if event_type == "session.created":
            info = props.get("info") if isinstance(props, dict) else None
            if isinstance(info, dict):
                child_id = info.get("id")
                parent_id = info.get("parentID")
                if (
                    isinstance(child_id, str)
                    and isinstance(parent_id, str)
                    and child_id
                    and parent_id
                ):
                    session_created_parent_id = parent_id
                    with self._lock:
                        if child_id not in self._child_to_parent:
                            self._child_to_parent[child_id] = parent_id
                            self._parent_to_children.setdefault(parent_id, []).append(
                                child_id
                            )
                            logger.info(
                                "subagent session %s spawned under parent %s",
                                child_id,
                                parent_id,
                            )

        session_id = _extract_session_id(event)
        if session_id is None:
            session_id = session_created_parent_id
        log_session_id = session_id or "<unscoped>"

        # Deliver to session_id's own subscribers AND to every ancestor's subscribers
        # so a turn subscribed only to the parent session also sees descendant
        # (subagent) events. Walk _child_to_parent up to the root, deduping so
        # no subscriber receives the event twice.
        with self._lock:
            target_subscriptions: list[_Subscription] = []
            seen_subscriptions: set[int] = set()
            if session_id is None:
                if not _is_unscoped_terminal_event(event):
                    return
                # Some opencode terminal events are published without a
                # sessionID. The bus is directory-scoped, so active subscribers
                # are the only consumers that can observe that turn ending.
                subscriber_groups = self._subscribers.values()
            else:
                target_session_ids = [session_id]
                ancestor = self._child_to_parent.get(session_id)
                seen_session_ids = {session_id}
                while ancestor is not None and ancestor not in seen_session_ids:
                    target_session_ids.append(ancestor)
                    seen_session_ids.add(ancestor)
                    ancestor = self._child_to_parent.get(ancestor)
                subscriber_groups = (
                    self._subscribers.get(target_session_id, ())
                    for target_session_id in target_session_ids
                )
            for subscribers in subscriber_groups:
                for subscription in subscribers:
                    if id(subscription) not in seen_subscriptions:
                        seen_subscriptions.add(id(subscription))
                        target_subscriptions.append(subscription)
        for subscription in target_subscriptions:
            try:
                subscription.queue.put_nowait(event)
            except Full:
                subscription.dropped_count += 1
                if (
                    subscription.dropped_count == 1
                    or subscription.dropped_count % 50 == 0
                ):
                    logger.warning(
                        "PodEventBus dropped event for session %s "
                        "(queue full; total dropped=%d)",
                        log_session_id,
                        subscription.dropped_count,
                    )


def _auth_token(auth: httpx.Auth | None) -> str | None:
    """Render auth to its Authorization header for comparison — ``httpx.Auth``
    has no ``__eq__``, so drive its public ``auth_flow`` over a dummy request."""
    if auth is None:
        return None
    try:
        signed = next(auth.auth_flow(httpx.Request("GET", "http://x")))
        return signed.headers.get("authorization")
    except Exception:
        return None


def _extract_session_id(evt: dict[str, Any]) -> str | None:
    """opencode events expose sessionID at ``properties.sessionID`` for
    most types, but composite payloads (Message, PermissionRequest) carry
    it on the inner object — try both."""
    props = evt.get("properties")
    if not isinstance(props, dict):
        return None
    sid = props.get("sessionID")
    if isinstance(sid, str) and sid:
        return sid
    info = props.get("info")
    if isinstance(info, dict):
        nested = info.get("sessionID")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _is_unscoped_terminal_event(event: dict[str, Any]) -> bool:
    event_type = event.get("type")
    if event_type in ("session.error", "session.idle"):
        return True
    if event_type != "session.status":
        return False
    props = event.get("properties")
    if not isinstance(props, dict):
        return False
    status = props.get("status")
    return isinstance(status, dict) and status.get("type") == "idle"


def _parse_sse_block(block: str) -> dict[str, Any] | None:
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("data: "):
            data_lines.append(line[6:])
        elif line.startswith("data:"):
            data_lines.append(line[5:])
    if not data_lines:
        return None
    payload = "\n".join(data_lines)
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
