import json
import time
from collections.abc import Callable
from datetime import timedelta
from itertools import islice
from typing import Any
from typing import cast
from typing import Literal

import psutil
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from pydantic import BaseModel
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import celery_get_queue_length
from onyx.background.celery.celery_redis import celery_get_unacked_task_ids
from onyx.background.celery.memory_monitoring import emit_process_memory
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import IndexingStatus
from onyx.db.enums import SyncStatus
from onyx.db.enums import SyncType
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocumentSet
from onyx.db.models import IndexAttempt
from onyx.db.models import SyncRecord
from onyx.db.models import UserGroup
from onyx.db.search_settings import get_active_search_settings_list
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import redis_lock_dump
from onyx.utils.logger import is_running_in_container
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_MONITORING_SOFT_TIME_LIMIT = 60 * 5  # 5 minutes
_MONITORING_TIME_LIMIT = _MONITORING_SOFT_TIME_LIMIT + 60  # 6 minutes

_CONNECTOR_INDEX_ATTEMPT_START_LATENCY_KEY_FMT = (
    "monitoring_connector_index_attempt_start_latency:{cc_pair_id}:{index_attempt_id}"
)

_CONNECTOR_INDEX_ATTEMPT_RUN_SUCCESS_KEY_FMT = (
    "monitoring_connector_index_attempt_run_success:{cc_pair_id}:{index_attempt_id}"
)

_FINAL_METRIC_KEY_FMT = "sync_final_metrics:{sync_type}:{entity_id}:{sync_record_id}"

_SYNC_START_LATENCY_KEY_FMT = (
    "sync_start_latency:{sync_type}:{entity_id}:{sync_record_id}"
)

_CONNECTOR_START_TIME_KEY_FMT = "connector_start_time:{cc_pair_id}:{index_attempt_id}"
_CONNECTOR_END_TIME_KEY_FMT = "connector_end_time:{cc_pair_id}:{index_attempt_id}"
_SYNC_START_TIME_KEY_FMT = "sync_start_time:{sync_type}:{entity_id}:{sync_record_id}"
_SYNC_END_TIME_KEY_FMT = "sync_end_time:{sync_type}:{entity_id}:{sync_record_id}"


def _mark_metric_as_emitted(redis_std: Redis, key: str) -> None:
    """Mark a metric as having been emitted by setting a Redis key with expiration"""
    redis_std.set(key, "1", ex=24 * 60 * 60)  # Expire after 1 day


def _has_metric_been_emitted(redis_std: Redis, key: str) -> bool:
    """Check if a metric has been emitted by checking for existence of Redis key"""
    return bool(redis_std.exists(key))


class Metric(BaseModel):
    key: (
        str | None
    )  # only required if we need to store that we have emitted this metric
    name: str
    value: Any
    tags: dict[str, str]

    def log(self) -> None:
        """Log the metric in a standardized format"""
        data = {
            "metric": self.name,
            "value": self.value,
            "tags": self.tags,
        }
        task_logger.info(json.dumps(data))

    def emit(self, tenant_id: str) -> None:
        # Convert value to appropriate type based on the input value
        bool_value = None
        float_value = None
        int_value = None
        string_value = None
        # NOTE: have to do bool first, since `isinstance(True, int)` is true
        # e.g. bool is a subclass of int
        if isinstance(self.value, bool):
            bool_value = self.value
        elif isinstance(self.value, int):
            int_value = self.value
        elif isinstance(self.value, float):
            float_value = self.value
        elif isinstance(self.value, str):
            string_value = self.value
        else:
            task_logger.error(
                f"Invalid metric value type: {type(self.value)} "
                f"({self.value}) for metric {self.name}."
            )
            return

        # don't send None values over the wire
        data = {
            k: v
            for k, v in {
                "metric_name": self.name,
                "float_value": float_value,
                "int_value": int_value,
                "string_value": string_value,
                "bool_value": bool_value,
                "tags": self.tags,
            }.items()
            if v is not None
        }
        task_logger.info(f"Emitting metric: {data}")
        optional_telemetry(
            record_type=RecordType.METRIC,
            data=data,
            tenant_id=tenant_id,
        )


