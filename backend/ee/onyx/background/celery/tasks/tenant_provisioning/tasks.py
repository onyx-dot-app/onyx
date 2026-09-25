"""
Periodic tasks for tenant pre-provisioning, plus the on-demand provisioning
task the api server hands a signup to when the pool cannot serve it.
"""

import asyncio
import datetime
import threading
import uuid

from celery import Task, shared_task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import (
    TARGET_AVAILABLE_TENANTS,
    TENANT_PROVISIONING_WAIT_SECONDS,
)
from onyx.configs.constants import (
    ONYX_CLOUD_TENANT_ID,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.engine.shard_routing import get_shard_for_new_tenant
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.models import AvailableTenant
from onyx.db.tenant_shard import record_tenant_placement
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import MULTI_TENANT, TENANT_ID_PREFIX

# Maximum tenants to provision in a single task run.
# Each tenant takes ~80s (alembic migrations), so 15 tenants ≈ 20 minutes.
_MAX_TENANTS_PER_RUN = 15

# Time limits sized for worst-case: provisioning up to _MAX_TENANTS_PER_RUN new tenants
# (~90s each) plus migrating up to TARGET_AVAILABLE_TENANTS pool tenants (~90s each).
_TENANT_PROVISIONING_SOFT_TIME_LIMIT = 60 * 40  # 40 minutes
_TENANT_PROVISIONING_TIME_LIMIT = 60 * 45  # 45 minutes

# One signup's tenant: migrate a pool tenant or build one (~90s), with margin.
_USER_PROVISION_LOCK_TIMEOUT = 60 * 10


# Shares the monitoring queue with the refill task, which holds at most one
# slot at a time. Cloud runs the monitoring worker at concurrency 8 on 3 pods.
@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CLOUD_PROVISION_TENANT_FOR_USER,
    queue=OnyxCeleryQueues.MONITORING,
    ignore_result=True,
    trail=False,
    bind=True,
)
def provision_tenant_for_user(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,  # noqa: ARG001, the cloud system tenant, carried for TenantAwareTask
    email: str,
    attempt_id: str,
    referral_source: str | None = None,
) -> bool:
    """Build or migrate the tenant for one signup, off the api server. The api
    server enqueues this when the pool has no tenant at head, then polls the
    mapping. Alembic never runs there: a hung migration pins its thread pool."""
    if not MULTI_TENANT:
        return False

    # Imported here: provisioning reaches every tool implementation (~75 MB).
    from ee.onyx.server.tenants.provisioning import (
        provision_attempt_failure_key,
        provision_user_tenant,
        user_provision_lock_name,
    )

    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    # Not thread-local: the heartbeat thread below must be able to extend it.
    lock: RedisLock = r.lock(
        user_provision_lock_name(email),
        timeout=_USER_PROVISION_LOCK_TIMEOUT,
        thread_local=False,
    )
    # Wait rather than skip: a request may hold this while assigning a pool
    # tenant, and if it fails this run is the signup's only remaining chance.
    if not lock.acquire(blocking_timeout=TENANT_PROVISIONING_WAIT_SECONDS):
        raise RuntimeError(
            "provision_tenant_for_user: the per-user lock stayed held past the "
            "signup wait window"
        )

    # Celery time limits do not work on thread pools, so a long migration could
    # outlive the lock and let a retry build a second tenant. Keep it alive.
    heartbeat = _LockHeartbeat(lock, _USER_PROVISION_LOCK_TIMEOUT)
    heartbeat.start()
    try:
        new_tenant_id = asyncio.run(provision_user_tenant(email, referral_source))
        task_logger.info("Provisioned tenant %s for a signup", new_tenant_id)
        return True
    except Exception:
        # The request that enqueued this attempt reads the marker and fails
        # now instead of at its deadline. The task itself fails loudly.
        r.set(
            provision_attempt_failure_key(attempt_id),
            "1",
            ex=TENANT_PROVISIONING_WAIT_SECONDS,
        )
        raise
    finally:
        heartbeat.stop()
        try:
            lock.release()
        except Exception:
            task_logger.warning(
                "Could not release user provision lock (likely expired), continuing"
            )


