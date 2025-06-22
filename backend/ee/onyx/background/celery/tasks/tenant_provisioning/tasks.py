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

# Default number of pre-provisioned tenants to maintain
DEFAULT_TARGET_AVAILABLE_TENANTS = 5

# Soft time limit for tenant pre-provisioning tasks (in seconds)
_TENANT_PROVISIONING_SOFT_TIME_LIMIT = 60 * 5  # 5 minutes
# Hard time limit for tenant pre-provisioning tasks (in seconds)
_TENANT_PROVISIONING_TIME_LIMIT = 60 * 10  # 10 minutes


@shared_task(
    name=OnyxCeleryTask.CLOUD_CHECK_AVAILABLE_TENANTS,
    queue=OnyxCeleryQueues.MONITORING,
    ignore_result=True,
    soft_time_limit=_TENANT_PROVISIONING_SOFT_TIME_LIMIT,
    time_limit=_TENANT_PROVISIONING_TIME_LIMIT,
    trail=False,
    bind=True,
)
def check_available_tenants(self: Task) -> None:
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
        timeout=_TENANT_PROVISIONING_SOFT_TIME_LIMIT,
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
        num_minimum_available_tenants = getattr(
            TARGET_AVAILABLE_TENANTS, "value", DEFAULT_TARGET_AVAILABLE_TENANTS
        )

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

        # just provision one tenant each time we run this ... increase if needed.
        if tenants_to_provision > 0:
            pre_provision_tenant()

    except Exception:
        task_logger.exception("Error in check_available_tenants task")

    finally:
        lock_check.release()


def pre_provision_tenant() -> None:
    """
    Pre-provision a new tenant and store it in the NewAvailableTenant table.
    This function fully sets up the tenant with all necessary configurations,
    so it's ready to be assigned to a user immediately.
    """
    # The MULTI_TENANT check is now done at the caller level (check_available_tenants)
    # rather than inside this function

    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    lock_provision: RedisLock = r.lock(
        OnyxRedisLocks.CLOUD_PRE_PROVISION_TENANT_LOCK,
        timeout=_TENANT_PROVISIONING_SOFT_TIME_LIMIT,
    )

    # Allow multiple pre-provisioning tasks to run, but ensure they don't overlap
    if not lock_provision.acquire(blocking=False):
        task_logger.debug(
            "Skipping pre_provision_tenant task because it is already running"
        )
        return

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
    finally:
        lock_provision.release()
