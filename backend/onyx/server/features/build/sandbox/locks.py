from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.server.features.build.sandbox.models import SandboxProvisionContentionError
from onyx.server.features.build.timeouts import PROVISION_DEADLINE_SECONDS


def provisioning_lock_key(sandbox_id: UUID) -> str:
    return f"sandbox_provision_{sandbox_id}"


@contextmanager
def sandbox_provision_lock(sandbox_id: UUID, tenant_id: str) -> Iterator[CacheLock]:
    """Serialize backend creation and cleanup. Cache failure must stop deletion."""
    lock = get_cache_backend(tenant_id=tenant_id).lock(
        provisioning_lock_key(sandbox_id),
        timeout=PROVISION_DEADLINE_SECONDS,
    )
    if not lock.acquire(blocking=False):
        raise SandboxProvisionContentionError(
            f"Sandbox {sandbox_id} is being provisioned or cleaned"
        )
    try:
        yield lock
    finally:
        if lock.owned():
            lock.release()
