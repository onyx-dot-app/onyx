"""Unit tests for :mod:`onyx.server.features.build.sandbox.opencode.event_bus`.

The bus is the most critical new component in the opencode-serve migration:
one long-lived ``/event`` SSE subscription per pod, multiplexed to
per-session subscriber queues. These tests cover the pure-Python pieces
of the bus — dispatch routing, sessionID extraction, parent/child
tracking, queue overflow, and close semantics — by exercising the bus
directly without standing up a real HTTP server. The reader loop's
httpx interaction is tested with a small subset of cases via a fake
transport.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from queue import Empty
from typing import Any

import httpx
import pytest

from onyx.server.features.build.sandbox.opencode import event_bus as event_bus_mod
from onyx.server.features.build.sandbox.opencode.event_bus import _extract_session_id
from onyx.server.features.build.sandbox.opencode.event_bus import _parse_sse_block
from onyx.server.features.build.sandbox.opencode.event_bus import BUS_CLOSED_SENTINEL
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> Generator[PodEventBus, None, None]:
    """Bus instance that never starts a reader thread (we drive ``_dispatch``
    directly). Closed at teardown."""
    b = PodEventBus(base_url="http://test.invalid:4096", auth=None)
    try:
        yield b
    finally:
        b.close()


def _make_event(
    etype: str,
    sessionID: str | None = None,
    info: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Construct an opencode event dict with the common ``properties`` shape."""
    props: dict[str, Any] = {}
    if sessionID is not None:
        props["sessionID"] = sessionID
    if info is not None:
        props["info"] = info
    props.update(extra)
    return {"type": etype, "properties": props}


# ---------------------------------------------------------------------------
# _extract_session_id — handles both schemas opencode uses
# ---------------------------------------------------------------------------


def test_extract_session_id_from_properties_direct() -> None:
    evt = _make_event("message.part.delta", sessionID="ses_A")
    assert _extract_session_id(evt) == "ses_A"


def test_extract_session_id_from_info_when_properties_lacks() -> None:
    # Some events (message.updated) carry sessionID on the nested Message
    # object instead of (or in addition to) properties.sessionID.
    evt = {"type": "message.updated", "properties": {"info": {"sessionID": "ses_B"}}}
    assert _extract_session_id(evt) == "ses_B"


def test_extract_session_id_properties_wins_over_info() -> None:
    """If both paths are set, properties.sessionID takes precedence."""
    evt = {
        "type": "message.updated",
        "properties": {"sessionID": "ses_outer", "info": {"sessionID": "ses_inner"}},
    }
    assert _extract_session_id(evt) == "ses_outer"


def test_extract_session_id_returns_none_for_global_events() -> None:
    assert _extract_session_id({"type": "server.connected", "properties": {}}) is None


def test_extract_session_id_returns_none_when_properties_missing() -> None:
    assert _extract_session_id({"type": "something"}) is None


def test_extract_session_id_handles_non_dict_properties() -> None:
    # Defensive: opencode shouldn't emit a non-dict ``properties``, but the
    # bus must not crash if it ever does.
    assert _extract_session_id({"type": "x", "properties": "garbage"}) is None


def test_extract_session_id_ignores_empty_string() -> None:
    evt = _make_event("message.part.delta", sessionID="")
    assert _extract_session_id(evt) is None


def test_extract_session_id_ignores_non_string_session_id() -> None:
    evt = {"type": "x", "properties": {"sessionID": 12345}}
    assert _extract_session_id(evt) is None


# ---------------------------------------------------------------------------
# _parse_sse_block — strict SSE framing
# ---------------------------------------------------------------------------


def test_parse_sse_block_simple_data_line() -> None:
    raw = 'data: {"type":"x","properties":{}}'
    assert _parse_sse_block(raw) == {"type": "x", "properties": {}}


def test_parse_sse_block_multi_line_data() -> None:
    raw = 'data: {"type":"x",\ndata: "properties":{}}'
    assert _parse_sse_block(raw) == {"type": "x", "properties": {}}


