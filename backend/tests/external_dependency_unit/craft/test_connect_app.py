"""Connect-app rendezvous over Redis: announce up, decision back.

These exercise the two channels the parked turn and the decision request use to
meet across workers — the announce (request → the live-stream worker) and the
single-shot decision latch (answer → the parked turn). Real Redis, no DB.
"""

from __future__ import annotations

from uuid import uuid4

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.server.features.build import connect_app
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


def _cache() -> CacheBackend:
    return get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)


def test_resolve_then_wait_returns_decision() -> None:
    cache = _cache()
    request_id = f"connect-app-test-{uuid4()}"
    cache.delete(connect_app._decision_key(request_id))  # type: ignore[attr-defined]

    connect_app.resolve(request_id, connect_app.ConnectAppDecision.CONNECTED, cache)
    decision = connect_app.wait_for_decision(request_id, timeout_s=5, cache=cache)

    assert decision is connect_app.ConnectAppDecision.CONNECTED


def test_wait_for_decision_times_out_to_none() -> None:
    cache = _cache()
    request_id = f"connect-app-test-{uuid4()}"
    cache.delete(connect_app._decision_key(request_id))  # type: ignore[attr-defined]

    assert connect_app.wait_for_decision(request_id, timeout_s=1, cache=cache) is None


def test_decision_is_single_shot() -> None:
    """The first waiter consumes the decision; a second wait times out."""
    cache = _cache()
    request_id = f"connect-app-test-{uuid4()}"
    cache.delete(connect_app._decision_key(request_id))  # type: ignore[attr-defined]

    connect_app.resolve(request_id, connect_app.ConnectAppDecision.DECLINED, cache)
    first = connect_app.wait_for_decision(request_id, timeout_s=5, cache=cache)
    second = connect_app.wait_for_decision(request_id, timeout_s=1, cache=cache)

    assert first is connect_app.ConnectAppDecision.DECLINED
    assert second is None


def test_announce_then_pop_roundtrips_request() -> None:
    cache = _cache()
    session_id = f"connect-app-test-{uuid4()}"
    cache.delete(connect_app._announce_key(session_id))  # type: ignore[attr-defined]

    request = connect_app.ConnectAppRequest(
        request_id="req-1", app_slug="google_calendar", reason="to schedule events"
    )
    connect_app.announce_request(session_id, request, cache)
    popped = connect_app.pop_announcement(session_id, timeout_s=5, cache=cache)

    assert popped == request


def test_pop_announcement_times_out_to_none() -> None:
    cache = _cache()
    session_id = f"connect-app-test-{uuid4()}"
    cache.delete(connect_app._announce_key(session_id))  # type: ignore[attr-defined]

    assert connect_app.pop_announcement(session_id, timeout_s=1, cache=cache) is None
