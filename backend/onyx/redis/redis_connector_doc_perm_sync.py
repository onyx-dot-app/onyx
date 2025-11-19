import time
from datetime import datetime
from logging import Logger
from typing import Any
from typing import cast
from typing import NamedTuple

import redis
from pydantic import BaseModel
from redis.lock import Lock as RedisLock

from onyx.access.models import DocExternalAccess
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_PERMISSIONS_SYNC_LOCK_TIMEOUT
from onyx.configs.constants import OnyxRedisConstants
from onyx.redis.redis_pool import SCAN_ITER_COUNT_DEFAULT
from onyx.utils.variable_functionality import fetch_versioned_implementation


class PermissionSyncResult(NamedTuple):
    """Result of a permission sync operation.

    Attributes:
        num_updated: Number of documents successfully updated
        num_errors: Number of documents that failed to update
    """

    num_updated: int
    num_errors: int


class RedisConnectorPermissionSyncPayload(BaseModel):
    id: str
    submitted: datetime
    started: datetime | None
    celery_task_id: str | None


class RedisConnectorPermissionSync:
    """Manages interactions with redis for doc permission sync tasks. Should only be accessed
    through RedisConnector."""

    PREFIX = "connectordocpermissionsync"

    FENCE_PREFIX = f"{PREFIX}_fence"

    # phase 1 - geneartor task and progress signals
    GENERATORTASK_PREFIX = f"{PREFIX}+generator"  # connectorpermissions+generator
    GENERATOR_PROGRESS_PREFIX = (
        PREFIX + "_generator_progress"
    )  # connectorpermissions_generator_progress
    GENERATOR_COMPLETE_PREFIX = (
        PREFIX + "_generator_complete"
    )  # connectorpermissions_generator_complete

    TASKSET_PREFIX = f"{PREFIX}_taskset"  # connectorpermissions_taskset
    SUBTASK_PREFIX = f"{PREFIX}+sub"  # connectorpermissions+sub

    # used to signal the overall workflow is still active
    # it's impossible to get the exact state of the system at a single point in time
    # so we need a signal with a TTL to bridge gaps in our checks
    ACTIVE_PREFIX = PREFIX + "_active"
    ACTIVE_TTL = CELERY_PERMISSIONS_SYNC_LOCK_TIMEOUT * 2

    def __init__(self, tenant_id: str, id: int, redis: redis.Redis) -> None:
        self.tenant_id: str = tenant_id
        self.id = id
        self.redis = redis

        self.fence_key: str = f"{self.FENCE_PREFIX}_{id}"
        self.generator_task_key = f"{self.GENERATORTASK_PREFIX}_{id}"
        self.generator_progress_key = f"{self.GENERATOR_PROGRESS_PREFIX}_{id}"
        self.generator_complete_key = f"{self.GENERATOR_COMPLETE_PREFIX}_{id}"

        self.taskset_key = f"{self.TASKSET_PREFIX}_{id}"

        self.subtask_prefix: str = f"{self.SUBTASK_PREFIX}_{id}"
        self.active_key = f"{self.ACTIVE_PREFIX}_{id}"

    def taskset_clear(self) -> None:
        self.redis.delete(self.taskset_key)

    def generator_clear(self) -> None:
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)

    def get_remaining(self) -> int:
        remaining = cast(int, self.redis.scard(self.taskset_key))
        return remaining

    def get_active_task_count(self) -> int:
        """Count of active permission sync tasks"""
        count = 0
        for _ in self.redis.sscan_iter(
            OnyxRedisConstants.ACTIVE_FENCES,
            RedisConnectorPermissionSync.FENCE_PREFIX + "*",
            count=SCAN_ITER_COUNT_DEFAULT,
        ):
            count += 1
        return count

    @property
    def fenced(self) -> bool:
        return bool(self.redis.exists(self.fence_key))

    @property
    def payload(self) -> RedisConnectorPermissionSyncPayload | None:
        # read related data and evaluate/print task progress
        fence_bytes = cast(Any, self.redis.get(self.fence_key))
        if fence_bytes is None:
            return None

        fence_str = fence_bytes.decode("utf-8")
        payload = RedisConnectorPermissionSyncPayload.model_validate_json(
            cast(str, fence_str)
        )

        return payload

    def set_fence(
        self,
        payload: RedisConnectorPermissionSyncPayload | None,
    ) -> None:
        if not payload:
            self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, payload.model_dump_json())
        self.redis.sadd(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)

    def set_active(self) -> None:
        """This sets a signal to keep the permissioning flow from getting cleaned up within
        the expiration time.

        The slack in timing is needed to avoid race conditions where simply checking
        the celery queue and task status could result in race conditions."""
        self.redis.set(self.active_key, 0, ex=self.ACTIVE_TTL)

    def active(self) -> bool:
        return bool(self.redis.exists(self.active_key))

    @property
    def generator_complete(self) -> int | None:
        """the fence payload is an int representing the starting number of
        permission sync tasks to be processed ... just after the generator completes."""
        fence_bytes = self.redis.get(self.generator_complete_key)
        if fence_bytes is None:
            return None

        if fence_bytes == b"None":
            return None

        fence_int = int(cast(bytes, fence_bytes).decode())
        return fence_int

    @generator_complete.setter
    def generator_complete(self, payload: int | None) -> None:
        """Set the payload to an int to set the fence, otherwise if None it will
        be deleted"""
        if payload is None:
            self.redis.delete(self.generator_complete_key)
            return

        self.redis.set(self.generator_complete_key, payload)

    def update_db(
        self,
        lock: RedisLock | None,
        new_permissions: list[DocExternalAccess],
        source_string: str,
        connector_id: int,
        credential_id: int,
        task_logger: Logger | None = None,
    ) -> PermissionSyncResult:
        """Update permissions for documents.

        Returns:
            PermissionSyncResult containing counts of successful updates and errors
        """
        last_lock_time = time.monotonic()

        document_update_permissions_fn = fetch_versioned_implementation(
            "onyx.background.celery.tasks.doc_permission_syncing.tasks",
            "document_update_permissions",
        )

        num_permissions = 0
        num_errors = 0
        # Create a task for each document permission sync
        for permissions in new_permissions:
            current_time = time.monotonic()
            if lock and current_time - last_lock_time >= (
                CELERY_GENERIC_BEAT_LOCK_TIMEOUT / 4
            ):
                lock.reacquire()
                last_lock_time = current_time

            if (
                permissions.external_access.num_entries
                > permissions.external_access.MAX_NUM_ENTRIES
            ):
                if task_logger:
                    num_users = len(permissions.external_access.external_user_emails)
                    num_groups = len(
                        permissions.external_access.external_user_group_ids
                    )
                    task_logger.warning(
                        f"Permissions length exceeded, skipping...: "
                        f"{permissions.doc_id} "
                        f"{num_users=} {num_groups=} "
                        f"{permissions.external_access.MAX_NUM_ENTRIES=}"
                    )
                continue

            # NOTE(rkuo): this used to fire a task instead of directly writing to the DB,
            # but the permissions can be excessively large if sent over the wire.
            # On the other hand, the downside of doing db updates here is that we can
            # block and fail if we can't make the calls to the DB ... but that's probably
            # a rare enough case to be acceptable.

            # This can internally exception due to db issues but still continue
            # Catch exceptions per-document to avoid breaking the entire sync
            try:
                document_update_permissions_fn(
                    self.tenant_id,
                    permissions,
                    source_string,
                    connector_id,
                    credential_id,
                )
                num_permissions += 1
            except Exception:
                num_errors += 1
                if task_logger:
                    task_logger.exception(
                        f"Failed to update permissions for document {permissions.doc_id}"
                    )
                # Continue processing other documents

        return PermissionSyncResult(num_updated=num_permissions, num_errors=num_errors)

    def reset(self) -> None:
        self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
        self.redis.delete(self.active_key)
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)
        self.redis.delete(self.taskset_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def remove_from_taskset(id: int, task_id: str, r: redis.Redis) -> None:
        taskset_key = f"{RedisConnectorPermissionSync.TASKSET_PREFIX}_{id}"
        r.srem(taskset_key, task_id)
        return

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        """Deletes all redis values for all connectors"""
        for key in r.scan_iter(RedisConnectorPermissionSync.ACTIVE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorPermissionSync.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(
            RedisConnectorPermissionSync.GENERATOR_COMPLETE_PREFIX + "*"
        ):
            r.delete(key)

        for key in r.scan_iter(
            RedisConnectorPermissionSync.GENERATOR_PROGRESS_PREFIX + "*"
        ):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorPermissionSync.FENCE_PREFIX + "*"):
            r.delete(key)
