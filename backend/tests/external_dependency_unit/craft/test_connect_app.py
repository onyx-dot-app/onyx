from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.server.features.build import connect_app
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


def _cache() -> CacheBackend:
    return get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)


def test_announcement_lifecycle() -> None:
    cache = _cache()
    session_id = f"connect-app-test-{uuid4()}"
    cache.delete(connect_app._announce_key(session_id))

    request = connect_app.ConnectAppRequest(
        request_id="req-1", external_app_id=17, reason="to schedule events"
    )
    connect_app.announce_request(session_id, request, cache)
    popped = connect_app.pop_announcement(session_id, timeout_s=5, cache=cache)

    assert popped == request
    assert connect_app.pop_announcement(session_id, timeout_s=1, cache=cache) is None


def test_pending_context_lifecycle() -> None:
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
    connect_app.clear_pending(request_id, cache)

    assert connect_app.load_pending(request_id, cache) is None


def test_restore_consumed_requests_and_exclude_resolved_or_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _cache()
    session_id = str(uuid4())
    deadline = time.time() + 180
    requests = [
        connect_app.ConnectAppRequest(
            request_id=str(uuid4()),
            external_app_id=app_id,
            reason=f"Read app {app_id}",
        )
        for app_id in (17, 18)
    ]

    def stash(request: connect_app.ConnectAppRequest) -> None:
        connect_app.stash_pending(
            request.request_id,
            connect_app.ConnectAppPending(
                build_session_id=session_id,
                opencode_session_id="oc-1",
                perm_id=request.request_id,
                directory=f"/workspace/sessions/{session_id}",
                request=request,
                expires_at=deadline,
            ),
            cache,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(stash, requests))
        for request in requests:
            assert 0 < cache.ttl(connect_app._pending_key(request.request_id)) <= 180
            connect_app.announce_request(session_id, request, cache)
            assert connect_app.pop_announcement(session_id, 1, cache) == request

        # Both fresh attachments see the same cards, despite consumed announcements.
        for _ in range(2):
            restored = connect_app.list_pending_requests(session_id, cache)
            assert {request.request_id: request for request in restored} == {
                request.request_id: request for request in requests
            }
        assert connect_app.list_pending_requests(str(uuid4()), cache) == []

        connect_app.clear_pending(requests[0].request_id, cache)
        assert connect_app.list_pending_requests(session_id, cache) == [requests[1]]

        # A record can remain until the cache's rounded TTL expires.
        assert cache.get(connect_app._pending_key(requests[1].request_id)) is not None
        with monkeypatch.context() as clock:
            clock.setattr(connect_app.time, "time", lambda: deadline + 1)
            assert connect_app.load_pending(requests[1].request_id, cache) is None
            assert connect_app.list_pending_requests(session_id, cache) == []
    finally:
        for request in requests:
            connect_app.clear_pending(request.request_id, cache)
        cache.delete(connect_app._session_key(session_id))
        cache.delete(connect_app._announce_key(session_id))


def test_session_index_outlives_long_request_when_short_request_is_added() -> None:
    cache = _cache()
    session_id = str(uuid4())
    index_key = connect_app._session_key(session_id)
    requests = [
        connect_app.ConnectAppRequest(request_id=str(uuid4()), external_app_id=app_id)
        for app_id in (17, 18)
    ]
    long_ttl = connect_app._PENDING_TTL_S * 2
    try:
        for request, lifetime in zip(requests, (long_ttl, 180), strict=True):
            connect_app.stash_pending(
                request.request_id,
                connect_app.ConnectAppPending(
                    build_session_id=session_id,
                    opencode_session_id="oc-1",
                    perm_id=request.request_id,
                    directory=f"/workspace/sessions/{session_id}",
                    request=request,
                    expires_at=time.time() + lifetime,
                ),
                cache,
            )
            assert cache.ttl(index_key) >= cache.ttl(
                connect_app._pending_key(requests[0].request_id)
            )
            if request == requests[0]:
                # Older workers capped the index even when a request lived longer.
                cache.expire(index_key, connect_app._PENDING_TTL_S)

        assert {
            request.request_id
            for request in connect_app.list_pending_requests(session_id, cache)
        } == {request.request_id for request in requests}
    finally:
        for request in requests:
            connect_app.clear_pending(request.request_id, cache)
        cache.delete(index_key)
