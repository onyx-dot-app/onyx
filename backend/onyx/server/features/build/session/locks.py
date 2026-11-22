from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.configs.constants import OnyxRedisLocks
from onyx.server.features.build.timeouts import SESSION_FLOW_LOCK_LEASE_SECONDS
from shared_configs.contextvars import get_current_tenant_id

# How long a creator blocks on another create/reap of the same user's sandbox.
SESSION_FLOW_LOCK_WAIT_SECONDS = 60


class SessionCreationLockAcquisitionError(RuntimeError):
    """Raised when session creation cannot acquire its per-user lock."""


def get_session_creation_lock(tenant_id: str, user_id: UUID) -> CacheLock:
    return get_cache_backend(tenant_id=tenant_id).lock(
        f"{OnyxRedisLocks.SESSION_CREATE_LOCK_PREFIX}:{user_id}",
        timeout=SESSION_FLOW_LOCK_LEASE_SECONDS,
    )


@contextmanager
def session_creation_lock(user_id: UUID) -> Generator[CacheLock, None, None]:
    """Serialize session creation for one user in the current tenant."""
    lock = get_session_creation_lock(get_current_tenant_id(), user_id)
    if not lock.acquire(
        blocking=True,
        blocking_timeout=SESSION_FLOW_LOCK_WAIT_SECONDS,
    ):
        raise SessionCreationLockAcquisitionError(
            f"Timed out waiting to create a session for user {user_id}"
        )

    try:
        yield lock
    finally:
        if lock.owned():
            lock.release()