def _collect_queue_metrics(redis_celery: Redis) -> list[Metric]:
    """Collect metrics about queue lengths for different Celery queues"""
    metrics = []
    queue_mappings = {
        "celery_queue_length": "celery",
        "docprocessing_queue_length": "docprocessing",
        "sync_queue_length": "sync",
        "deletion_queue_length": "deletion",
        "pruning_queue_length": "pruning",
        "permissions_sync_queue_length": OnyxCeleryQueues.CONNECTOR_DOC_PERMISSIONS_SYNC,
        "external_group_sync_queue_length": OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC,
        "permissions_upsert_queue_length": OnyxCeleryQueues.DOC_PERMISSIONS_UPSERT,
    }

    for name, queue in queue_mappings.items():
        metrics.append(
            Metric(
                key=None,
                name=name,
                value=celery_get_queue_length(queue, redis_celery),
                tags={"queue": name},
            )
        )

    return metrics


def _build_connector_start_latency_metric(
    cc_pair: ConnectorCredentialPair,
    recent_attempt: IndexAttempt,
    second_most_recent_attempt: IndexAttempt | None,
    redis_std: Redis,
) -> Metric | None:
    if not recent_attempt.time_started:
        return None

    # check if we already emitted a metric for this index attempt
    metric_key = _CONNECTOR_INDEX_ATTEMPT_START_LATENCY_KEY_FMT.format(
        cc_pair_id=cc_pair.id,
        index_attempt_id=recent_attempt.id,
    )
    if _has_metric_been_emitted(redis_std, metric_key):
        task_logger.info(
            f"Skipping metric for connector {cc_pair.connector.id} "
            f"index attempt {recent_attempt.id} because it has already been "
            "emitted"
        )
        return None

    # Connector start latency
    # first run case - we should start as soon as it's created
    if not second_most_recent_attempt:
        desired_start_time = cc_pair.connector.time_created
    else:
        if not cc_pair.connector.refresh_freq:
            task_logger.debug(
                "Connector has no refresh_freq and this is a non-initial index attempt. "
                "Assuming user manually triggered indexing, so we'll skip start latency metric."
            )
            return None

        desired_start_time = second_most_recent_attempt.time_updated + timedelta(
            seconds=cc_pair.connector.refresh_freq
        )

    start_latency = (recent_attempt.time_started - desired_start_time).total_seconds()

    task_logger.info(
        f"Start latency for index attempt {recent_attempt.id}: {start_latency:.2f}s "
        f"(desired: {desired_start_time}, actual: {recent_attempt.time_started})"
    )

    job_id = build_job_id("connector", str(cc_pair.id), str(recent_attempt.id))

    return Metric(
        key=metric_key,
        name="connector_start_latency",
        value=start_latency,
        tags={
            "job_id": job_id,
            "connector_id": str(cc_pair.connector.id),
            "source": str(cc_pair.connector.source),
        },
    )


def _build_connector_final_metrics(
    cc_pair: ConnectorCredentialPair,
    recent_attempts: list[IndexAttempt],
    redis_std: Redis,
) -> list[Metric]:
    """
    Final metrics for connector index attempts:
      - Boolean success/fail metric
      - If success, emit:
          * duration (seconds)
          * doc_count
    """
    metrics = []
    for attempt in recent_attempts:
        metric_key = _CONNECTOR_INDEX_ATTEMPT_RUN_SUCCESS_KEY_FMT.format(
            cc_pair_id=cc_pair.id,
            index_attempt_id=attempt.id,
        )
        if _has_metric_been_emitted(redis_std, metric_key):
            task_logger.info(
                f"Skipping final metrics for connector {cc_pair.connector.id} "
                f"index attempt {attempt.id}, already emitted."
            )
            continue

        # We only emit final metrics if the attempt is in a terminal state
        if attempt.status not in [
            IndexingStatus.SUCCESS,
            IndexingStatus.FAILED,
            IndexingStatus.CANCELED,
        ]:
            # Not finished; skip
            continue

        job_id = build_job_id("connector", str(cc_pair.id), str(attempt.id))
        success = attempt.status == IndexingStatus.SUCCESS
        metrics.append(
            Metric(
                key=metric_key,  # We'll mark the same key for any final metrics
                name="connector_run_succeeded",
                value=success,
                tags={
                    "job_id": job_id,
                    "connector_id": str(cc_pair.connector.id),
                    "source": str(cc_pair.connector.source),
                    "status": attempt.status.value,
                },
            )
        )

        if success:
            # Make sure we have valid time_started
            if attempt.time_started and attempt.time_updated:
                duration_seconds = (
                    attempt.time_updated - attempt.time_started
                ).total_seconds()
                metrics.append(
                    Metric(
                        key=None,  # No need for a new key, or you can reuse the same if you prefer
                        name="connector_index_duration_seconds",
                        value=duration_seconds,
                        tags={
                            "job_id": job_id,
                            "connector_id": str(cc_pair.connector.id),
                            "source": str(cc_pair.connector.source),
                        },
                    )
                )
            else:
                task_logger.error(
                    f"Index attempt {attempt.id} succeeded but has missing time "
                    f"(time_started={attempt.time_started}, time_updated={attempt.time_updated})."
                )

            # For doc counts, choose whichever field is more relevant
            doc_count = attempt.total_docs_indexed or 0
            metrics.append(
                Metric(
                    key=None,
                    name="connector_index_doc_count",
                    value=doc_count,
                    tags={
                        "job_id": job_id,
                        "connector_id": str(cc_pair.connector.id),
                        "source": str(cc_pair.connector.source),
                    },
                )
            )

    return metrics


