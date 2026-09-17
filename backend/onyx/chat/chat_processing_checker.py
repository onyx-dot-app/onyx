from uuid import UUID

from onyx.cache.interface import CacheBackend
from onyx.utils.logger import setup_logger

logger = setup_logger()

PREFIX = "chatprocessing"
FENCE_PREFIX = f"{PREFIX}_fence"
FENCE_TTL = 30 * 60  # Retain the buffer identity after a worker dies.
PROCESSING_REFRESH_INTERVAL_S = 5.0
PROCESSING_STALE_AFTER_S = 3 * PROCESSING_REFRESH_INTERVAL_S


def _get_fence_key(chat_session_id: UUID) -> str:
    """Generate the cache key for a chat session processing fence.

    Args:
        chat_session_id: The UUID of the chat session

    Returns:
        The fence key string. Tenant isolation is handled automatically
        by the cache backend (Redis key-prefixing or Postgres schema routing).
    """
    return f"{FENCE_PREFIX}_{chat_session_id}"


def set_processing_status(
    chat_session_id: UUID,
    cache: CacheBackend,
    value: bool,
    processing_key: int | None = None,
) -> None:
    """Set or clear the fence for a chat session processing a message.

    The marker retains the buffered response ID after a worker becomes inactive.
    Its remaining TTL determines liveness; 0 means no response ID is available.

    Args:
        chat_session_id: The UUID of the chat session
        cache: Tenant-aware cache backend
        value: True to set the fence, False to clear it
        processing_key: Stream-buffer run id to expose to resume readers
    """
    fence_key = _get_fence_key(chat_session_id)
    if value:
        cache.set(
            fence_key, processing_key if processing_key is not None else 0, ex=FENCE_TTL
        )
    else:
        cache.delete(fence_key)


def get_processing_key(chat_session_id: UUID, cache: CacheBackend) -> int | None:
    """Buffered response ID, retained for recovery after the worker becomes inactive."""
    raw = cache.get(_get_fence_key(chat_session_id))
    if raw is None:
        return None
    try:
        processing_key = int(
            raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        logger.warning(
            "invalid processing run id for session %s: %r",
            chat_session_id,
            raw,
        )
        return None
    return processing_key if processing_key > 0 else None


def is_chat_session_processing(chat_session_id: UUID, cache: CacheBackend) -> bool:
    """A worker must refresh its processing marker to remain live across pods."""
    remaining = cache.ttl(_get_fence_key(chat_session_id))
    return FENCE_TTL - PROCESSING_STALE_AFTER_S < remaining <= FENCE_TTL