class _LockHeartbeat(threading.Thread):
    """Extends a Redis lock's TTL at a third of its timeout until stopped."""

    def __init__(self, lock: RedisLock, timeout_seconds: int) -> None:
        super().__init__(daemon=True, name="user-provision-lock-heartbeat")
        self._lock = lock
        self._interval = timeout_seconds / 3
        self._timeout = timeout_seconds
        self._stopped = threading.Event()

    def run(self) -> None:
        while not self._stopped.wait(self._interval):
            try:
                self._lock.extend(self._timeout, replace_ttl=True)
            except Exception:
                # Keep trying: one failed extension leaves two thirds of the
                # TTL, and a later one may still land before it runs out.
                task_logger.exception("Could not extend the user provision lock")

    def stop(self) -> None:
        self._stopped.set()


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CLOUD_CHECK_AVAILABLE_TENANTS,
    queue=OnyxCeleryQueues.MONITORING,
    ignore_result=True,
    soft_time_limit=_TENANT_PROVISIONING_SOFT_TIME_LIMIT,
    time_limit=_TENANT_PROVISIONING_TIME_LIMIT,
    trail=False,
    bind=True,
)
def check_available_tenants(self: Task) -> None:  # noqa: ARG001
    """
    Check if we have enough pre-provisioned tenants available.
    If not, trigger the pre-provisioning of new tenants.
    """
    task_logger.info("STARTING CHECK_AVAILABLE_TENANTS")
    if not MULTI_TENANT:
        task_logger.info(
            "Multi-tenancy is not enabled, skipping tenant pre-provisioning"
        )
        return

    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    lock_check: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_AVAILABLE_TENANTS_LOCK,
        timeout=_TENANT_PROVISIONING_TIME_LIMIT,
    )

    # These tasks should never overlap
    if not lock_check.acquire(blocking=False):
        task_logger.info(
            "Skipping check_available_tenants task because it is already running"
        )
        return

    try:
        # Get the current count of available tenants
        with get_session_with_shared_schema() as db_session:
            num_available_tenants = db_session.query(AvailableTenant).count()

        # Get the target number of available tenants
        num_minimum_available_tenants = TARGET_AVAILABLE_TENANTS

        # Calculate how many new tenants we need to provision
        if num_available_tenants < num_minimum_available_tenants:
            tenants_to_provision = num_minimum_available_tenants - num_available_tenants
        else:
            tenants_to_provision = 0

        task_logger.info(
            f"Available tenants: {num_available_tenants}, "
            f"Target minimum available tenants: {num_minimum_available_tenants}, "
            f"To provision: {tenants_to_provision}"
        )

        batch_size = min(tenants_to_provision, _MAX_TENANTS_PER_RUN)
        if batch_size < tenants_to_provision:
            task_logger.info(
                f"Capping batch to {batch_size} (need {tenants_to_provision}, will catch up next cycle)"
            )

        provisioned = 0
        for i in range(batch_size):
            task_logger.info(f"Provisioning tenant {i + 1}/{batch_size}")
            try:
                if pre_provision_tenant():
                    provisioned += 1
            except Exception:
                task_logger.exception(
                    f"Failed to provision tenant {i + 1}/{batch_size}, continuing with remaining tenants"
                )

        task_logger.info(f"Provisioning complete: {provisioned}/{batch_size} succeeded")

        # Migrate any pool tenants that were provisioned before a new migration was deployed
        _migrate_stale_pool_tenants()

        _reconcile_control_plane_orphans()

    except Exception:
        task_logger.exception("Error in check_available_tenants task")

    finally:
        try:
            lock_check.release()
        except Exception:
            task_logger.warning(
                "Could not release check lock (likely expired), continuing"
            )


def _reconcile_control_plane_orphans() -> None:
    """Retry control-plane deletes that a signup rollback could not complete."""
    from ee.onyx.server.tenants.provisioning import reconcile_control_plane_orphans

    try:
        removed = asyncio.run(reconcile_control_plane_orphans())
    except Exception:
        task_logger.exception("Control plane orphan reconciliation failed")
        return
    if removed:
        task_logger.info("Removed %s orphaned control plane tenants", removed)


def _migrate_stale_pool_tenants() -> None:
    """
    Run alembic upgrade head on all pool tenants. Since alembic upgrade head is
    idempotent, tenants already at head are a fast no-op. This ensures pool
    tenants are always current so that signup doesn't hit schema mismatches
    (e.g. missing columns added after the tenant was pre-provisioned).
    """
    from ee.onyx.server.tenants.schema_management import (
        get_current_alembic_version,
        run_alembic_migrations,
    )

    with get_session_with_shared_schema() as db_session:
        pool_tenants = db_session.query(AvailableTenant).all()
        tenant_ids = [t.tenant_id for t in pool_tenants]

    if not tenant_ids:
        return

    task_logger.info(
        f"Checking {len(tenant_ids)} pool tenant(s) for pending migrations"
    )

    for tenant_id in tenant_ids:
        try:
            run_alembic_migrations(tenant_id)
            new_version = get_current_alembic_version(tenant_id)
            with get_session_with_shared_schema() as db_session:
                tenant = (
                    db_session.query(AvailableTenant)
                    .filter_by(tenant_id=tenant_id)
                    .first()
                )
                if tenant and tenant.alembic_version != new_version:
                    task_logger.info(
                        f"Migrated pool tenant {tenant_id}: {tenant.alembic_version} -> {new_version}"
                    )
                    tenant.alembic_version = new_version
                    db_session.commit()
        except Exception:
            task_logger.exception(
                f"Failed to migrate pool tenant {tenant_id}, skipping"
            )


