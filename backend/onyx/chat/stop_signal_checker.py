from uuid import UUID

from redis.client import Redis

from shared_configs.contextvars import get_current_tenant_id

# Redis key prefixes for chat session stop signals
PREFIX = "chatsessionstop"
FENCE_PREFIX = f"{PREFIX}_fence"


def set_fence(chat_session_id: UUID, redis_client: Redis, value: bool) -> None:
    """
    Set or clear the stop signal fence for a chat session.

    Args:
        chat_session_id: The UUID of the chat session
        redis_client: Redis client to use
        value: True to set the fence (stop signal), False to clear it
    """
    tenant_id = get_current_tenant_id()
    fence_key = f"{FENCE_PREFIX}_{tenant_id}_{chat_session_id}"
    if not value:
        redis_client.delete(fence_key)
        return

    redis_client.set(fence_key, 0)


def is_connected(chat_session_id: UUID, redis_client: Redis) -> bool:
    """
    Check if the chat session should continue (not stopped).

    Args:
        chat_session_id: The UUID of the chat session to check
        redis_client: Redis client to use for checking the stop signal

    Returns:
        True if the session should continue, False if it should stop
    """
    tenant_id = get_current_tenant_id()
    fence_key = f"{FENCE_PREFIX}_{tenant_id}_{chat_session_id}"
    return not bool(redis_client.exists(fence_key))


def reset_cancel_status(chat_session_id: UUID, redis_client: Redis) -> None:
    """
    Clear the stop signal for a chat session.

    Args:
        chat_session_id: The UUID of the chat session
        redis_client: Redis client to use
    """
    tenant_id = get_current_tenant_id()
    fence_key = f"{FENCE_PREFIX}_{tenant_id}_{chat_session_id}"
    redis_client.delete(fence_key)
