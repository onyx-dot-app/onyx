"""Unit tests for `streaming.merge_events_with_announces`.

The merger is a generator that interleaves a synchronous event iterator with
approval-announce events drained from a Redis-style BLPOP. Two daemon threads
write onto a shared `queue.Queue` until the event iterator completes.
"""

import json
import threading
import time
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.server.features.build.packets import ApprovalRequestedPacket
from onyx.server.features.build.session import streaming as streaming_mod


def _collect_with_timeout(
    gen: Generator[Any, None, None], timeout_s: float = 2.0
) -> list[Any]:
    """Drain a generator on a thread; fail the test if it doesn't finish."""
    items: list[Any] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            for item in gen:
                items.append(item)
        except BaseException as e:  # noqa: BLE001
            error.append(e)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout_s)
    assert not t.is_alive(), "merger generator did not terminate"
    if error:
        raise error[0]
    return items


def _stub_get_cache_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        streaming_mod,
        "get_cache_backend",
        lambda tenant_id: MagicMock(),  # noqa: ARG005 — kwarg name must match production caller
    )


def _stub_pop_announcement(monkeypatch: pytest.MonkeyPatch, fn: Any) -> None:
    monkeypatch.setattr(streaming_mod.approval_cache, "pop_announcement", fn)


def _always_none(_session_id: UUID, timeout_s: int, cache: Any) -> UUID | None:  # noqa: ARG001 — kwarg name must match production caller
    # Honor the timeout so the poll loop doesn't spin while events produces.
    time.sleep(min(0.05, float(timeout_s)))
    return None


def test_events_only_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get_cache_backend(monkeypatch)
    _stub_pop_announcement(monkeypatch, _always_none)

    def events() -> Generator[str, None, None]:
        yield "a"
        yield "b"
        yield "c"

    out = _collect_with_timeout(
        streaming_mod.merge_events_with_announces(
            events(), session_id=uuid4(), tenant_id="public"
        )
    )

    assert out == ["a", "b", "c"]


def test_announce_emitted_as_approval_requested_packet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    approval_id = uuid4()
    pop_call_count: list[int] = []
    announce_enqueued = threading.Event()

    def pop(_sid: UUID, timeout_s: int, cache: Any) -> UUID | None:  # noqa: ARG001 — kwarg name must match production caller
        # Deliver the approval on the first call. By the second call the
        # announce-pump has already enqueued the packet, so signalling here
        # lets events end deterministically once the packet is on the queue.
        pop_call_count.append(1)
        if len(pop_call_count) == 1:
            return approval_id
        announce_enqueued.set()
        time.sleep(min(0.02, float(timeout_s)))
        return None

    _stub_get_cache_backend(monkeypatch)
    _stub_pop_announcement(monkeypatch, pop)

    def events() -> Generator[str, None, None]:
        # Wait until the announce packet is queued before ending (no sleeps).
        assert announce_enqueued.wait(timeout=2.0), "announce packet was never enqueued"
        yield "events-end"

    out = _collect_with_timeout(
        streaming_mod.merge_events_with_announces(
            events(), session_id=session_id, tenant_id="public"
        )
    )

    packets = [item for item in out if isinstance(item, ApprovalRequestedPacket)]
    assert len(packets) == 1
    packet = packets[0]
    assert packet.approval_id == approval_id
    assert packet.session_id == session_id
    assert packet.type == "approval_requested"

    # Verify the SSE-frame shape the attach stream produces from this packet.
    rendered = streaming_mod.event_to_sse(packet)
    assert rendered.startswith("event: message\n")
    parsed = json.loads(rendered.split("data: ", 1)[1])
    assert parsed["type"] == "approval_requested"
    assert parsed["approval_id"] == str(approval_id)
    assert parsed["session_id"] == str(session_id)


