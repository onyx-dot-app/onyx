import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLockLostError
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS
from onyx.server.features.build.db.sandbox import (
    fail_stale_provisioning__no_commit,
    get_sandbox_by_id,
    get_stale_provisioning_sandboxes,
)
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.locks import sandbox_provision_lock
from onyx.server.features.build.sandbox.models import SandboxProvisionContentionError
from onyx.server.features.build.timeouts import (
    ATTEMPT_DEADLINE_SECONDS,
    RUNTIME_TEARDOWN_SECONDS,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()
RESOURCE_GRACE_SECONDS = 15 * 60
MAX_CLEANUP_RESOURCES = 100
RESOURCE_RETRY_SECONDS = max(60, SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS * 16)


def reconcile_sandbox_resources(
    manager: SandboxManager,
    tenant_id: str,
    deadline: float,
    check_ownership: Callable[[], None],
) -> None:
    """Collect abandoned resources using successful, current DB reads as evidence."""
    cache = get_cache_backend(tenant_id=tenant_id)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=ATTEMPT_DEADLINE_SECONDS
    )
    with get_session_with_current_tenant() as db_session:
        stale = [
            (row.id, row.provisioning_attempt_number)
            for row in get_stale_provisioning_sandboxes(
                db_session, stale_cutoff, MAX_CLEANUP_RESOURCES
            )
        ]
    for sandbox_id, attempt_number in stale:
        check_ownership()
        try:
            with sandbox_provision_lock(sandbox_id, tenant_id):
                with get_session_with_current_tenant() as db_session:
                    fail_stale_provisioning__no_commit(
                        db_session, sandbox_id, attempt_number, stale_cutoff
                    )
                    db_session.commit()
        except SandboxProvisionContentionError:
            continue

    grace_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=RESOURCE_GRACE_SECONDS
    )
    attempted = 0
    for resource in manager.iter_resources(tenant_id, deadline):
        check_ownership()
        if resource.tenant_id != tenant_id or resource.created_at > grace_cutoff:
            continue
        retry_key = (
            f"sandbox_cleanup_retry:{resource.kind.value}:{resource.instance_id}"
        )
        if cache.get(retry_key) is not None:
            continue
        try:
            with sandbox_provision_lock(resource.sandbox_id, tenant_id) as claim:
                # Read after acquiring the creation lock. A failed DB read must
                # escape without authorizing orphan deletion.
                with get_session_with_current_tenant() as db_session:
                    sandbox = get_sandbox_by_id(db_session, resource.sandbox_id)
                    if sandbox is not None:
                        if sandbox.status not in {
                            SandboxStatus.SLEEPING,
                            SandboxStatus.TERMINATED,
                        }:
                            continue
                        if (
                            resource.provisioning_attempt_number is not None
                            and resource.provisioning_attempt_number
                            > sandbox.provisioning_attempt_number
                        ):
                            continue
                check_ownership()
                if not claim.owned():
                    raise RuntimeError("Sandbox cleanup claim lost")
                attempted += 1
                manager.delete_resource(
                    resource, min(deadline, time.monotonic() + RUNTIME_TEARDOWN_SECONDS)
                )
                logger.info(
                    "Removed stale sandbox %s resource %s %s",
                    resource.sandbox_id,
                    resource.kind.value,
                    resource.name,
                )
        except SandboxProvisionContentionError:
            continue
        except CacheLockLostError:
            raise
        except Exception:
            cache.set(retry_key, "retry", ex=RESOURCE_RETRY_SECONDS)
            logger.exception("Failed to reconcile sandbox resource %s", resource.name)
        if attempted >= MAX_CLEANUP_RESOURCES:
            break
