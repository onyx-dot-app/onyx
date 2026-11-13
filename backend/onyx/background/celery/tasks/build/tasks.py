"""Celery tasks for sandbox operations (cleanup, etc.)."""

import datetime
import random
import time
from collections.abc import Callable
from functools import partial
from uuid import UUID

from celery import Task, shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock, CacheLockLostError
from onyx.configs.constants import OnyxCeleryTask, OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.server.features.build.configs import (
    ENABLE_CRAFT,
    SANDBOX_IDLE_TIMEOUT_SECONDS,
)
from onyx.server.features.build.db.sandbox import (
    get_latest_snapshot_for_session,
    get_running_sandboxes,
    user_has_stale_active_session,
)
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.session.resource_cleanup import (
    delete_unknown_tenant_resources,
    fail_stale_provisioning_sandboxes,
    reconcile_sandbox_resources,
)
from onyx.server.features.build.timeouts import (
    SANDBOX_CLEANUP_DEADLINE_SECONDS as TIMEOUT_SECONDS,
)
from onyx.server.features.build.timeouts import SESSION_FLOW_LOCK_LEASE_SECONDS
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# Background snapshots ride the idle timeout: a session is re-snapshotted when
# its latest snapshot is older than idle_timeout/4 (15 min at the default 1h),
# so the data-loss bound scales with the pace of sandboxes going to sleep.
SNAPSHOT_INTERVAL_DIVISOR = 4
RUNNING_SANDBOX_BATCH_SIZE = 100
RUNNING_SANDBOX_CURSOR_KEY = "sandbox_cleanup_running_cursor"


def _check_cleanup_lease(lock: CacheLock, deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("Sandbox cleanup deadline exceeded")
    if not lock.owned():
        raise CacheLockLostError("Sandbox cleanup lease lost")
    lock.extend(SESSION_FLOW_LOCK_LEASE_SECONDS)


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CLEANUP_IDLE_SANDBOXES,
    soft_time_limit=TIMEOUT_SECONDS,
    bind=True,
    ignore_result=True,
)
def cleanup_idle_sandboxes_task(self: Task, *, tenant_id: str) -> None:  # noqa: ARG001
    """Sweep one tenant from its database rows, without a runtime inventory.

    Reaches rows whose runtime may be gone, such as stale ``PROVISIONING`` rows
    and idle ``RUNNING`` rows. ``reconcile_sandbox_runtimes_task`` runs the same
    sweep, plus runtime removal, for every tenant that owns a live runtime,
    including tenants this fanout skips.
    """
    _sweep_tenant_sandboxes(
        tenant_id, time.monotonic() + TIMEOUT_SECONDS, reconcile_resources=False
    )


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.RECONCILE_SANDBOX_RUNTIMES,
    soft_time_limit=TIMEOUT_SECONDS,
    bind=True,
    ignore_result=True,
)
def reconcile_sandbox_runtimes_task(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str | None = None,  # noqa: ARG001
) -> None:
    """Check every live sandbox runtime against its tenant's database state.

    Each tenant that owns a runtime gets the full sweep, including removal of
    runtimes that no database row justifies, whether or not the per-tenant
    fanout reaches that tenant. In multi-tenant deployments, runtimes of
    tenants that no longer exist are deleted after the resource grace period.
    In single-tenant deployments, runtimes labelled with another tenant belong
    to another deployment and are retained.
    """
    if not ENABLE_CRAFT:
        return

    deadline = time.monotonic() + TIMEOUT_SECONDS
    sandbox_manager = get_sandbox_manager()
    # Resources created before tenant labels appear only in a tenant's own
    # inventory, so a single-tenant deployment always sweeps its tenant.
    always_swept = set() if MULTI_TENANT else {POSTGRES_DEFAULT_SCHEMA}
    owners = list(sandbox_manager.list_resource_tenant_ids(deadline) | always_swept)
    known_tenants = set(get_all_tenant_ids())
    # A slow tenant must not starve the same tenants on every run.
    random.shuffle(owners)
    failed: list[str] = []
    for owner in owners:
        if time.monotonic() >= deadline:
            # The shuffled order reaches the rest on a later run.
            break
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(owner)
        try:
            if owner in known_tenants:
                _sweep_tenant_sandboxes(owner, deadline, reconcile_resources=True)
            elif MULTI_TENANT:
                delete_unknown_tenant_resources(sandbox_manager, owner, deadline)
            else:
                task_logger.info(
                    "Retaining sandbox resources of foreign tenant %s", owner
                )
        except Exception:
            task_logger.exception("Sandbox reconciliation failed for tenant %s", owner)
            failed.append(owner)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    if failed:
        raise RuntimeError(f"Sandbox reconciliation failed for tenants {failed}")


