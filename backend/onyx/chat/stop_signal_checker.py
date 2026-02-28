from uuid import UUID

from onyx.cache.interface import CacheBackend

PREFIX = "chatsessionstop"
FENCE_PREFIX = f"{PREFIX}_fence"
FENCE_TTL = 10 * 60  # 10 minutes


def _get_fence_key(chat_session_id: UUID) -> str:
    """Generate the cache key for a chat session stop signal fence.

    Args:
        chat_session_id: The UUID of the chat session

    Returns:
        The fence key string. Tenant isolation is handled automatically
        by the cache backend (Redis key-prefixing or Postgres schema routing).
    """
    return f"{FENCE_PREFIX}_{chat_session_id}"


def set_fence(chat_session_id: UUID, cache: CacheBackend, value: bool) -> None:
    """Set or clear the stop signal fence for a chat session.

    Args:
        chat_session_id: The UUID of the chat session
        cache: Tenant-aware cache backend
        value: True to set the fence (stop signal), False to clear it
    """
    fence_key = _get_fence_key(chat_session_id)
    if not value:
        cache.delete(fence_key)
        return
    cache.set(fence_key, 0, ex=FENCE_TTL)


def is_connected(chat_session_id: UUID, cache: CacheBackend) -> bool:
    """Check if the chat session should continue (not stopped).

    Args:
        chat_session_id: The UUID of the chat session to check
        cache: Tenant-aware cache backend

    Returns:
        True if the session should continue, False if it should stop
    """
    return not cache.exists(_get_fence_key(chat_session_id))


def reset_cancel_status(chat_session_id: UUID, cache: CacheBackend) -> None:
    """Clear the stop signal for a chat session.

    Args:
        chat_session_id: The UUID of the chat session
        cache: Tenant-aware cache backend
    """
    cache.delete(_get_fence_key(chat_session_id))
