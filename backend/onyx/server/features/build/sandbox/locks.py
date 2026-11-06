from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.server.features.build.sandbox.models import SandboxProvisionContentionError
from onyx.server.features.build.timeouts import PROVISION_DEADLINE_SECONDS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def provisioning_lock_key(sandbox_id: UUID) -> str:
    return f"sandbox_provision_{sandbox_id}"


@contextmanager
def sandbox_provision_lock(sandbox_id: UUID, tenant_id: str) -> Iterator[CacheLock]:
    """Serialize backend creation and cleanup. Acquisition errors stop the operation."""
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
        try:
            if lock.owned():
                lock.release()
        except Exception:
            logger.warning(
                "Failed to release sandbox %s provisioning lock",
                sandbox_id,
                exc_info=True,
            )
