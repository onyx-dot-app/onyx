"""
Periodic tasks for tenant pre-provisioning.
"""

import asyncio
import datetime
import uuid

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from ee.onyx.server.tenants.provisioning import setup_tenant
from ee.onyx.server.tenants.schema_management import create_schema_if_not_exists
from ee.onyx.server.tenants.schema_management import get_current_alembic_version
from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import TARGET_AVAILABLE_TENANTS
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.models import AvailableTenant
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import TENANT_ID_PREFIX

# Maximum tenants to provision in a single task run.
# Each tenant takes ~80s (alembic migrations), so 5 tenants ≈ 7 minutes.
_MAX_TENANTS_PER_RUN = 5

# Time limits sized for worst-case batch: _MAX_TENANTS_PER_RUN × ~90s + buffer.
_TENANT_PROVISIONING_SOFT_TIME_LIMIT = 60 * 10  # 10 minutes
_TENANT_PROVISIONING_TIME_LIMIT = 60 * 15  # 15 minutes


@shared_task(
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
                f"Capping batch to {batch_size} "
                f"(need {tenants_to_provision}, will catch up next cycle)"
            )

        provisioned = 0
        for i in range(batch_size):
            task_logger.info(f"Provisioning tenant {i + 1}/{batch_size}")
            try:
                if pre_provision_tenant():
                    provisioned += 1
            except Exception:
                task_logger.exception(
                    f"Failed to provision tenant {i + 1}/{batch_size}, "
                    "continuing with remaining tenants"
                )

        task_logger.info(f"Provisioning complete: {provisioned}/{batch_size} succeeded")

    except Exception:
        task_logger.exception("Error in check_available_tenants task")

    finally:
        try:
            lock_check.release()
        except Exception:
            task_logger.warning(
                "Could not release check lock (likely expired), continuing"
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
        task_logger.info(f"Pre-provisioning tenant: {tenant_id}")

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