def _collect_connector_metrics(db_session: Session, redis_std: Redis) -> list[Metric]:
    """Collect metrics about connector runs from the past hour"""
    one_hour_ago = get_db_current_time(db_session) - timedelta(hours=1)

    # Get all connector credential pairs
    cc_pairs = db_session.scalars(select(ConnectorCredentialPair)).all()
    # Might be more than one search setting, or just one
    active_search_settings_list = get_active_search_settings_list(db_session)

    metrics = []

    # If you want to process each cc_pair against each search setting:
    for cc_pair in cc_pairs:
        for search_settings in active_search_settings_list:
            recent_attempts = (
                db_session.query(IndexAttempt)
                .filter(
                    IndexAttempt.connector_credential_pair_id == cc_pair.id,
                    IndexAttempt.search_settings_id == search_settings.id,
                )
                .order_by(IndexAttempt.time_created.desc())
                .limit(2)
                .all()
            )

            if not recent_attempts:
                continue

            most_recent_attempt = recent_attempts[0]
            second_most_recent_attempt = (
                recent_attempts[1] if len(recent_attempts) > 1 else None
            )

            if one_hour_ago > most_recent_attempt.time_created:
                continue

            # Build a job_id for correlation
            job_id = build_job_id(
                "connector", str(cc_pair.id), str(most_recent_attempt.id)
            )

            # Add raw start time metric if available
            if most_recent_attempt.time_started:
                start_time_key = _CONNECTOR_START_TIME_KEY_FMT.format(
                    cc_pair_id=cc_pair.id,
                    index_attempt_id=most_recent_attempt.id,
                )
                metrics.append(
                    Metric(
                        key=start_time_key,
                        name="connector_start_time",
                        value=most_recent_attempt.time_started.timestamp(),
                        tags={
                            "job_id": job_id,
                            "connector_id": str(cc_pair.connector.id),
                            "source": str(cc_pair.connector.source),
                        },
                    )
                )

            # Add raw end time metric if available and in terminal state
            if (
                most_recent_attempt.status.is_terminal()
                and most_recent_attempt.time_updated
            ):
                end_time_key = _CONNECTOR_END_TIME_KEY_FMT.format(
                    cc_pair_id=cc_pair.id,
                    index_attempt_id=most_recent_attempt.id,
                )
                metrics.append(
                    Metric(
                        key=end_time_key,
                        name="connector_end_time",
                        value=most_recent_attempt.time_updated.timestamp(),
                        tags={
                            "job_id": job_id,
                            "connector_id": str(cc_pair.connector.id),
                            "source": str(cc_pair.connector.source),
                        },
                    )
                )

            # Connector start latency
            start_latency_metric = _build_connector_start_latency_metric(
                cc_pair, most_recent_attempt, second_most_recent_attempt, redis_std
            )

            if start_latency_metric:
                metrics.append(start_latency_metric)

            # Connector run success/failure
            final_metrics = _build_connector_final_metrics(
                cc_pair, recent_attempts, redis_std
            )
            metrics.extend(final_metrics)

    return metrics


