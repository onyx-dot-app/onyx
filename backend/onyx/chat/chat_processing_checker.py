from uuid import UUID

from redis.client import Redis

# Redis key prefices for chat message processing
PREFIX = "chatprocessing"
FENCE_PREFIX = f"{PREFIX}_fence"
FENCE_TTL = 30 * 60  # 30 minutes


def _get_fence_key(chat_session_id: UUID) -> str:
    """
    Generate the Redis key for a chat session processing a message.

    Args:
            chat_session_id: The UUID of the chat session

    Returns:
            The fence key string (tenant_id is automatically added by the Redis client)
    """
    return f"{FENCE_PREFIX}_{chat_session_id}"


def set_processing_status(
    chat_session_id: UUID, redis_client: Redis, value: bool
) -> None:
    """
    Set or clear the fence for a chat session processing a message.

    If the key exists, we are processing a message. If the key does not exist, we are not processing a message.

    Args:
            chat_session_id: The UUID of the chat session
            redis_client: The Redis client to use
            value: True to set the fence, False to clear it
    """
    fence_key = _get_fence_key(chat_session_id)

    if value:
        redis_client.set(fence_key, 0, ex=FENCE_TTL)
    else:
        redis_client.delete(fence_key)


def is_chat_session_processing(chat_session_id: UUID, redis_client: Redis) -> bool:
    """
    Check if the chat session is processing a message.

    Args:
            chat_session_id: The UUID of the chat session
            redis_client: The Redis client to use

    Returns:
            True if the chat session is processing a message, False otherwise
    """
    fence_key = _get_fence_key(chat_session_id)
    return not bool(redis_client.exists(fence_key))


def reset_cancel_status(chat_session_id: UUID, redis_client: Redis) -> None:
    """
    Reset the cancel status for a chat session processing a message.

    Args:
            chat_session_id: The UUID of the chat session
            redis_client: The Redis client to use
    """
    fence_key = _get_fence_key(chat_session_id)
    redis_client.delete(fence_key)
