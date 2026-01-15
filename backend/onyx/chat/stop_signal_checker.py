from uuid import UUID

from redis.client import Redis

# Redis key prefixes for chat session stop signals
PREFIX = "chatsessionstop"
FENCE_PREFIX = f"{PREFIX}_fence"
FENCE_TTL = 10 * 60  # 10 minutes - defensive TTL to prevent memory leaks


def _get_fence_key(chat_session_id: UUID) -> str:
    """
    Generate the Redis key for a chat session stop signal fence.

    Args:
        chat_session_id: The UUID of the chat session

    Returns:
        The fence key string (tenant_id is automatically added by the Redis client)
    """
    return f"{FENCE_PREFIX}_{chat_session_id}"


def set_fence(chat_session_id: UUID, redis_client: Redis, value: bool) -> None:
    """
    Set or clear the stop signal fence for a chat session.

    Args:
        chat_session_id: The UUID of the chat session
        redis_client: Redis client to use (tenant-aware client that auto-prefixes keys)
        value: True to set the fence (stop signal), False to clear it
    """
    fence_key = _get_fence_key(chat_session_id)
    if not value:
        redis_client.delete(fence_key)
        return

    redis_client.set(fence_key, 0, ex=FENCE_TTL)


def is_connected(chat_session_id: UUID, redis_client: Redis) -> bool:
    """
    Check if the chat session should continue (not stopped).

    Args:
        chat_session_id: The UUID of the chat session to check
        redis_client: Redis client to use for checking the stop signal (tenant-aware client that auto-prefixes keys)

    Returns:
        True if the session should continue, False if it should stop
    """
    fence_key = _get_fence_key(chat_session_id)
    return not bool(redis_client.exists(fence_key))


def reset_cancel_status(chat_session_id: UUID, redis_client: Redis) -> None:
    """
    Clear the stop signal for a chat session.

    Args:
        chat_session_id: The UUID of the chat session
        redis_client: Redis client to use (tenant-aware client that auto-prefixes keys)
    """
    fence_key = _get_fence_key(chat_session_id)
    redis_client.delete(fence_key)
