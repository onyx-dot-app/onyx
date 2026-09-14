"""Unit tests for chat cancellation and chat_processing_checker.

These modules are safety-critical — they control whether a chat stream
continues or stops.  The tests use a simple in-memory CacheBackend stub
so no external services are needed.
"""

from unittest.mock import patch
from uuid import uuid4

from onyx.cache.interface import CacheBackend, CacheLock
from onyx.chat.cancellation import STOP_TTL, clear_stop, is_stop_requested, request_stop
from onyx.chat.chat_processing_checker import (
    is_chat_session_processing,
    set_processing_status,
)


class _MemoryCacheBackend(CacheBackend):
    """Minimal in-memory CacheBackend for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    def getdel(self, key: str) -> bytes | None:
        return self._store.pop(key, None)

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,  # noqa: ARG002
    ) -> None:
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

    def exists(self, key: str) -> bool:
        return key in self._store

    def expire(self, key: str, seconds: int) -> None:
        pass

    def ttl(self, key: str) -> int:
        return -2 if key not in self._store else -1

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        raise NotImplementedError

    def rpush(self, key: str, value: str | bytes) -> None:
        raise NotImplementedError

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        raise NotImplementedError


# ── chat cancellation ──────────────────────────────────────────────


class TestStopRequests:
    def test_request_stop_creates_key(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        request_stop(sid, cache)
        assert is_stop_requested(sid, cache)

    def test_clear_stop_removes_key(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        request_stop(sid, cache)
        clear_stop(sid, cache)
        assert not is_stop_requested(sid, cache)

    def test_clear_stop_noop_when_absent(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        clear_stop(sid, cache)
        assert not is_stop_requested(sid, cache)

    def test_request_stop_uses_ttl(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        with patch.object(cache, "set", wraps=cache.set) as cache_set:
            request_stop(sid, cache)
        cache_set.assert_called_once_with(
            f"chatsessionstop_fence_{sid}", 0, ex=STOP_TTL
        )


class TestIsStopRequested:
    def test_no_request_by_default(self) -> None:
        cache = _MemoryCacheBackend()
        assert not is_stop_requested(uuid4(), cache)

    def test_sessions_are_isolated(self) -> None:
        cache = _MemoryCacheBackend()
        sid1, sid2 = uuid4(), uuid4()
        request_stop(sid1, cache)
        assert is_stop_requested(sid1, cache)
        assert not is_stop_requested(sid2, cache)


# ── chat_processing_checker ──────────────────────────────────────────


class TestSetProcessingStatus:
    def test_set_true_marks_processing(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        set_processing_status(sid, cache, True)
        assert is_chat_session_processing(sid, cache)

    def test_set_false_clears_processing(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        set_processing_status(sid, cache, True)
        set_processing_status(sid, cache, False)
        assert not is_chat_session_processing(sid, cache)


class TestIsChatSessionProcessing:
    def test_not_processing_by_default(self) -> None:
        cache = _MemoryCacheBackend()
        assert not is_chat_session_processing(uuid4(), cache)

    def test_sessions_are_isolated(self) -> None:
        cache = _MemoryCacheBackend()
        sid1, sid2 = uuid4(), uuid4()
        set_processing_status(sid1, cache, True)
        assert is_chat_session_processing(sid1, cache)
        assert not is_chat_session_processing(sid2, cache)