def _collect_sync_metrics(db_session: Session, redis_std: Redis) -> list[Metric]:
    """
    Collect metrics for document set and group syncing:
      - Success/failure status
      - Start latency (for doc sets / user groups)
      - Duration & doc count (only if success)
      - Throughput (docs/min) (only if success)
      - Raw start/end times for each sync
    """

    one_hour_ago = get_db_current_time(db_session) - timedelta(hours=1)

    # Get all sync records that ended in the last hour
    recent_sync_records = db_session.scalars(
        select(SyncRecord)
        .where(SyncRecord.sync_end_time.isnot(None))
        .where(SyncRecord.sync_end_time >= one_hour_ago)
        .order_by(SyncRecord.sync_end_time.desc())
    ).all()

    task_logger.info(
        f"Collecting sync metrics for {len(recent_sync_records)} sync records"
    )

    metrics = []

    for sync_record in recent_sync_records:
        # Build a job_id for correlation
        job_id = build_job_id("sync_record", str(sync_record.id))

        # Add raw start time metric
        start_time_key = _SYNC_START_TIME_KEY_FMT.format(
            sync_type=sync_record.sync_type,
            entity_id=sync_record.entity_id,
            sync_record_id=sync_record.id,
        )
        metrics.append(
            Metric(
                key=start_time_key,
                name="sync_start_time",
                value=sync_record.sync_start_time.timestamp(),
                tags={
                    "job_id": job_id,
                    "sync_type": str(sync_record.sync_type),
                },
            )
        )

        # Add raw end time metric if available
        if sync_record.sync_end_time:
            end_time_key = _SYNC_END_TIME_KEY_FMT.format(
                sync_type=sync_record.sync_type,
                entity_id=sync_record.entity_id,
                sync_record_id=sync_record.id,
            )
            metrics.append(
                Metric(
                    key=end_time_key,
                    name="sync_end_time",
                    value=sync_record.sync_end_time.timestamp(),
                    tags={
                        "job_id": job_id,
                        "sync_type": str(sync_record.sync_type),
                    },
                )
            )

        # Emit a SUCCESS/FAIL boolean metric
        #    Use a single Redis key to avoid re-emitting final metrics
        final_metric_key = _FINAL_METRIC_KEY_FMT.format(
            sync_type=sync_record.sync_type,
            entity_id=sync_record.entity_id,
            sync_record_id=sync_record.id,
        )
        if not _has_metric_been_emitted(redis_std, final_metric_key):
            # Evaluate success
            sync_succeeded = sync_record.sync_status == SyncStatus.SUCCESS

            metrics.append(
                Metric(
                    key=final_metric_key,
                    name="sync_run_succeeded",
                    value=sync_succeeded,
                    tags={
                        "job_id": job_id,
                        "sync_type": str(sync_record.sync_type),
                        "status": str(sync_record.sync_status),
                    },
                )
            )

            # If successful, emit additional metrics
            if sync_succeeded:
                if sync_record.sync_end_time and sync_record.sync_start_time:
                    duration_seconds = (
                        sync_record.sync_end_time - sync_record.sync_start_time
                    ).total_seconds()
                else:
                    task_logger.error(
                        f"Invalid times for sync record {sync_record.id}: "
                        f"start={sync_record.sync_start_time}, end={sync_record.sync_end_time}"
                    )
                    duration_seconds = None

                doc_count = sync_record.num_docs_synced or 0

                sync_speed = None
                if duration_seconds and duration_seconds > 0:
                    duration_mins = duration_seconds / 60.0
                    sync_speed = (
                        doc_count / duration_mins if duration_mins > 0 else None
                    )

                # Emit duration, doc count, speed
                if duration_seconds is not None:
                    metrics.append(
                        Metric(
                            key=final_metric_key,
                            name="sync_duration_seconds",
                            value=duration_seconds,
                            tags={
                                "job_id": job_id,
                                "sync_type": str(sync_record.sync_type),
                            },
                        )
                    )
                else:
                    task_logger.error(
                        f"Invalid sync record {sync_record.id} with no duration"
                    )

                metrics.append(
                    Metric(
                        key=final_metric_key,
                        name="sync_doc_count",
                        value=doc_count,
                        tags={
                            "job_id": job_id,
                            "sync_type": str(sync_record.sync_type),
                        },
                    )
                )

                if sync_speed is not None:
                    metrics.append(
                        Metric(
                            key=final_metric_key,
                            name="sync_speed_docs_per_min",
                            value=sync_speed,
                            tags={
                                "job_id": job_id,
                                "sync_type": str(sync_record.sync_type),
                            },
                        )
                    )
                else:
                    task_logger.error(
                        f"Invalid sync record {sync_record.id} with no duration"
                    )

        # Emit start latency
        start_latency_key = _SYNC_START_LATENCY_KEY_FMT.format(
            sync_type=sync_record.sync_type,
            entity_id=sync_record.entity_id,
            sync_record_id=sync_record.id,
        )
        if not _has_metric_been_emitted(redis_std, start_latency_key):
            # Get the entity's last update time based on sync type
            entity: DocumentSet | UserGroup | None = None
            if sync_record.sync_type == SyncType.DOCUMENT_SET:
                entity = db_session.scalar(
                    select(DocumentSet).where(DocumentSet.id == sync_record.entity_id)
                )
            elif sync_record.sync_type == SyncType.USER_GROUP:
                entity = db_session.scalar(
                    select(UserGroup).where(UserGroup.id == sync_record.entity_id)
                )
            else:
                # Only user groups and document set sync records have
                #  an associated entity we can use for latency metrics
                continue

            if entity is None:
                task_logger.error(
                    f"Sync record of type {sync_record.sync_type} doesn't have an entity "
                    f"associated with it (id={sync_record.entity_id}). Skipping start latency metric."
                )

            # Calculate start latency in seconds:
            #    (actual sync start) - (last modified time)
            if (
                entity is not None
                and entity.time_last_modified_by_user
                and sync_record.sync_start_time
            ):
                start_latency = (
                    sync_record.sync_start_time - entity.time_last_modified_by_user
                ).total_seconds()

                if start_latency < 0:
                    task_logger.error(
                        f"Negative start latency for sync record {sync_record.id} "
                        f"(start={sync_record.sync_start_time}, entity_modified={entity.time_last_modified_by_user})"
                    )
                    continue

                metrics.append(
                    Metric(
                        key=start_latency_key,
                        name="sync_start_latency_seconds",
                        value=start_latency,
                        tags={
                            "job_id": job_id,
                            "sync_type": str(sync_record.sync_type),
                        },
                    )
                )

    return metrics