def _expire_and_collect(
    sandbox_manager: SandboxManager,
    tenant_id: str,
    deadline: float,
    check_ownership: Callable[[], None],
    *,
    reconcile_resources: bool,
) -> list[Exception]:
    """Expire stale provisioning and optionally remove unjustified runtime
    resources. Returns failures instead of raising, so snapshots and idle
    cleanup still run, unless the sweep lease is lost."""
    try:
        fail_stale_provisioning_sandboxes(tenant_id, check_ownership)
        if reconcile_resources:
            reconcile_sandbox_resources(
                sandbox_manager, tenant_id, deadline, check_ownership
            )
    except Exception as e:
        check_ownership()
        task_logger.exception(
            "Resource reconciliation failed; continuing sandbox snapshots and idle cleanup"
        )
        return [e]
    return []


def _sweep_tenant_sandboxes(
    tenant_id: str, deadline: float, *, reconcile_resources: bool
) -> None:
    """Sweep one tenant: expire stale provisioning, optionally remove runtime
    resources that no row justifies, then background-snapshot sessions and
    sleep idle ``RUNNING`` sandboxes.

    Background snapshots bound data loss from ungraceful pod death (kubelet
    eviction, node loss, spot reclaim) to ~idle_timeout/SNAPSHOT_INTERVAL_DIVISOR:
    sessions whose latest snapshot is fresher than that interval are skipped
    without touching the pod (except at reap — the pod is about to die, so
    always snapshot).
    The reap itself is ``sleep_sandbox`` (sandbox lifecycle), which stays
    fail-closed: snapshot failure on a reachable pod keeps the sandbox
    RUNNING for retry next sweep.
    """
    from onyx.server.features.build.session.locks import get_session_creation_lock
    from onyx.server.features.build.session.sandbox_lifecycle import (
        create_session_snapshot_keep_latest,
        is_sandbox_idle,
        list_snapshotable_session_workspaces,
        sleep_sandbox,
    )

    task_logger.info(f"Sandbox sweep starting for tenant {tenant_id}")

    redis_client = get_redis_client(tenant_id=tenant_id)
    cache = get_cache_backend(tenant_id=tenant_id)
    lock = cache.lock(
        OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK,
        timeout=SESSION_FLOW_LOCK_LEASE_SECONDS,
    )

    # Prevent overlapping runs of this task
    if not lock.acquire(blocking=False):
        task_logger.info("Sandbox sweep - lock not acquired, skipping")
        return

    # Failures are collected so the rest of the sweep still runs, then raised
    # at the end so the task reports that sandboxes were left unreconciled.
    try:
        sandbox_manager = get_sandbox_manager()

        errors = _expire_and_collect(
            sandbox_manager,
            tenant_id,
            deadline,
            partial(_check_cleanup_lease, lock, deadline),
            reconcile_resources=reconcile_resources,
        )

        while True:
            with get_session_with_current_tenant() as db_session:
                _check_cleanup_lease(lock, deadline)
                cursor = cache.get(RUNNING_SANDBOX_CURSOR_KEY)
                running_sandboxes = get_running_sandboxes(
                    db_session,
                    after_id=UUID(cursor.decode()) if cursor else None,
                    limit=RUNNING_SANDBOX_BATCH_SIZE,
                )
                if not running_sandboxes:
                    cache.delete(RUNNING_SANDBOX_CURSOR_KEY)
                    task_logger.debug("No running sandboxes found")
                    break

                # Tenant-work-gating hook: refresh this tenant's active-set
                # membership whenever the sweep has work to do.
                maybe_mark_tenant_active(tenant_id, caller="sandbox_cleanup")

                now = datetime.datetime.now(datetime.timezone.utc)
                snapshot_cutoff = now - datetime.timedelta(
                    seconds=SANDBOX_IDLE_TIMEOUT_SECONDS // SNAPSHOT_INTERVAL_DIVISOR
                )

                for sandbox in running_sandboxes:
                    _check_cleanup_lease(lock, deadline)
                    sandbox_id = sandbox.id

                    try:
                        if is_sandbox_idle(sandbox, now):
                            session_creation_lock = get_session_creation_lock(
                                redis_client, sandbox.user_id
                            )
                            sleep_sandbox(
                                db_session=db_session,
                                sandbox_manager=sandbox_manager,
                                sandbox=sandbox,
                                tenant_id=tenant_id,
                                session_creation_lock=session_creation_lock,
                                check_cleanup_ownership=lambda: _check_cleanup_lease(
                                    lock, deadline
                                ),
                                cleanup_deadline=deadline,
                            )
                            continue
                        # DB-only prefilter: listing workspaces is a pod exec, so
                        # skip it when every ACTIVE session already has a fresh
                        # snapshot.
                        if not user_has_stale_active_session(
                            db_session, sandbox.user_id, snapshot_cutoff
                        ):
                            continue

                        session_creation_lock = get_session_creation_lock(
                            redis_client, sandbox.user_id
                        )
                        if not session_creation_lock.acquire(blocking=False):
                            task_logger.info(
                                "Skipping sandbox %s background snapshot while a "
                                "session is being created",
                                sandbox.id,
                            )
                            continue
                        try:
                            # List session directories in the sandbox via the
                            # backend-agnostic manager API.
                            session_ids = list_snapshotable_session_workspaces(
                                db_session,
                                sandbox_manager,
                                sandbox,
                                session_creation_lock,
                            )
                        finally:
                            if session_creation_lock.owned():
                                session_creation_lock.release()

                        # Background snapshot failures are log-only (unlike the
                        # reap path, nothing is about to be terminated).
                        snapshots_created = 0
                        for session_id in session_ids:
                            _check_cleanup_lease(lock, deadline)
                            try:
                                latest = get_latest_snapshot_for_session(
                                    db_session, session_id
                                )
                                if latest and latest.created_at > snapshot_cutoff:
                                    continue

                                snapshot_start = time.monotonic()
                                snapshot_result = create_session_snapshot_keep_latest(
                                    sandbox_manager=sandbox_manager,
                                    db_session=db_session,
                                    sandbox_id=sandbox_id,
                                    session_id=session_id,
                                    tenant_id=tenant_id,
                                )
                                snapshot_elapsed = time.monotonic() - snapshot_start
                                if snapshot_result:
                                    snapshots_created += 1
                                    task_logger.info(
                                        f"Snapshot created for session {session_id}: "
                                        f"{snapshot_result.size_bytes / 1_048_576:.1f} MiB "
                                        f"in {snapshot_elapsed:.1f}s"
                                    )
                            except Exception as e:
                                task_logger.warning(
                                    f"Failed to create snapshot for session {session_id}: {e}"
                                )
                                db_session.rollback()

                        # Chat history lives outside session workspaces;
                        # keep it equally fresh.
                        if (
                            snapshots_created
                            and sandbox_manager.supports_opencode_history_persistence
                        ):
                            try:
                                sandbox_manager.create_opencode_history_snapshot(
                                    sandbox_id, tenant_id
                                )
                            except Exception as e:
                                task_logger.warning(
                                    f"Background opencode history snapshot failed "
                                    f"for sandbox {sandbox_id}: {e}"
                                )

                    except Exception as e:
                        task_logger.error(
                            f"Failed to sweep sandbox {sandbox_id}: {e}",
                            exc_info=True,
                        )
                        db_session.rollback()
                        errors.append(e)

                    finally:
                        if not lock.owned():
                            raise CacheLockLostError("Sandbox cleanup lease lost")
                        cache.set(RUNNING_SANDBOX_CURSOR_KEY, str(sandbox_id))
    except Exception:
        task_logger.exception("Error in sandbox sweep for tenant %s", tenant_id)
        raise

    finally:
        if lock.owned():
            lock.release()

    if errors:
        raise ExceptionGroup(f"Sandbox sweep failed for tenant {tenant_id}", errors)
    task_logger.info(f"Sandbox sweep completed for tenant {tenant_id}")
