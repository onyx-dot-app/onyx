import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock, CacheLockLostError
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.configs import SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS
from onyx.server.features.build.db.build_session import get_orphan_build_session_ids
from onyx.server.features.build.db.sandbox import (
    fail_stale_provisioning__no_commit,
    get_sandbox_by_id,
    get_stale_provisioning_sandboxes,
    record_cleanup_checkpoint__no_commit,
    user_has_build_sessions,
)
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.locks import sandbox_provision_lock
from onyx.server.features.build.sandbox.models import (
    SandboxCleanupCheckpoint,
    SandboxProvisionContentionError,
    SandboxResourceKind,
)
from onyx.server.features.build.session.locks import session_creation_lock
from onyx.server.features.build.timeouts import (
    ATTEMPT_DEADLINE_SECONDS,
    RUNTIME_TEARDOWN_SECONDS,
    SESSION_FLOW_LOCK_LEASE_SECONDS,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()
RESOURCE_GRACE_SECONDS = 15 * 60
MAX_CLEANUP_RESOURCES = 100
RESOURCE_RETRY_SECONDS = max(60, SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS * 16)


def _check_resource_claim(
    claim: CacheLock, check_ownership: Callable[[], None]
) -> None:
    check_ownership()
    if not claim.owned():
        raise CacheLockLostError("Sandbox cleanup claim lost")
    claim.extend(SESSION_FLOW_LOCK_LEASE_SECONDS)


def _checkpoint_failed_runtime(
    manager: SandboxManager,
    sandbox_id: UUID,
    user_id: UUID,
    tenant_id: str,
    check_ownership: Callable[[], None],
) -> None:
    from onyx.server.features.build.session.sandbox_lifecycle import (
        create_session_snapshot_keep_latest,
    )

    check_ownership()
    if not manager.workspace_storage_exists(sandbox_id, tenant_id):
        return
    with session_creation_lock(user_id) as session_lock:

        def check_checkpoint_ownership() -> None:
            check_ownership()
            if not session_lock.owned():
                raise CacheLockLostError("Sandbox checkpoint session lock lost")
            session_lock.extend(
                math.ceil(SESSION_FLOW_LOCK_LEASE_SECONDS), replace_ttl=True
            )

        check_checkpoint_ownership()
        if manager.supports_opencode_history_persistence:
            manager.create_opencode_history_snapshot(sandbox_id, tenant_id)
            check_checkpoint_ownership()
        check_checkpoint_ownership()
        session_ids = manager.list_session_workspaces(sandbox_id)
        check_checkpoint_ownership()
        for session_id in session_ids:
            check_checkpoint_ownership()
            with get_session_with_current_tenant() as db_session:
                # Deleted sessions do not need preservation; other users' sessions
                # must never receive a snapshot from this runtime.
                if get_orphan_build_session_ids([session_id], user_id, db_session):
                    continue
                create_session_snapshot_keep_latest(
                    manager, db_session, sandbox_id, session_id, tenant_id
                )
            check_checkpoint_ownership()


def _prepare_failed_resource_cleanup(
    manager: SandboxManager,
    owner: Sandbox,
    tenant_id: str,
    deadline: float,
    claim: CacheLock,
    check_ownership: Callable[[], None],
) -> bool:
    sandbox_id = owner.id
    user_id = owner.user_id
    attempt_number = owner.provisioning_attempt_number
    checkpoint_heartbeat = owner.last_heartbeat
    checkpoint_proof = (
        SandboxCleanupCheckpoint.model_validate(owner.cleanup_checkpoint)
        if owner.cleanup_checkpoint is not None
        else None
    )
    current_resources = list(manager.iter_resources(tenant_id, deadline, sandbox_id))
    runtimes = [
        r
        for r in current_resources
        if r.kind in {SandboxResourceKind.POD, SandboxResourceKind.CONTAINER}
    ]
    needs_checkpoint = any(
        r.provisioning_attempt_number != attempt_number for r in runtimes
    ) or any(r.kind == SandboxResourceKind.VOLUME for r in current_resources)
    storage_identity = manager.workspace_storage_identity(sandbox_id, tenant_id)
    resume_deletion = (
        checkpoint_proof is not None
        and checkpoint_proof.provisioning_attempt_number == attempt_number
        and checkpoint_proof.storage_identity == storage_identity
        and checkpoint_proof.last_heartbeat == checkpoint_heartbeat
        and not manager.runtime_exists(sandbox_id, tenant_id)
    )
    if needs_checkpoint and not resume_deletion:
        _checkpoint_failed_runtime(
            manager,
            sandbox_id,
            user_id,
            tenant_id,
            lambda: _check_resource_claim(claim, check_ownership),
        )
        _check_resource_claim(claim, check_ownership)
        if (
            manager.workspace_storage_identity(sandbox_id, tenant_id)
            != storage_identity
        ):
            return False
        if storage_identity is not None:
            with get_session_with_current_tenant() as db_session:
                if not record_cleanup_checkpoint__no_commit(
                    db_session,
                    sandbox_id,
                    SandboxCleanupCheckpoint(
                        provisioning_attempt_number=attempt_number,
                        storage_identity=storage_identity,
                        last_heartbeat=checkpoint_heartbeat,
                    ),
                    expected_status=SandboxStatus.FAILED,
                ):
                    db_session.rollback()
                    return False
                db_session.commit()
    with get_session_with_current_tenant() as db_session:
        current = get_sandbox_by_id(db_session, sandbox_id)
        if (
            current is None
            or current.status != SandboxStatus.FAILED
            or current.provisioning_attempt_number != attempt_number
            or current.last_heartbeat != checkpoint_heartbeat
        ):
            return False
    return True


def _prepare_failed_resource_cleanup(
    manager: SandboxManager,
    owner: Sandbox,
    tenant_id: str,
    deadline: float,
    claim: CacheLock,
    check_ownership: Callable[[], None],
) -> bool:
    sandbox_id = owner.id
    user_id = owner.user_id
    attempt_number = owner.provisioning_attempt_number
    checkpoint_heartbeat = owner.last_heartbeat
    checkpoint_proof = (
        SandboxCleanupCheckpoint.model_validate(owner.cleanup_checkpoint)
        if owner.cleanup_checkpoint is not None
        else None
    )
    current_resources = list(manager.iter_resources(tenant_id, deadline, sandbox_id))
    runtimes = [
        r
        for r in current_resources
        if r.kind in {SandboxResourceKind.POD, SandboxResourceKind.CONTAINER}
    ]
    needs_checkpoint = any(
        r.provisioning_attempt_number != attempt_number for r in runtimes
    ) or any(r.kind == SandboxResourceKind.VOLUME for r in current_resources)
    storage_identity = manager.workspace_storage_identity(sandbox_id, tenant_id)
    resume_deletion = (
        checkpoint_proof is not None
        and checkpoint_proof.provisioning_attempt_number == attempt_number
        and checkpoint_proof.storage_identity == storage_identity
        and checkpoint_proof.last_heartbeat == checkpoint_heartbeat
        and not manager.runtime_exists(sandbox_id, tenant_id)
    )
    if needs_checkpoint and not resume_deletion:
        _checkpoint_failed_runtime(
            manager,
            sandbox_id,
            user_id,
            tenant_id,
            lambda: _check_resource_claim(claim, check_ownership),
        )
        _check_resource_claim(claim, check_ownership)
        if (
            manager.workspace_storage_identity(sandbox_id, tenant_id)
            != storage_identity
        ):
            return False
        if storage_identity is not None:
            with get_session_with_current_tenant() as db_session:
                if not record_cleanup_checkpoint__no_commit(
                    db_session,
                    sandbox_id,
                    SandboxCleanupCheckpoint(
                        provisioning_attempt_number=attempt_number,
                        storage_identity=storage_identity,
                        last_heartbeat=checkpoint_heartbeat,
                    ),
                    expected_status=SandboxStatus.FAILED,
                ):
                    db_session.rollback()
                    return False
                db_session.commit()
    with get_session_with_current_tenant() as db_session:
        current = get_sandbox_by_id(db_session, sandbox_id)
        if (
            current is None
            or current.status != SandboxStatus.FAILED
            or current.provisioning_attempt_number != attempt_number
            or current.last_heartbeat != checkpoint_heartbeat
        ):
            return False
    return True


def reconcile_sandbox_resources(
    manager: SandboxManager,
    tenant_id: str,
    deadline: float,
    check_ownership: Callable[[], None],
) -> None:
    """Collect abandoned resources using successful, current DB reads as evidence."""
    if get_current_tenant_id() != tenant_id:
        raise RuntimeError("Sandbox cleanup tenant context mismatch")
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
    verified_owners: set[UUID] = set()
    for resource in manager.iter_resources(tenant_id, deadline):
        check_ownership()
        if not resource.legacy_ownership and resource.tenant_id == tenant_id:
            verified_owners.add(resource.sandbox_id)
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
                    checkpoint_owner: Sandbox | None = None
                    if (
                        sandbox is None
                        and resource.legacy_ownership
                        and resource.sandbox_id not in verified_owners
                    ):
                        logger.warning(
                            "Retaining legacy resource %s without verified tenant ownership",
                            resource.name,
                        )
                        continue
                    if sandbox is not None:
                        if sandbox.status not in {
                            SandboxStatus.FAILED,
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
                        if (
                            sandbox.status == SandboxStatus.FAILED
                            and user_has_build_sessions(db_session, sandbox.user_id)
                        ):
                            checkpoint_owner = sandbox
                if (
                    checkpoint_owner is not None
                    and not _prepare_failed_resource_cleanup(
                        manager,
                        checkpoint_owner,
                        tenant_id,
                        deadline,
                        claim,
                        check_ownership,
                    )
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