def build_job_id(
    job_type: Literal["connector", "sync_record"],
    primary_id: str,
    secondary_id: str | None = None,
) -> str:
    if job_type == "connector":
        if secondary_id is None:
            raise ValueError(
                "secondary_id (attempt_id) is required for connector job_type"
            )
        return f"connector:{primary_id}:attempt:{secondary_id}"
    elif job_type == "sync_record":
        return f"sync_record:{primary_id}"


@shared_task(
    name=OnyxCeleryTask.MONITOR_BACKGROUND_PROCESSES,
    ignore_result=True,
    soft_time_limit=_MONITORING_SOFT_TIME_LIMIT,
    time_limit=_MONITORING_TIME_LIMIT,
    queue=OnyxCeleryQueues.MONITORING,
    bind=True,
)
def monitor_background_processes(self: Task, *, tenant_id: str) -> None:
    """Collect and emit metrics about background processes.
    This task runs periodically to gather metrics about:
    - Queue lengths for different Celery queues
    - Connector run metrics (start latency, success rate)
    - Syncing speed metrics
    - Worker status and task counts
    """
    if tenant_id is not None:
        CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    task_logger.info("Starting background monitoring")
    r = get_redis_client()

    lock_monitoring: RedisLock = r.lock(
        OnyxRedisLocks.MONITOR_BACKGROUND_PROCESSES_LOCK,
        timeout=_MONITORING_SOFT_TIME_LIMIT,
    )

    # these tasks should never overlap
    if not lock_monitoring.acquire(blocking=False):
        task_logger.info("Skipping monitoring task because it is already running")
        return None

    try:
        # Get Redis client for Celery broker
        redis_celery = self.app.broker_connection().channel().client  # type: ignore
        redis_std = get_redis_client()

        # Define metric collection functions and their dependencies
        metric_functions: list[Callable[[], list[Metric]]] = [
            lambda: _collect_queue_metrics(redis_celery),
            lambda: _collect_connector_metrics(db_session, redis_std),
            lambda: _collect_sync_metrics(db_session, redis_std),
        ]

        # Collect and log each metric
        with get_session_with_current_tenant() as db_session:
            for metric_fn in metric_functions:
                metrics = metric_fn()
                for metric in metrics:
                    # double check to make sure we aren't double-emitting metrics
                    if metric.key is None or not _has_metric_been_emitted(
                        redis_std, metric.key
                    ):
                        metric.log()
                        metric.emit(tenant_id)

                    if metric.key is not None:
                        _mark_metric_as_emitted(redis_std, metric.key)

        task_logger.info("Successfully collected background metrics")
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception as e:
        task_logger.exception("Error collecting background process metrics")
        raise e
    finally:
        if lock_monitoring.owned():
            lock_monitoring.release()

        task_logger.info("Background monitoring task finished")


