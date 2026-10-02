"""Unit tests for chat cancellation and chat_processing_checker.

These modules are safety-critical — they control whether a chat stream
continues or stops.  The tests use a simple in-memory CacheBackend stub
so no external services are needed.
"""

import threading
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.cache.interface import CacheBackend, CacheLock, CacheLockLostError
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
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor


class _MemoryCacheBackend(CacheBackend):
    """Minimal in-memory CacheBackend for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
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

    with ContextThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(claim, admissions))
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
        return_value=admission._last_refresh + 1800,
    ):
        with pytest.raises(CacheLockLostError):
            admission.refresh()


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
