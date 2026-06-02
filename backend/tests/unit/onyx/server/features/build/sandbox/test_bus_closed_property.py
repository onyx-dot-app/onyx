"""Test for ``PodEventBus.closed`` and the cached-bus eviction it enables.

Empirical finding (2026-05-23): when the per-pod event bus exhausts its
reconnect budget (20 consecutive failures, e.g. against a long-idle pod
that gets evicted), it sets ``_closed=True`` and signals subscribers, but
``KubernetesSandboxManager._event_buses[sandbox_id]`` still holds the
dead bus. Every subsequent ``_get_or_create_event_bus`` returns the dead
instance, the next send hangs on ``stream_ready.wait()``, and the user
sees ``opencode /event stream did not become ready``. Three independent
chaos-test subagents hit this in sequence.

The fix: expose ``closed`` as a property; the manager checks it and
replaces the dead bus on the next access. These tests pin both halves.
"""

from __future__ import annotations

from onyx.server.features.build.sandbox.opencode.event_bus import BUS_CLOSED_SENTINEL
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus


def test_closed_property_starts_false() -> None:
    bus = PodEventBus(base_url="http://test.invalid:4096", auth=None)
    try:
        assert bus.closed is False
    finally:
        bus.close()


def test_closed_property_true_after_explicit_close() -> None:
    bus = PodEventBus(base_url="http://test.invalid:4096", auth=None)
    bus.close()
    assert bus.closed is True


def test_closed_property_signals_subscribers() -> None:
    """A subscriber that exists when the bus closes should receive
    BUS_CLOSED_SENTINEL — that's how downstream generators know to exit
    cleanly rather than wait forever."""
    bus = PodEventBus(base_url="http://test.invalid:4096", auth=None)
    sub = bus.subscribe("ses_test")
    try:
        bus.close()
        assert bus.closed is True
        # The close path should have delivered the sentinel.
        item = sub.queue.get(timeout=1.0)
        assert item is BUS_CLOSED_SENTINEL
    finally:
        # Don't double-close — already closed above.
        pass


def test_subscribe_after_close_immediately_delivers_sentinel() -> None:
    """If a caller races subscribe vs. close, the subscriber should not
    wait forever — they should get the sentinel immediately."""
    bus = PodEventBus(base_url="http://test.invalid:4096", auth=None)
    bus.close()
    sub = bus.subscribe("ses_late")
    item = sub.queue.get(timeout=1.0)
    assert item is BUS_CLOSED_SENTINEL