@shared_task(
    name=OnyxCeleryTask.CLOUD_MONITOR_ALEMBIC,
)
def cloud_check_alembic() -> bool | None:
    """A task to verify that all tenants are on the same alembic revision.

    This check is expected to fail if a cloud alembic migration is currently running
    across all tenants.

    TODO: have the cloud migration script set an activity signal that this check
    uses to know it doesn't make sense to run a check at the present time.
    """

    # Used as a placeholder if the alembic revision cannot be retrieved
    ALEMBIC_NULL_REVISION = "000000000000"

    time_start = time.monotonic()

    redis_client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)

    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CLOUD_CHECK_ALEMBIC_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    last_lock_time = time.monotonic()

    tenant_to_revision: dict[str, str] = {}
    revision_counts: dict[str, int] = {}
    out_of_date_tenants: dict[str, str] = {}
    top_revision: str = ""
    tenant_ids: list[str] | list[None] = []

    try:
        # map tenant_id to revision (or ALEMBIC_NULL_REVISION if the query fails)
        tenant_ids = get_all_tenant_ids()
        for tenant_id in tenant_ids:
            current_time = time.monotonic()
            if current_time - last_lock_time >= (CELERY_GENERIC_BEAT_LOCK_TIMEOUT / 4):
                lock_beat.reacquire()
                last_lock_time = current_time

            if tenant_id is None:
                continue

            with get_session_with_shared_schema() as session:
                try:
                    result = session.execute(
                        text(f'SELECT * FROM "{tenant_id}".alembic_version LIMIT 1')
                    )
                    result_scalar: str | None = result.scalar_one_or_none()
                    if result_scalar is None:
                        raise ValueError("Alembic version should not be None.")

                    tenant_to_revision[tenant_id] = result_scalar
                except Exception:
                    task_logger.error(f"Tenant {tenant_id} has no revision!")
                    tenant_to_revision[tenant_id] = ALEMBIC_NULL_REVISION

        # get the total count of each revision
        for k, v in tenant_to_revision.items():
            revision_counts[v] = revision_counts.get(v, 0) + 1

        # error if any null revision tenants are found
        if ALEMBIC_NULL_REVISION in revision_counts:
            num_null_revisions = revision_counts[ALEMBIC_NULL_REVISION]
            raise ValueError(f"No revision was found for {num_null_revisions} tenants!")

        # get the revision with the most counts
        sorted_revision_counts = sorted(
            revision_counts.items(), key=lambda item: item[1], reverse=True
        )

        if len(sorted_revision_counts) == 0:
            raise ValueError(
                f"cloud_check_alembic - No revisions found for {len(tenant_ids)} tenant ids!"
            )

        top_revision, _ = sorted_revision_counts[0]

        # build a list of out of date tenants
        for k, v in tenant_to_revision.items():
            if v == top_revision:
                continue

            out_of_date_tenants[k] = v

    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
        raise
    except Exception:
        task_logger.exception("Unexpected exception during cloud alembic check")
        raise
    finally:
        if lock_beat.owned():
            lock_beat.release()
        else:
            task_logger.error("cloud_check_alembic - Lock not owned on completion")
            redis_lock_dump(lock_beat, redis_client)

    if len(out_of_date_tenants) > 0:
        task_logger.error(
            f"Found out of date tenants: "
            f"num_out_of_date_tenants={len(out_of_date_tenants)} "
            f"num_tenants={len(tenant_ids)} "
            f"revision={top_revision}"
        )

        num_to_log = min(5, len(out_of_date_tenants))
        task_logger.info(
            f"Logging {num_to_log}/{len(out_of_date_tenants)} out of date tenants."
        )
        for k, v in islice(out_of_date_tenants.items(), 5):
            task_logger.info(f"Out of date tenant: tenant={k} revision={v}")
    else:
        task_logger.info(
            f"All tenants are up to date: num_tenants={len(tenant_ids)} revision={top_revision}"
        )

    time_elapsed = time.monotonic() - time_start
    task_logger.info(
        f"cloud_check_alembic finished: num_tenants={len(tenant_ids)} elapsed={time_elapsed:.2f}"
    )
    return True


