"""Store explicit Stop requests in the tenant-aware cache."""

from uuid import UUID

from onyx.cache.interface import CacheBackend

STOP_TTL = 10 * 60


def _stop_key(chat_session_id: UUID) -> str:
    # Preserve the deployed cache key across API replicas.
    return f"chatsessionstop_fence_{chat_session_id}"


def request_stop(chat_session_id: UUID, cache: CacheBackend) -> None:
    cache.set(_stop_key(chat_session_id), 0, ex=STOP_TTL)


def clear_stop(chat_session_id: UUID, cache: CacheBackend) -> None:
    cache.delete(_stop_key(chat_session_id))


def is_stop_requested(chat_session_id: UUID, cache: CacheBackend) -> bool:
    return cache.exists(_stop_key(chat_session_id))