def test_parse_sse_block_ignores_event_and_id_lines() -> None:
    raw = 'event: foo\nid: 123\ndata: {"type":"x"}'
    assert _parse_sse_block(raw) == {"type": "x"}


def test_parse_sse_block_handles_no_space_after_colon() -> None:
    # SSE technically allows ``data:value`` with no space.
    assert _parse_sse_block('data:{"type":"x"}') == {"type": "x"}


def test_parse_sse_block_returns_none_on_empty_block() -> None:
    assert _parse_sse_block("") is None
    assert _parse_sse_block("event: foo\nid: 1") is None  # no data line


def test_parse_sse_block_returns_none_on_malformed_json() -> None:
    assert _parse_sse_block("data: not-json") is None


def test_parse_sse_block_returns_none_on_non_object_json() -> None:
    # Bus dispatcher assumes dict; arrays/scalars must be filtered out.
    assert _parse_sse_block("data: [1,2,3]") is None
    assert _parse_sse_block("data: 42") is None


# ---------------------------------------------------------------------------
# Dispatch — routes events to the right subscribers
# ---------------------------------------------------------------------------


def test_dispatch_delivers_event_to_matching_subscriber(bus: PodEventBus) -> None:
    sub = bus.subscribe("ses_A")
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_A", delta="hi"))
    item = sub.queue.get_nowait()
    assert item is not None
    assert item["properties"]["delta"] == "hi"


def test_dispatch_filters_events_for_other_sessions(bus: PodEventBus) -> None:
    sub_a = bus.subscribe("ses_A")
    bus.subscribe("ses_B")
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_B"))
    with pytest.raises(Empty):
        sub_a.queue.get_nowait()


def test_dispatch_fans_out_to_multiple_subscribers_same_session(
    bus: PodEventBus,
) -> None:
    sub1 = bus.subscribe("ses_A")
    sub2 = bus.subscribe("ses_A")
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_A"))
    assert sub1.queue.get_nowait() is not None
    assert sub2.queue.get_nowait() is not None


def test_dispatch_drops_global_events_without_sessionid(bus: PodEventBus) -> None:
    sub = bus.subscribe("ses_A")
    bus._dispatch({"type": "server.connected", "properties": {}})
    with pytest.raises(Empty):
        sub.queue.get_nowait()


def test_dispatch_fans_out_unscoped_session_error(bus: PodEventBus) -> None:
    """opencode can publish terminal session events without sessionID. Since the
    bus is directory-scoped, deliver those to active subscribers instead of
    dropping them and leaving send-message to emit keepalives until timeout."""
    sub_a = bus.subscribe("ses_A")
    sub_b = bus.subscribe("ses_B")

    bus._dispatch(
        {
            "type": "session.error",
            "properties": {"error": {"data": {"message": "upstream reset"}}},
        }
    )

    item_a = sub_a.queue.get_nowait()
    item_b = sub_b.queue.get_nowait()
    assert item_a is not None
    assert item_b is not None
    assert item_a["type"] == "session.error"
    assert item_b["type"] == "session.error"
    assert item_a["properties"]["error"]["data"]["message"] == "upstream reset"


def test_dispatch_fans_out_unscoped_idle_status(bus: PodEventBus) -> None:
    sub = bus.subscribe("ses_A")

    bus._dispatch(
        {"type": "session.status", "properties": {"status": {"type": "idle"}}}
    )

    item = sub.queue.get_nowait()
    assert item is not None
    assert item["type"] == "session.status"


def test_dispatch_drops_unscoped_non_terminal_event(bus: PodEventBus) -> None:
    sub = bus.subscribe("ses_A")

    bus._dispatch({"type": "session.updated", "properties": {}})

    with pytest.raises(Empty):
        sub.queue.get_nowait()