def pre_provision_tenant() -> bool:
    """
    Pre-provision a new tenant and store it in the NewAvailableTenant table.
    This function fully sets up the tenant with all necessary configurations,
    so it's ready to be assigned to a user immediately.

    Returns True if a tenant was successfully provisioned, False otherwise.
    """
    # The MULTI_TENANT check is now done at the caller level (check_available_tenants)
    # rather than inside this function
    # Imported here: provisioning reaches every tool implementation (~75 MB) and
    # only multi-tenant deployments run this.
    from ee.onyx.server.tenants.provisioning import setup_tenant
    from ee.onyx.server.tenants.schema_management import (
        create_schema_if_not_exists,
        get_current_alembic_version,
    )

    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    lock_provision: RedisLock = r.lock(
        OnyxRedisLocks.CLOUD_PRE_PROVISION_TENANT_LOCK,
        timeout=_TENANT_PROVISIONING_TIME_LIMIT,
    )

    # Allow multiple pre-provisioning tasks to run, but ensure they don't overlap
    if not lock_provision.acquire(blocking=False):
        task_logger.warning(
            "Skipping pre_provision_tenant — could not acquire provision lock"
        )
        return False

    tenant_id: str | None = None
    try:
        # Generate a new tenant ID
        tenant_id = TENANT_ID_PREFIX + str(uuid.uuid4())
        shard_name = get_shard_for_new_tenant()
        task_logger.info(f"Pre-provisioning tenant {tenant_id} on shard {shard_name}")

        # Before schema creation: every step below routes via the catalog.
        record_tenant_placement(tenant_id, shard_name)

        # Create the schema for the new tenant
        schema_created = create_schema_if_not_exists(tenant_id)
        if schema_created:
            task_logger.debug(f"Created schema for tenant: {tenant_id}")
        else:
            task_logger.debug(f"Schema already exists for tenant: {tenant_id}")

        # Set up the tenant with all necessary configurations
        task_logger.debug(f"Setting up tenant configuration: {tenant_id}")
        asyncio.run(setup_tenant(tenant_id))
        task_logger.debug(f"Tenant configuration completed: {tenant_id}")

        # Get the current Alembic version
        alembic_version = get_current_alembic_version(tenant_id)
        task_logger.debug(
            f"Tenant {tenant_id} using Alembic version: {alembic_version}"
        )

        # Store the pre-provisioned tenant in the database
        task_logger.debug(f"Storing pre-provisioned tenant in database: {tenant_id}")
        with get_session_with_shared_schema() as db_session:
            # Use a transaction to ensure atomicity
            db_session.begin()
            try:
                new_tenant = AvailableTenant(
                    tenant_id=tenant_id,
                    alembic_version=alembic_version,
                    date_created=datetime.datetime.now(),
                    shard_name=shard_name,
                )
                db_session.add(new_tenant)
                db_session.commit()
                task_logger.info(f"Successfully pre-provisioned tenant: {tenant_id}")
                return True
            except Exception:
                db_session.rollback()
                task_logger.error(
                    f"Failed to store pre-provisioned tenant: {tenant_id}",
                    exc_info=True,
                )
                raise

    except Exception:
        task_logger.error("Error in pre_provision_tenant task", exc_info=True)
        # If we have a tenant_id, attempt to rollback any partially completed provisioning
        if tenant_id:
            task_logger.info(
                f"Rolling back failed tenant provisioning for: {tenant_id}"
            )
            try:
                from ee.onyx.server.tenants.provisioning import (
                    rollback_tenant_provisioning,
                )

                asyncio.run(rollback_tenant_provisioning(tenant_id))
            except Exception:
                task_logger.exception(f"Error during rollback for tenant: {tenant_id}")
        return False
    finally:
        try:
            lock_provision.release()
        except Exception:
            task_logger.warning(
                "Could not release provision lock (likely expired), continuing"
            )