@shared_task(
    name=OnyxCeleryTask.CLOUD_MONITOR_CELERY_QUEUES, ignore_result=True, bind=True
)
def cloud_monitor_celery_queues(
    self: Task,
) -> None:
    return monitor_celery_queues_helper(self)


@shared_task(name=OnyxCeleryTask.MONITOR_CELERY_QUEUES, ignore_result=True, bind=True)
def monitor_celery_queues(self: Task, *, tenant_id: str) -> None:
    return monitor_celery_queues_helper(self)


def monitor_celery_queues_helper(
    task: Task,
) -> None:
    """A task to monitor all celery queue lengths."""

    r_celery = task.app.broker_connection().channel().client  # type: ignore
    n_celery = celery_get_queue_length("celery", r_celery)
    n_docfetching = celery_get_queue_length(
        OnyxCeleryQueues.CONNECTOR_DOC_FETCHING, r_celery
    )
    n_docprocessing = celery_get_queue_length(OnyxCeleryQueues.DOCPROCESSING, r_celery)
    n_user_files_indexing = celery_get_queue_length(
        OnyxCeleryQueues.USER_FILES_INDEXING, r_celery
    )
    n_user_file_processing = celery_get_queue_length(
        OnyxCeleryQueues.USER_FILE_PROCESSING, r_celery
    )
    n_user_file_project_sync = celery_get_queue_length(
        OnyxCeleryQueues.USER_FILE_PROJECT_SYNC, r_celery
    )
    n_user_file_delete = celery_get_queue_length(
        OnyxCeleryQueues.USER_FILE_DELETE, r_celery
    )
    n_sync = celery_get_queue_length(OnyxCeleryQueues.VESPA_METADATA_SYNC, r_celery)
    n_deletion = celery_get_queue_length(OnyxCeleryQueues.CONNECTOR_DELETION, r_celery)
    n_pruning = celery_get_queue_length(OnyxCeleryQueues.CONNECTOR_PRUNING, r_celery)
    n_permissions_sync = celery_get_queue_length(
        OnyxCeleryQueues.CONNECTOR_DOC_PERMISSIONS_SYNC, r_celery
    )
    n_external_group_sync = celery_get_queue_length(
        OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC, r_celery
    )
    n_permissions_upsert = celery_get_queue_length(
        OnyxCeleryQueues.DOC_PERMISSIONS_UPSERT, r_celery
    )

    n_docfetching_prefetched = celery_get_unacked_task_ids(
        OnyxCeleryQueues.CONNECTOR_DOC_FETCHING, r_celery
    )
    n_docprocessing_prefetched = celery_get_unacked_task_ids(
        OnyxCeleryQueues.DOCPROCESSING, r_celery
    )

    task_logger.info(
        f"Queue lengths: celery={n_celery} "
        f"docfetching={n_docfetching} "
        f"docfetching_prefetched={len(n_docfetching_prefetched)} "
        f"docprocessing={n_docprocessing} "
        f"docprocessing_prefetched={len(n_docprocessing_prefetched)} "
        f"user_files_indexing={n_user_files_indexing} "
        f"user_file_processing={n_user_file_processing} "
        f"user_file_project_sync={n_user_file_project_sync} "
        f"user_file_delete={n_user_file_delete} "
        f"sync={n_sync} "
        f"deletion={n_deletion} "
        f"pruning={n_pruning} "
        f"permissions_sync={n_permissions_sync} "
        f"external_group_sync={n_external_group_sync} "
        f"permissions_upsert={n_permissions_upsert} "
    )


"""Memory monitoring"""


