from uuid import UUID

from redis.client import Redis

from onyx.redis.redis_pool import get_redis_client
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
    # TODO: figure out dependency injection for redis client
    whack_redis_client = get_redis_client()
    if not value:
        whack_redis_client.delete(fence_key)
        return

    whack_redis_client.set(fence_key, 0)


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
    # TODO: figure out dependency injection for redis client
    whack_redis_client = get_redis_client()
    # Return True if NOT fenced (i.e., no stop signal set)
    return not bool(whack_redis_client.exists(fence_key))


def reset(chat_session_id: UUID, redis_client: Redis) -> None:
    """
    Clear the stop signal for a chat session.

    Args:
        chat_session_id: The UUID of the chat session
        redis_client: Redis client to use
    """
    tenant_id = get_current_tenant_id()
    fence_key = f"{FENCE_PREFIX}_{tenant_id}_{chat_session_id}"
    # TODO: figure out dependency injection for redis client
    whack_redis_client = get_redis_client()
    whack_redis_client.delete(fence_key)
