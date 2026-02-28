"""Unit tests for stop_signal_checker and chat_processing_checker.

These modules are safety-critical — they control whether a chat stream
continues or stops.  The tests use a simple in-memory CacheBackend stub
so no external services are needed.
"""

from uuid import uuid4

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheLock
from onyx.chat.chat_processing_checker import is_chat_session_processing
from onyx.chat.chat_processing_checker import set_processing_status
from onyx.chat.stop_signal_checker import FENCE_TTL
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.stop_signal_checker import reset_cancel_status
from onyx.chat.stop_signal_checker import set_fence


class _MemoryCacheBackend(CacheBackend):
    """Minimal in-memory CacheBackend for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._store.get(key)

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


# ── stop_signal_checker ──────────────────────────────────────────────


class TestSetFence:
    def test_set_fence_true_creates_key(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        set_fence(sid, cache, True)
        assert not is_connected(sid, cache)

    def test_set_fence_false_removes_key(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        set_fence(sid, cache, True)
        set_fence(sid, cache, False)
        assert is_connected(sid, cache)

    def test_set_fence_false_noop_when_absent(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        set_fence(sid, cache, False)
        assert is_connected(sid, cache)

    def test_set_fence_uses_ttl(self) -> None:
        """Verify set_fence passes ex=FENCE_TTL to cache.set."""
        calls: list[dict[str, object]] = []
        cache = _MemoryCacheBackend()
        original_set = cache.set

        def tracking_set(
            key: str,
            value: str | bytes | int | float,
            ex: int | None = None,
        ) -> None:
            calls.append({"key": key, "ex": ex})
            original_set(key, value, ex=ex)

        cache.set = tracking_set  # type: ignore[assignment]

        set_fence(uuid4(), cache, True)
        assert len(calls) == 1
        assert calls[0]["ex"] == FENCE_TTL


class TestIsConnected:
    def test_connected_when_no_fence(self) -> None:
        cache = _MemoryCacheBackend()
        assert is_connected(uuid4(), cache)

    def test_disconnected_when_fence_set(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        set_fence(sid, cache, True)
        assert not is_connected(sid, cache)

    def test_sessions_are_isolated(self) -> None:
        cache = _MemoryCacheBackend()
        sid1, sid2 = uuid4(), uuid4()
        set_fence(sid1, cache, True)
        assert not is_connected(sid1, cache)
        assert is_connected(sid2, cache)


class TestResetCancelStatus:
    def test_clears_fence(self) -> None:
        cache = _MemoryCacheBackend()
        sid = uuid4()
        set_fence(sid, cache, True)
        reset_cancel_status(sid, cache)
        assert is_connected(sid, cache)

    def test_noop_when_no_fence(self) -> None:
        cache = _MemoryCacheBackend()
        reset_cancel_status(uuid4(), cache)


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