def test_dispatch_extracts_sessionid_from_nested_info(bus: PodEventBus) -> None:
    """``message.updated`` puts sessionID on the inner Message object."""
    sub = bus.subscribe("ses_A")
    bus._dispatch(
        {
            "type": "message.updated",
            "properties": {"info": {"sessionID": "ses_A", "role": "assistant"}},
        }
    )
    assert sub.queue.get_nowait() is not None


def test_dispatch_no_subscribers_is_noop(bus: PodEventBus) -> None:
    """No registered subscribers for the session ID — event is dropped
    silently. Common case: events arriving before any send_message starts."""
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_orphan"))
    # No assertion needed; just shouldn't raise.


# ---------------------------------------------------------------------------
# Subagent (parent/child) tracking
# ---------------------------------------------------------------------------


def test_dispatch_session_created_records_parent_child(bus: PodEventBus) -> None:
    bus._dispatch(
        {
            "type": "session.created",
            "properties": {
                "sessionID": "ses_child",
                "info": {"id": "ses_child", "parentID": "ses_parent"},
            },
        }
    )
    assert bus.list_children("ses_parent") == ["ses_child"]
    assert bus.parent_of("ses_child") == "ses_parent"


def test_dispatch_session_created_without_sessionid_delivers_to_parent(
    bus: PodEventBus,
) -> None:
    """opencode's session.created shape identifies the child as info.id, not
    properties.sessionID. Parent subscribers still need the event immediately
    so the task card can attach to the live child session."""
    parent_sub = bus.subscribe("ses_parent")
    child_sub = bus.subscribe("ses_child")

    bus._dispatch(
        {
            "type": "session.created",
            "properties": {
                "info": {"id": "ses_child", "parentID": "ses_parent"},
            },
        }
    )

    item = parent_sub.queue.get_nowait()
    assert item is not None
    assert item["type"] == "session.created"
    assert item["properties"]["info"]["id"] == "ses_child"
    assert bus.list_children("ses_parent") == ["ses_child"]
    assert bus.parent_of("ses_child") == "ses_parent"
    with pytest.raises(Empty):
        child_sub.queue.get_nowait()


def test_list_children_preserves_spawn_order(bus: PodEventBus) -> None:
    """``list_children`` returns child sessionIDs in the order opencode
    emitted ``session.created`` — NOT lexicographic. Frontends use this
    list as the basis for 'next/previous subagent' navigation, so
    iteration order must match what the user saw spawn first."""
    for child_id in ("ses_z", "ses_a", "ses_m"):
        bus._dispatch(
            {
                "type": "session.created",
                "properties": {
                    "sessionID": child_id,
                    "info": {"id": child_id, "parentID": "ses_parent"},
                },
            }
        )
    assert bus.list_children("ses_parent") == ["ses_z", "ses_a", "ses_m"]


def test_list_children_dedupes_repeated_session_created(bus: PodEventBus) -> None:
    """opencode may re-emit session.created on reconnect/resync (or our
    bus reader may reconnect mid-stream and observe the same event
    again). The same child must appear only once in list_children."""
    for _ in range(3):
        bus._dispatch(
            {
                "type": "session.created",
                "properties": {
                    "sessionID": "ses_child",
                    "info": {"id": "ses_child", "parentID": "ses_parent"},
                },
            }
        )
    assert bus.list_children("ses_parent") == ["ses_child"]


def test_list_children_returns_empty_for_unknown_parent(bus: PodEventBus) -> None:
    assert bus.list_children("ses_no_children") == []


def test_session_created_without_parentid_does_not_register_child(
    bus: PodEventBus,
) -> None:
    """A top-level session.created (no parentID) must not pollute
    parent/child maps."""
    bus._dispatch(
        {
            "type": "session.created",
            "properties": {
                "sessionID": "ses_top",
                "info": {"id": "ses_top"},  # no parentID
            },
        }
    )
    assert bus.parent_of("ses_top") is None
    assert bus.list_children("ses_top") == []


# ---------------------------------------------------------------------------
# Subscriber lifecycle
# ---------------------------------------------------------------------------


