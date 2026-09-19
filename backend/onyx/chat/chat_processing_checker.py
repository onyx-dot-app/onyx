from uuid import UUID

from onyx.cache.interface import CacheBackend
from onyx.utils.logger import setup_logger

logger = setup_logger()

PREFIX = "chatprocessing"
FENCE_PREFIX = f"{PREFIX}_fence"
FENCE_TTL = 30 * 60  # 30 minutes


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
    run_id: int | None = None,
) -> None:
    """Set or clear the fence for a chat session processing a message.

    If the key exists, a message is being processed. The fence value carries the
    run id of the active stream buffer when known; 0 means unknown (legacy pods
    or pre-reservation failures) and reads as "in flight, not resumable".

    Args:
        chat_session_id: The UUID of the chat session
        cache: Tenant-aware cache backend
        value: True to set the fence, False to clear it
        run_id: Stream-buffer run id to expose to resume readers
    """
    fence_key = _get_fence_key(chat_session_id)
    if value:
        cache.set(fence_key, run_id if run_id is not None else 0, ex=FENCE_TTL)
    else:
        cache.delete(fence_key)


def get_processing_run_id(chat_session_id: UUID, cache: CacheBackend) -> int | None:
    """Run id of the session's in-flight stream buffer, or None when idle or the
    fence carries no run id."""
    raw = cache.get(_get_fence_key(chat_session_id))
    if raw is None:
        return None
    try:
        run_id = int(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    except (TypeError, ValueError, UnicodeDecodeError):
        logger.warning(
            "invalid processing run id for session %s: %r",
            chat_session_id,
            raw,
        )
        return None
    return run_id if run_id > 0 else None


def is_chat_session_processing(chat_session_id: UUID, cache: CacheBackend) -> bool:
    """Check if the chat session is processing a message.

    Args:
        chat_session_id: The UUID of the chat session
        cache: Tenant-aware cache backend

    Returns:
        True if the chat session is processing a message, False otherwise
    """
    return cache.exists(_get_fence_key(chat_session_id))
