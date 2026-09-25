"""Store Stop requests for an identified execution in the tenant-aware cache."""

from uuid import UUID

from onyx.cache.interface import CacheBackend

STOP_TTL = 10 * 60


def _stop_key(chat_session_id: UUID, processing_key: int) -> str:
    return f"chatsessionstop_fence_{chat_session_id}_{processing_key}"


def request_stop(
    chat_session_id: UUID, cache: CacheBackend, *, processing_key: int
) -> None:
    cache.set(_stop_key(chat_session_id, processing_key), 1, ex=STOP_TTL)


def clear_stop(
    chat_session_id: UUID, cache: CacheBackend, *, processing_key: int
) -> None:
    cache.delete(_stop_key(chat_session_id, processing_key))


def is_stop_requested(
    chat_session_id: UUID, cache: CacheBackend, *, processing_key: int
) -> bool:
    return cache.exists(_stop_key(chat_session_id, processing_key))
