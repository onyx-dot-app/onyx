"""Per-pod opencode-serve event bus.

One long-lived ``GET /event`` SSE subscription per opencode-serve process,
fanned out to per-session subscriber queues. opencode-serve does not
support ``Last-Event-ID`` (sst/opencode#25657), so subscribers reconcile
gaps via the cumulative ``part.text`` field on ``message.part.updated``.
"""

from __future__ import annotations

import json
import threading
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
        connect_timeout: float = 10.0,
        event_read_timeout: float | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
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
        (e.g. ``KubernetesSandboxManager._event_buses``) should check this
        before reusing a bus — a closed bus will only deliver
        ``BUS_CLOSED_SENTINEL`` to subscribers."""
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
            try:
                self._read_one_stream()
                had_successful_read = self.stream_ready.is_set()
                if not self._stop.is_set():
                    logger.info(
                        "opencode /event stream ended; reconnecting in %.1fs",
                        backoff,
                    )
            except Exception as e:
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
        with httpx.stream(
            "GET",
            f"{self._base_url}/event",
            auth=self._auth,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            self.stream_ready.set()
            logger.info(
                "PodEventBus connected to %s/event (status=%s)",
                self._base_url,
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

    def _dispatch(self, evt: dict[str, Any]) -> None:
        etype = evt.get("type")
        props = evt.get("properties") or {}

        if etype == "session.created":
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

        sid = _extract_session_id(evt)
        if sid is None:
            return

        with self._lock:
            queues = list(self._subscribers.get(sid, ()))
        for sub in queues:
            try:
                sub.queue.put_nowait(evt)
            except Full:
                sub.dropped_count += 1
                if sub.dropped_count == 1 or sub.dropped_count % 50 == 0:
                    logger.warning(
                        "PodEventBus dropped event for session %s "
                        "(queue full; total dropped=%d)",
                        sid,
                        sub.dropped_count,
                    )


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
