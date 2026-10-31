"""Unit tests for chat cancellation and chat_processing_checker.

These modules are safety-critical — they control whether a chat stream
continues or stops.  The tests use a simple in-memory CacheBackend stub
so no external services are needed.
"""

import builtins
import contextvars
import threading
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError

from onyx.cache.interface import CacheBackend, CacheLock, CacheLockLostError
from onyx.cache.redis_backend import RedisCacheBackend
from onyx.chat.chat_processing_checker import (
    ACTIVE_LEASE_SECONDS,
    PREPARATION_LEASE_SECONDS,
    ChatTurnAdmission,
    get_processing_stream_id,
    is_chat_session_processing,
)
from onyx.chat.stop_signal_checker import (
    STOP_TTL,
    clear_stop,
    is_stop_requested,
    request_stop,
)
from onyx.redis.tenant_redis_client import TenantRedisClient


class _MemoryCacheBackend(CacheBackend):
    """Minimal in-memory CacheBackend for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.sets: dict[str, set[bytes]] = {}
        self._ttls: dict[str, int] = {}

    def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    def getdel(self, key: str) -> bytes | None:
        self._ttls.pop(key, None)
        return self._store.pop(key, None)

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        self._ttls[key] = ex if ex is not None else -1
        if isinstance(value, bytes):
            self._store[key] = value
        else:
            self._store[key] = str(value).encode()

    def set_if_absent(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> bool:
        if key in self._store:
            return False
        self.set(key, value, ex=ex)
        return True

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._ttls.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        for key in list(self._store):
            if key.startswith(prefix):
                self.delete(key)

    def exists_many(self, keys: Collection[str]) -> builtins.set[str]:
        return {key for key in keys if key in self._store}

    def set_add(self, key: str, member: str | bytes) -> None:
        value = member if isinstance(member, bytes) else member.encode()
        self.sets.setdefault(key, set()).add(value)

    def set_remove(self, key: str, member: str | bytes) -> None:
        value = member if isinstance(member, bytes) else member.encode()
        self.sets.get(key, set()).discard(value)

    def set_members(self, key: str, *, limit: int) -> list[bytes]:
        if limit < 1:
            raise ValueError("Cache set member limit must be positive")
        return list(self.sets.get(key, set()))[:limit]

    def exists(self, key: str) -> bool:
        return key in self._store

    def expire(self, key: str, seconds: int) -> None:
        if key in self._store:
            self._ttls[key] = seconds

    def renew_if_value(self, key: str, expected: bytes, seconds: int) -> bool:
        if self.get(key) != expected:
            return False
        self.expire(key, seconds)
        return True

    def ttl(self, key: str) -> int:
        return self._ttls.get(key, -2)

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        raise NotImplementedError

    def rpush(self, key: str, value: str | bytes) -> None:
        raise NotImplementedError

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        raise NotImplementedError


# ── chat cancellation ──────────────────────────────────────────────


class TestStopRequests:
    def test_request_stop_creates_key(self) -> None:
        cache = _AdmissionCache()
        sid = uuid4()
        request_stop(sid, cache, stream_id=10)
        assert is_stop_requested(sid, cache, stream_id=10)

    def test_clear_stop_removes_key(self) -> None:
        cache = _AdmissionCache()
        sid = uuid4()
        request_stop(sid, cache, stream_id=10)
        clear_stop(sid, cache, stream_id=10)
        assert not is_stop_requested(sid, cache, stream_id=10)

    def test_request_stop_uses_ttl(self) -> None:
        cache = _AdmissionCache()
        sid = uuid4()
        with patch.object(cache, "set", wraps=cache.set) as cache_set:
            request_stop(sid, cache, stream_id=10)
        cache_set.assert_called_once_with(
            f"chatsessionstop_fence_{sid}_10", 1, ex=STOP_TTL
        )


def test_delayed_stop_and_cleanup_cannot_affect_next_request() -> None:
    cache = _AdmissionCache()
    session_id = uuid4()
    admission = ChatTurnAdmission(cache)
    admission.claim(session_id)
    admission.publish(11)
    request_stop(session_id, cache, stream_id=10)
    assert not is_stop_requested(session_id, cache, stream_id=11)
    request_stop(session_id, cache, stream_id=11)
    clear_stop(session_id, cache, stream_id=10)
    assert is_stop_requested(session_id, cache, stream_id=11)


class TestIsStopRequested:
    def test_sessions_are_isolated(self) -> None:
        cache = _AdmissionCache()
        sid1, sid2 = uuid4(), uuid4()
        request_stop(sid1, cache, stream_id=10)
        assert is_stop_requested(sid1, cache, stream_id=10)
        assert not is_stop_requested(sid2, cache, stream_id=10)


# ── chat_processing_checker ──────────────────────────────────────────


class TestChatTurnAdmission:
    def test_set_true_marks_processing(self) -> None:
        cache = _AdmissionCache()
        sid = uuid4()
        admission = ChatTurnAdmission(cache)
        admission.claim(sid)
        assert is_chat_session_processing(sid, cache)

    def test_set_false_clears_processing(self) -> None:
        cache = _AdmissionCache()
        sid = uuid4()
        admission = ChatTurnAdmission(cache)
        admission.claim(sid)
        admission.release()
        assert not is_chat_session_processing(sid, cache)


class TestIsChatSessionProcessing:
    def test_sessions_are_isolated(self) -> None:
        cache = _AdmissionCache()
        sid1, sid2 = uuid4(), uuid4()
        ChatTurnAdmission(cache).claim(sid1)
        assert is_chat_session_processing(sid1, cache)
        assert not is_chat_session_processing(sid2, cache)


class _ThreadCacheLock(CacheLock):
    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock

    def acquire(
        self, blocking: bool = True, blocking_timeout: float | None = None
    ) -> bool:
        return self._lock.acquire(
            blocking, blocking_timeout if blocking_timeout is not None else -1
        )

    def release(self) -> None:
        self._lock.release()

    def extend(self, ttl_seconds: float) -> None:
        del ttl_seconds
        raise NotImplementedError

    def owned(self) -> bool:
        return self._lock.locked()


class _AdmissionCache(_MemoryCacheBackend):
    def __init__(self) -> None:
        super().__init__()
        self._admission_lock = threading.Lock()

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        del name, timeout
        return _ThreadCacheLock(self._admission_lock)


def test_concurrent_admission_rejects_one_turn_before_stream_assignment() -> None:
    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import OnyxError

    cache = _AdmissionCache()
    session_id = uuid4()
    admissions = [ChatTurnAdmission(cache), ChatTurnAdmission(cache)]
    barrier = threading.Barrier(2)

    def claim(admission: ChatTurnAdmission) -> bool:
        barrier.wait()
        try:
            admission.claim(session_id)
            return True
        except OnyxError as error:
            assert error.error_code is OnyxErrorCode.CONFLICT
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        tasks = [
            workers.submit(contextvars.copy_context().run, claim, admission)
            for admission in admissions
        ]
        results = [cast(bool, task.result()) for task in tasks]
    assert sorted(results) == [False, True]
    assert is_chat_session_processing(session_id, cache)
    assert get_processing_stream_id(session_id, cache) is None
    winner = admissions[results.index(True)]
    winner.publish(17)
    assert get_processing_stream_id(session_id, cache) == 17
    winner.release()
    assert not is_chat_session_processing(session_id, cache)


def test_stale_turn_cannot_publish_refresh_or_release_new_admission() -> None:
    cache = _AdmissionCache()
    session_id = uuid4()
    old = ChatTurnAdmission(cache)
    old.claim(session_id)
    old.publish(17)
    # Simulate expiry before a different pod admits the next turn.
    cache._store.clear()
    new = ChatTurnAdmission(cache)
    new.claim(session_id)
    new.publish(18)
    with pytest.raises(CacheLockLostError):
        old.publish(17)
    with pytest.raises(CacheLockLostError):
        old.refresh()
    old.release()
    assert is_chat_session_processing(session_id, cache)
    assert get_processing_stream_id(session_id, cache) == 18
    new.refresh()
    new.release()
    assert not is_chat_session_processing(session_id, cache)


def test_missing_stream_marker_keeps_admitted_session_busy() -> None:
    cache = _AdmissionCache()
    session_id = uuid4()
    admission = ChatTurnAdmission(cache)
    admission.claim(session_id)
    cache.delete(f"chatprocessing_fence_{session_id}")
    assert is_chat_session_processing(session_id, cache)
    admission.release()
    assert not is_chat_session_processing(session_id, cache)


def test_late_renewal_cannot_reclaim_expired_admission() -> None:
    cache = _AdmissionCache()
    admission = ChatTurnAdmission(cache)
    admission.claim(uuid4())
    with patch(
        "onyx.chat.chat_processing_checker.time.monotonic",
        return_value=admission._last_refresh + PREPARATION_LEASE_SECONDS,
    ):
        with pytest.raises(CacheLockLostError):
            admission.refresh()


@pytest.mark.parametrize("timeout_at", ["watch", "execute"])
def test_admission_retries_redis_renewal_timeout(timeout_at: str) -> None:
    cache = _AdmissionCache()
    admission = ChatTurnAdmission(cache)
    session_id = uuid4()
    admission.claim(session_id)
    owner_key = f"chatprocessing_owner_{session_id}"
    token = cache.get(owner_key)
    redis = MagicMock(spec=Redis)
    pipeline = redis.pipeline.return_value.__enter__.return_value
    pipeline.get.return_value = token
    executions = 0

    def execute() -> list[bool]:
        nonlocal executions
        executions += 1
        cache.expire(owner_key, PREPARATION_LEASE_SECONDS)
        if timeout_at == "execute" and executions == 1:
            raise RedisTimeoutError("Renewal reply was lost")
        return [True]

    pipeline.execute.side_effect = execute
    if timeout_at == "watch":
        pipeline.watch.side_effect = [RedisTimeoutError("WATCH timed out"), None]
    backend = RedisCacheBackend(TenantRedisClient("tenant", redis))
    try:
        with patch.object(
            cache, "renew_if_value", side_effect=backend.renew_if_value
        ) as renew:
            admission.refresh()
        assert renew.call_count == 2
        assert all(
            call.args == (owner_key, token, PREPARATION_LEASE_SECONDS)
            for call in renew.call_args_list
        )
        assert pipeline.watch.call_count == 2
        pipeline.get.assert_called_with(f"tenant:{owner_key}")
        assert cache.get(owner_key) == token
        assert cache.ttl(owner_key) == PREPARATION_LEASE_SECONDS
    finally:
        admission.release()


def test_admission_renewal_retry_is_bounded() -> None:
    cache = _AdmissionCache()
    admission = ChatTurnAdmission(cache)
    admission.claim(uuid4())
    last_refresh = admission._last_refresh
    try:
        with patch.object(
            cache, "renew_if_value", side_effect=RedisTimeoutError("Cache unavailable")
        ) as renew:
            with pytest.raises(RedisTimeoutError):
                admission.refresh()
        assert renew.call_count == 2
        assert admission._last_refresh == last_refresh
    finally:
        admission.release()


@pytest.mark.parametrize("lease_expired", [False, True])
def test_admission_retry_cannot_reclaim_lost_ownership(lease_expired: bool) -> None:
    cache = _AdmissionCache()
    admission = ChatTurnAdmission(cache)
    session_id = uuid4()
    admission.claim(session_id)
    owner_key = f"chatprocessing_owner_{session_id}"
    original_renew = cache.renew_if_value
    attempts = 0

    def renew(key: str, expected: bytes, seconds: int) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if lease_expired:
                admission._last_refresh -= PREPARATION_LEASE_SECONDS
            else:
                cache.set(owner_key, b"replacement", ex=PREPARATION_LEASE_SECONDS)
            raise RedisTimeoutError("Renewal timed out")
        return original_renew(key, expected, seconds)

    try:
        with patch.object(cache, "renew_if_value", side_effect=renew):
            with pytest.raises(CacheLockLostError):
                admission.refresh()
        assert attempts == (1 if lease_expired else 2)
        if not lease_expired:
            assert cache.get(owner_key) == b"replacement"
    finally:
        admission.release()


def test_claim_write_timeout_can_release_its_own_admission() -> None:
    cache = _AdmissionCache()
    session_id = uuid4()
    admission = ChatTurnAdmission(cache)
    original_set = cache.set_if_absent

    def write_then_raise(
        key: str, value: str | bytes | int | float, ex: int | None = None
    ) -> bool:
        original_set(key, value, ex)
        raise TimeoutError("Claim reply was lost")

    with patch.object(cache, "set_if_absent", side_effect=write_then_raise):
        with pytest.raises(TimeoutError):
            admission.claim(session_id)
    assert is_chat_session_processing(session_id, cache)
    admission.release()
    assert not is_chat_session_processing(session_id, cache)


def test_published_turn_renews_both_keys_with_short_lease() -> None:
    cache = _AdmissionCache()
    session_id = uuid4()
    admission = ChatTurnAdmission(cache)
    admission.claim(session_id)
    owner_key = f"chatprocessing_owner_{session_id}"
    marker_key = f"chatprocessing_fence_{session_id}"
    assert cache.ttl(owner_key) == PREPARATION_LEASE_SECONDS
    assert cache.ttl(marker_key) == PREPARATION_LEASE_SECONDS
    admission.publish(17)
    assert cache.ttl(owner_key) == ACTIVE_LEASE_SECONDS
    assert cache.ttl(marker_key) == ACTIVE_LEASE_SECONDS
    cache.expire(owner_key, 20)
    cache.expire(marker_key, 20)
    admission.refresh()
    assert cache.ttl(owner_key) == ACTIVE_LEASE_SECONDS
    assert cache.ttl(marker_key) == ACTIVE_LEASE_SECONDS
    with patch(
        "onyx.chat.chat_processing_checker.time.monotonic",
        return_value=admission._last_refresh + ACTIVE_LEASE_SECONDS,
    ):
        with pytest.raises(CacheLockLostError):
            admission.refresh()
    admission.release()


def test_expired_owner_ignores_stale_marker_and_allows_next_turn() -> None:
    cache = _AdmissionCache()
    session_id = uuid4()
    old = ChatTurnAdmission(cache)
    old.claim(session_id)
    old.publish(17)
    # Publication can shorten the owner lease before its marker write completes.
    cache.expire(f"chatprocessing_fence_{session_id}", PREPARATION_LEASE_SECONDS)
    cache.delete(f"chatprocessing_owner_{session_id}")
    assert not is_chat_session_processing(session_id, cache)
    assert get_processing_stream_id(session_id, cache) is None
    new = ChatTurnAdmission(cache)
    new.claim(session_id)
    assert get_processing_stream_id(session_id, cache) is None
    new.publish(18)
    old.release()
    assert get_processing_stream_id(session_id, cache) == 18
    new.release()