def test_unsubscribe_removes_subscriber(bus: PodEventBus) -> None:
    sub = bus.subscribe("ses_A")
    bus.unsubscribe(sub)
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_A"))
    with pytest.raises(Empty):
        sub.queue.get_nowait()


def test_unsubscribe_only_removes_the_specific_subscriber(bus: PodEventBus) -> None:
    """Two subscribers on the same session; unsubscribing one leaves the
    other receiving events."""
    sub1 = bus.subscribe("ses_A")
    sub2 = bus.subscribe("ses_A")
    bus.unsubscribe(sub1)
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_A"))
    with pytest.raises(Empty):
        sub1.queue.get_nowait()
    assert sub2.queue.get_nowait() is not None


def test_unsubscribe_unknown_subscription_is_idempotent(bus: PodEventBus) -> None:
    """Defensive: caller may unsubscribe twice on error paths. Must not raise."""
    sub = bus.subscribe("ses_A")
    bus.unsubscribe(sub)
    bus.unsubscribe(sub)  # second call is a no-op


def test_subscribe_after_close_returns_pre_drained_queue(bus: PodEventBus) -> None:
    """After ``close()``, subsequent subscribers should receive the close
    sentinel immediately so they don't block forever."""
    bus.close()
    sub = bus.subscribe("ses_A")
    assert sub.queue.get_nowait() is BUS_CLOSED_SENTINEL


# ---------------------------------------------------------------------------
# Queue overflow — drop policy
# ---------------------------------------------------------------------------


def test_subscriber_queue_full_increments_dropped_count(bus: PodEventBus) -> None:
    sub = bus.subscribe("ses_A")
    # Fill the queue to capacity.
    for _ in range(sub.queue.maxsize):
        sub.queue.put_nowait({"filler": True})
    # Next dispatch should drop, not raise.
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_A"))
    assert sub.dropped_count == 1
    # Repeated full-queue dispatches keep counting.
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_A"))
    assert sub.dropped_count == 2


def test_subscriber_queue_overflow_does_not_block_other_subscribers(
    bus: PodEventBus,
) -> None:
    """A slow subscriber must not back-pressure the shared dispatcher."""
    slow = bus.subscribe("ses_A")
    fast = bus.subscribe("ses_A")
    for _ in range(slow.queue.maxsize):
        slow.queue.put_nowait({"filler": True})
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_A"))
    assert slow.dropped_count == 1
    assert fast.queue.get_nowait() is not None  # fast still gets the event


def test_unscoped_queue_overflow_log_uses_sentinel(
    bus: PodEventBus,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sub = bus.subscribe("ses_A")
    for _ in range(sub.queue.maxsize):
        sub.queue.put_nowait({"filler": True})

    with caplog.at_level("WARNING", logger=event_bus_mod.logger.name):
        bus._dispatch(
            {
                "type": "session.error",
                "properties": {"error": {"data": {"message": "upstream reset"}}},
            }
        )

    assert sub.dropped_count == 1
    assert "session <unscoped>" in caplog.text
    assert "session None" not in caplog.text


# ---------------------------------------------------------------------------
# Close semantics
# ---------------------------------------------------------------------------


def test_close_signals_existing_subscribers_with_sentinel(bus: PodEventBus) -> None:
    sub = bus.subscribe("ses_A")
    bus.close()
    assert sub.queue.get_nowait() is BUS_CLOSED_SENTINEL


def test_close_signals_subscribers_even_with_full_queue(bus: PodEventBus) -> None:
    """When a subscriber's queue is full at close time, the bus drops the
    head to make room for the sentinel — so consumers can detect close
    without polling indefinitely."""
    sub = bus.subscribe("ses_A")
    for _ in range(sub.queue.maxsize):
        sub.queue.put_nowait({"filler": True})
    bus.close()
    # The sentinel may be at any position — drain until found or queue empty.
    saw_sentinel = False
    while True:
        try:
            item = sub.queue.get_nowait()
        except Empty:
            break
        if item is BUS_CLOSED_SENTINEL:
            saw_sentinel = True
            break
    assert saw_sentinel, "close() must place the sentinel in subscriber queues"


def test_close_is_idempotent(bus: PodEventBus) -> None:
    bus.close()
    bus.close()  # must not raise


# ---------------------------------------------------------------------------
# /event request scoping — directory query parameter
# ---------------------------------------------------------------------------
#
# opencode-serve's ``Instance.provide`` middleware reads ``?directory=`` off
# the /event request and routes the subscription to that directory's
# Instance. Without the query param, the SSE stream only sees the default
# Instance (server.connected + server.heartbeat) and session events for
# /workspace/sessions/<id> never arrive — sessions on the same pod silently
# fail or cross-talk depending on which one connected first. These tests
# pin the wire-level contract.


class _CapturingStream:
    """Stand-in for ``httpx.stream``'s return value. Records the kwargs the
    bus passed (URL, params, auth, timeout) and raises a ``ConnectError`` on
    ``__enter__`` so ``_read_one_stream`` exits without trying to consume a
    response body."""

    captured: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).captured = {"args": args, "kwargs": kwargs}

    def __enter__(self) -> Any:
        raise httpx.ConnectError("test stop")

    def __exit__(self, *_: Any) -> None:
        return None


