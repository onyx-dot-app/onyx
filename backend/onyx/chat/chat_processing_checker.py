from uuid import UUID

from onyx.cache.interface import CacheBackend

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
    chat_session_id: UUID, cache: CacheBackend, value: bool
) -> None:
    """Set or clear the fence for a chat session processing a message.

    If the key exists, a message is being processed.

    Args:
        chat_session_id: The UUID of the chat session
        cache: Tenant-aware cache backend
        value: True to set the fence, False to clear it
    """
    fence_key = _get_fence_key(chat_session_id)
    if value:
        cache.set(fence_key, 0, ex=FENCE_TTL)
    else:
        cache.delete(fence_key)


def is_chat_session_processing(chat_session_id: UUID, cache: CacheBackend) -> bool:
    """Check if the chat session is processing a message.

    Args:
        chat_session_id: The UUID of the chat session
        cache: Tenant-aware cache backend

    Returns:
        True if the chat session is processing a message, False otherwise
    """
    return cache.exists(_get_fence_key(chat_session_id))