def test_interleaving_events_and_announce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The announce packet is yielded BETWEEN "x" and "y".

    Two events make the FIFO order deterministic: `x_yielded` blocks the
    announce stub until "x" is queued; `announce_enqueued` blocks events from
    yielding "y" until the packet is queued. Output: `["x", <packet>, "y"]`.
    """
    session_id = uuid4()
    approval_id = uuid4()
    x_yielded = threading.Event()
    announce_enqueued = threading.Event()
    pop_call_count: list[int] = []

    def pop(_sid: UUID, timeout_s: int, cache: Any) -> UUID | None:  # noqa: ARG001 — kwarg name must match production caller
        # Don't deliver until "x" is already on the output queue.
        if not x_yielded.wait(timeout=2.0):
            return None
        pop_call_count.append(1)
        if len(pop_call_count) == 1:
            return approval_id
        # By the second call the packet is enqueued; let events yield "y".
        announce_enqueued.set()
        time.sleep(min(0.02, float(timeout_s)))
        return None

    _stub_get_cache_backend(monkeypatch)
    _stub_pop_announcement(monkeypatch, pop)

    def events() -> Generator[str, None, None]:
        yield "x"
        x_yielded.set()
        assert announce_enqueued.wait(timeout=2.0), "announce packet was never enqueued"
        yield "y"

    out = _collect_with_timeout(
        streaming_mod.merge_events_with_announces(
            events(), session_id=session_id, tenant_id="public"
        )
    )

    assert len(out) == 3
    assert out[0] == "x"
    assert isinstance(out[1], ApprovalRequestedPacket)
    assert out[1].approval_id == approval_id
    assert out[2] == "y"


def test_terminates_when_event_iterator_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_cache_backend(monkeypatch)
    _stub_pop_announcement(monkeypatch, _always_none)

    def events() -> Generator[str, None, None]:
        yield "only"

    # Generator must finish even though the announce thread would BLPOP forever.
    out = _collect_with_timeout(
        streaming_mod.merge_events_with_announces(
            events(), session_id=uuid4(), tenant_id="public"
        ),
        timeout_s=1.0,
    )
    assert out == ["only"]


def test_no_deadlock_when_announce_thread_sees_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get_cache_backend(monkeypatch)
    _stub_pop_announcement(monkeypatch, _always_none)

    pre_threads = {t.name for t in threading.enumerate()}

    def events() -> Generator[str, None, None]:
        yield "p"
        yield "q"

    out = _collect_with_timeout(
        streaming_mod.merge_events_with_announces(
            events(), session_id=uuid4(), tenant_id="public"
        )
    )
    assert out == ["p", "q"]

    # The merger sets `stop` on exit; the announce daemon notices on its next
    # tick. Allow a brief grace window then verify no pump threads leaked.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        leaked = [
            t
            for t in threading.enumerate()
            if t.name not in pre_threads
            and ("announce-pump" in t.name or "events-pump" in t.name)
            and t.is_alive()
        ]
        if not leaked:
            break
        time.sleep(0.05)
    leaked = [
        t
        for t in threading.enumerate()
        if t.name not in pre_threads
        and ("announce-pump" in t.name or "events-pump" in t.name)
        and t.is_alive()
    ]
    assert leaked == [], f"threads did not exit cleanly: {leaked}"


def test_pop_announcement_exception_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising `pop_announcement` is logged and the loop keeps polling.

    Asserting `>= 2` calls (not `>= 1`) pins that the loop survives a raise
    instead of crashing the thread after one iteration.
    """
    calls: list[int] = []
    second_call = threading.Event()

    def pop(_sid: UUID, timeout_s: int, cache: Any) -> UUID | None:  # noqa: ARG001 — kwarg names must match production caller
        calls.append(1)
        if len(calls) >= 2:
            second_call.set()
        raise RuntimeError("redis exploded")

    _stub_get_cache_backend(monkeypatch)
    _stub_pop_announcement(monkeypatch, pop)

    def events() -> Generator[str, None, None]:
        # Wait for the second raise to prove the loop survived the first.
        assert second_call.wait(timeout=2.0), "announce loop did not retry"
        yield "still-ok"

    out = _collect_with_timeout(
        streaming_mod.merge_events_with_announces(
            events(), session_id=uuid4(), tenant_id="public"
        )
    )

    assert out == ["still-ok"]
    assert len(calls) >= 2