def test_read_one_stream_passes_directory_as_query_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the bus is constructed with ``directory=...``, the GET /event
    call MUST include ``?directory=...`` so opencode-serve scopes the
    subscription to that Instance. Without this param, no session events
    are delivered — which is exactly the bug this PR fixes."""
    monkeypatch.setattr(event_bus_mod.httpx, "stream", _CapturingStream)
    bus = PodEventBus(
        base_url="http://test.invalid:4096",
        auth=None,
        directory="/workspace/sessions/abc-123",
    )
    try:
        with pytest.raises(httpx.ConnectError):
            bus._read_one_stream()
    finally:
        bus.close()

    kwargs = _CapturingStream.captured["kwargs"]
    args = _CapturingStream.captured["args"]
    assert kwargs["params"] == {"directory": "/workspace/sessions/abc-123"}
    # The directory must travel as a query param, not be baked into the path —
    # the URL stays the bare /event endpoint.
    assert args == ("GET", "http://test.invalid:4096/event")


# ---------------------------------------------------------------------------
# Reader-loop integration via fake httpx transport
# ---------------------------------------------------------------------------


def test_dispatch_handles_session_error_event(bus: PodEventBus) -> None:
    """session.error carries sessionID + error.data.message — bus must
    deliver it so the consumer's translator can yield an Error SandboxEvent."""
    sub = bus.subscribe("ses_A")
    bus._dispatch(
        {
            "type": "session.error",
            "properties": {
                "sessionID": "ses_A",
                "error": {"data": {"message": "boom"}},
            },
        }
    )
    item = sub.queue.get_nowait()
    assert item is not None
    assert item["type"] == "session.error"
    assert item["properties"]["error"]["data"]["message"] == "boom"


# ---------------------------------------------------------------------------
# Thread safety smoke test
# ---------------------------------------------------------------------------


def test_reader_self_closes_after_max_consecutive_failures() -> None:
    """Bus reader gives up after _RECONNECT_MAX_CONSECUTIVE_FAILURES
    failed reconnects, self-closes, and signals subscribers — without
    this cap, an api_server would leak a reader thread + httpx client
    per orphan pod (eviction, OOMKill, GC, replica restart with
    pre-existing pods).

    Test approach: point the bus at a definitely-unreachable URL with a
    tiny backoff so the failure cap is hit quickly. The subscriber's
    queue should receive the close sentinel.
    """
    bus = PodEventBus(
        base_url="http://127.0.0.1:1",  # closed port
        auth=None,
        connect_timeout=0.1,
    )
    # Tighten the schedule so the test runs in <2s.
    bus._RECONNECT_BACKOFF_INITIAL = 0.05  # type: ignore[misc]
    bus._RECONNECT_BACKOFF_MAX = 0.05  # type: ignore[misc]
    bus._RECONNECT_MAX_CONSECUTIVE_FAILURES = 3  # type: ignore[misc]
    sub = bus.subscribe("ses_anything")
    try:
        # Wait up to 5s for the bus to give up and signal close.
        item = sub.queue.get(timeout=5.0)
        assert item is BUS_CLOSED_SENTINEL
    finally:
        bus.close()


