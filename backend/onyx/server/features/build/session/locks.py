from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID

from redis.lock import Lock as RedisLock

from onyx.configs.constants import OnyxRedisLocks
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.features.build.configs import (
    SESSION_CREATE_LOCK_LEASE_SECONDS,
    SESSION_CREATE_LOCK_WAIT_SECONDS,
)
from shared_configs.contextvars import get_current_tenant_id


class SessionCreationLockAcquisitionError(RuntimeError):
    """Raised when session creation cannot acquire its per-user lock."""


def get_session_creation_lock(
    redis_client: TenantRedisClient,
    user_id: UUID,
) -> RedisLock:
    return redis_client.lock(
        f"{OnyxRedisLocks.SESSION_CREATE_LOCK_PREFIX}:{user_id}",
        timeout=SESSION_CREATE_LOCK_LEASE_SECONDS,
    )


@contextmanager
def session_creation_lock(user_id: UUID) -> Generator[None, None, None]:
    """Serialize session creation for one user in the current tenant."""
    redis_client = get_redis_client(tenant_id=get_current_tenant_id())
    lock = get_session_creation_lock(redis_client, user_id)
    if not lock.acquire(
        blocking=True,
        blocking_timeout=SESSION_CREATE_LOCK_WAIT_SECONDS,
    ):
        raise SessionCreationLockAcquisitionError(
            f"Timed out waiting to create a session for user {user_id}"
        )

    try:
        yield
    finally:
        if lock.owned():
            lock.release()