def _get_cmdline_for_process(process: psutil.Process) -> str | None:
    try:
        return " ".join(process.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


@shared_task(
    name=OnyxCeleryTask.MONITOR_PROCESS_MEMORY,
    ignore_result=True,
    soft_time_limit=_MONITORING_SOFT_TIME_LIMIT,
    time_limit=_MONITORING_TIME_LIMIT,
    queue=OnyxCeleryQueues.MONITORING,
    bind=True,
)
def monitor_process_memory(self: Task, *, tenant_id: str) -> None:
    """
    Task to monitor memory usage of supervisor-managed processes.
    This periodically checks the memory usage of processes and logs information
    in a standardized format.

    The task looks for processes managed by supervisor and logs their
    memory usage statistics. This is useful for monitoring memory consumption
    over time and identifying potential memory leaks.
    """
    # don't run this task in multi-tenant mode, have other, better means of monitoring
    if MULTI_TENANT:
        return

    # Skip memory monitoring if not in container
    if not is_running_in_container():
        return

    try:
        # Get all supervisor-managed processes
        supervisor_processes: dict[int, str] = {}

        # Map cmd line elements to more readable process names
        process_type_mapping = {
            "--hostname=primary": "primary",
            "--hostname=light": "light",
            "--hostname=heavy": "heavy",
            "--hostname=indexing": "indexing",
            "--hostname=monitoring": "monitoring",
            "beat": "beat",
            "slack/listener.py": "slack",
        }

        # Find all python processes that are likely celery workers
        for proc in psutil.process_iter():
            cmdline = _get_cmdline_for_process(proc)
            if not cmdline:
                continue

            # Match supervisor-managed processes
            for process_name, process_type in process_type_mapping.items():
                if process_name in cmdline:
                    if process_type in supervisor_processes.values():
                        task_logger.error(
                            f"Duplicate process type for type {process_type} "
                            f"with cmd {cmdline} with pid={proc.pid}."
                        )
                        continue

                    supervisor_processes[proc.pid] = process_type
                    break

        if len(supervisor_processes) != len(process_type_mapping):
            task_logger.error(
                "Missing processes: "
                f"{set(process_type_mapping.keys()).symmetric_difference(supervisor_processes.values())}"
            )

        # Log memory usage for each process
        for pid, process_type in supervisor_processes.items():
            try:
                emit_process_memory(pid, process_type, {})
            except psutil.NoSuchProcess:
                # Process may have terminated since we obtained the list
                continue
            except Exception as e:
                task_logger.exception(f"Error monitoring process {pid}: {str(e)}")

    except Exception:
        task_logger.exception("Error in monitor_process_memory task")


@shared_task(
    name=OnyxCeleryTask.CLOUD_MONITOR_CELERY_PIDBOX, ignore_result=True, bind=True
)
def cloud_monitor_celery_pidbox(
    self: Task,
) -> None:
    """
    Celery can leave behind orphaned pidboxes from old workers that are idle and never cleaned up.
    This task removes them based on idle time to avoid Redis clutter and overflowing the instance.
    This is a real issue we've observed in production.

    Note:
    - Setting CELERY_ENABLE_REMOTE_CONTROL = False would prevent pidbox keys entirely,
    but might also disable features like inspect, broadcast, and worker remote control.
    Use with caution.
    """

    num_deleted = 0

    MAX_PIDBOX_IDLE = 24 * 3600  # 1 day in seconds
    r_celery: Redis = self.app.broker_connection().channel().client  # type: ignore
    for key in r_celery.scan_iter("*.reply.celery.pidbox"):
        key_bytes = cast(bytes, key)
        key_str = key_bytes.decode("utf-8")
        if key_str.startswith("_kombu"):
            continue

        idletime_raw = r_celery.object("idletime", key)
        if idletime_raw is None:
            continue

        idletime = cast(int, idletime_raw)
        if idletime < MAX_PIDBOX_IDLE:
            continue

        r_celery.delete(key)
        task_logger.info(
            f"Deleted idle pidbox: pidbox={key_str} "
            f"idletime={idletime} "
            f"max_idletime={MAX_PIDBOX_IDLE}"
        )
        num_deleted += 1

    # Enable later in case we want some aggregate metrics
    # task_logger.info(f"Deleted idle pidbox: pidbox={key_str}")