def test_dispatch_under_concurrent_subscribers(bus: PodEventBus) -> None:
    """The dispatch path holds a brief lock while snapshotting subscribers.
    Smoke test: concurrent subscribe/unsubscribe alongside dispatch must
    not corrupt state or raise."""
    stop = threading.Event()
    subs: list[Any] = []

    def churn() -> None:
        while not stop.is_set():
            s = bus.subscribe("ses_A")
            subs.append(s)
            if len(subs) > 5:
                bus.unsubscribe(subs.pop(0))

    t = threading.Thread(target=churn, daemon=True)
    t.start()
    try:
        for _ in range(200):
            bus._dispatch(_make_event("message.part.delta", sessionID="ses_A"))
    finally:
        stop.set()
        t.join(timeout=2.0)

    # No assertion on counts — drop policy makes that flaky. Just verify
    # we exited cleanly without exceptions and the bus is still usable.
    sub = bus.subscribe("ses_other")
    bus._dispatch(_make_event("message.part.delta", sessionID="ses_other"))
    assert sub.queue.get_nowait() is not None


# ---------------------------------------------------------------------------
# 401 self-heal: a peer api_server pod rotated the opencode password, so the
# bus's cached auth is stale. The reader must reload auth before reconnecting
# rather than burning its whole reconnect budget on 401s.
# ---------------------------------------------------------------------------


class _Status401Stream:
    """Stand-in for ``httpx.stream`` whose response is a 401."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs

    def __enter__(self) -> httpx.Response:
        return httpx.Response(401, request=httpx.Request("GET", self._args[1]))

    def __exit__(self, *_: Any) -> None:
        return None


def test_read_one_stream_reloads_auth_on_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_bus_mod.httpx, "stream", _Status401Stream)
    fresh = httpx.BasicAuth("opencode", "fresh-pw")
    reloads: list[int] = []

    def reload_auth() -> httpx.Auth:
        reloads.append(1)
        return fresh

    bus = PodEventBus(
        base_url="http://test.invalid:4096",
        auth=httpx.BasicAuth("opencode", "stale-pw"),
        reload_auth=reload_auth,
    )
    try:
        # 401 → reload auth, then raise_for_status bubbles up to trigger reconnect.
        with pytest.raises(httpx.HTTPStatusError):
            bus._read_one_stream()
    finally:
        bus.close()

    assert reloads == [1]
    assert bus._auth is fresh


def test_read_one_stream_401_without_reload_auth_just_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_bus_mod.httpx, "stream", _Status401Stream)
    bus = PodEventBus(base_url="http://test.invalid:4096", auth=None)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            bus._read_one_stream()
    finally:
        bus.close()


def test_read_one_stream_401_no_op_when_credential_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine auth failure (reload returns the same credential) must not
    swap auth — otherwise every reconnect logs a misleading "reloaded"."""
    monkeypatch.setattr(event_bus_mod.httpx, "stream", _Status401Stream)
    current = httpx.BasicAuth("opencode", "same-pw")

    bus = PodEventBus(
        base_url="http://test.invalid:4096",
        auth=current,
        # Distinct object, same credential — the 401 is genuine, not a rotation.
        reload_auth=lambda: httpx.BasicAuth("opencode", "same-pw"),
    )
    try:
        with pytest.raises(httpx.HTTPStatusError):
            bus._read_one_stream()
    finally:
        bus.close()

    assert bus._auth is current
