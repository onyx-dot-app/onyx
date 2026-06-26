from __future__ import annotations

from uuid import uuid4

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.server.features.build import connect_app
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


def _cache() -> CacheBackend:
    return get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)


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


def test_stash_then_load_roundtrips_pending() -> None:
    cache = _cache()
    request_id = f"connect-app-test-{uuid4()}"

    pending = connect_app.ConnectAppPending(
        build_session_id="bs-1",
        opencode_session_id="oc-1",
        perm_id="perm-1",
        directory="/workspace/sessions/bs-1",
    )
    connect_app.stash_pending(request_id, pending, cache)

    assert connect_app.load_pending(request_id, cache) == pending


def test_load_pending_missing_returns_none() -> None:
    cache = _cache()
    request_id = f"connect-app-test-{uuid4()}"

    assert connect_app.load_pending(request_id, cache) is None


def test_clear_pending_removes_the_context() -> None:
    """After answering, the context is cleared so a duplicate decision is a no-op."""
    cache = _cache()
    request_id = f"connect-app-test-{uuid4()}"

    connect_app.stash_pending(
        request_id,
        connect_app.ConnectAppPending(
            build_session_id="bs-1",
            opencode_session_id="oc-1",
            perm_id="perm-1",
            directory="/workspace/sessions/bs-1",
        ),
        cache,
    )
    connect_app.clear_pending(request_id, cache)

    assert connect_app.load_pending(request_id, cache) is None
