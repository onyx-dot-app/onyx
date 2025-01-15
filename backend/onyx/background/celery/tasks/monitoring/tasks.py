import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from pydantic import BaseModel
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.vespa.tasks import celery_get_queue_length
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine import get_db_current_time
from onyx.db.engine import get_session_with_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.enums import SyncType
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocumentSet
from onyx.db.models import IndexAttempt
from onyx.db.models import SyncRecord
from onyx.db.models import UserGroup
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType

_MONITORING_SOFT_TIME_LIMIT = 60 * 5  # 5 minutes
_MONITORING_TIME_LIMIT = _MONITORING_SOFT_TIME_LIMIT + 60  # 6 minutes

_CONNECTOR_INDEX_ATTEMPT_START_LATENCY_KEY_FMT = (
    "monitoring_connector_index_attempt_start_latency:{cc_pair_id}:{index_attempt_id}"
)

_CONNECTOR_INDEX_ATTEMPT_RUN_SUCCESS_KEY_FMT = (
    "monitoring_connector_index_attempt_run_success:{cc_pair_id}:{index_attempt_id}"
)


def _mark_metric_as_emitted(redis_std: Redis, key: str) -> None:
    """Mark a metric as having been emitted by setting a Redis key with expiration"""
    redis_std.set(key, "1", ex=24 * 60 * 60)  # Expire after 1 day


def _has_metric_been_emitted(redis_std: Redis, key: str) -> bool:
    """Check if a metric has been emitted by checking for existence of Redis key"""
    return bool(redis_std.exists(key))


class Metric(BaseModel):
    key: str | None  # only required if we need to store that we have emitted this metric
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

    def emit(self) -> None:
        # Convert value to appropriate type
        float_value = (
            float(self.value) if isinstance(self.value, (int, float)) else None
        )
        int_value = int(self.value) if isinstance(self.value, int) else None
        string_value = str(self.value) if isinstance(self.value, str) else None
        bool_value = bool(self.value) if isinstance(self.value, bool) else None

        if (
            float_value is None
            and int_value is None
            and string_value is None
            and bool_value is None
        ):
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
        optional_telemetry(
            record_type=RecordType.METRIC,
            data=data,
        )


def _collect_queue_metrics(redis_celery: Redis) -> list[Metric]:
    """Collect metrics about queue lengths for different Celery queues"""
    metrics = []
    queue_mappings = {
        "celery_queue_length": "celery",
        "indexing_queue_length": "indexing",
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
            task_logger.error(
                "Found non-initial index attempt for connector "
                "without refresh_freq. This should never happen."
            )
            return None

        desired_start_time = second_most_recent_attempt.time_updated + timedelta(
            seconds=cc_pair.connector.refresh_freq
        )

    start_latency = (recent_attempt.time_started - desired_start_time).total_seconds()

    return Metric(
        key=metric_key,
        name="connector_start_latency",
        value=start_latency,
        tags={},
    )


def _build_run_success_metric(
    cc_pair: ConnectorCredentialPair, recent_attempt: IndexAttempt, redis_std: Redis
) -> Metric | None:
    metric_key = _CONNECTOR_INDEX_ATTEMPT_RUN_SUCCESS_KEY_FMT.format(
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

    if recent_attempt.status in [
        IndexingStatus.SUCCESS,
        IndexingStatus.FAILED,
        IndexingStatus.CANCELED,
    ]:
        return Metric(
            key=metric_key,
            name="connector_run_succeeded",
            value=recent_attempt.status == IndexingStatus.SUCCESS,
            tags={"source": str(cc_pair.connector.source)},
        )

    return None


def _collect_connector_metrics(db_session: Session, redis_std: Redis) -> list[Metric]:
    """Collect metrics about connector runs from the past hour"""
    # NOTE: use get_db_current_time since the IndexAttempt times are set based on DB time
    one_hour_ago = get_db_current_time(db_session) - timedelta(hours=1)

    # Get all connector credential pairs
    cc_pairs = db_session.scalars(select(ConnectorCredentialPair)).all()

    metrics = []
    for cc_pair in cc_pairs:
        # Get most recent attempt in the last hour
        recent_attempts = (
            db_session.query(IndexAttempt)
            .filter(
                IndexAttempt.connector_credential_pair_id == cc_pair.id,
                IndexAttempt.time_created >= one_hour_ago,
            )
            .order_by(IndexAttempt.time_created.desc())
            .limit(2)
            .all()
        )
        recent_attempt = recent_attempts[0] if recent_attempts else None
        second_most_recent_attempt = (
            recent_attempts[1] if len(recent_attempts) > 1 else None
        )

        # if no metric to emit, skip
        if not recent_attempt:
            continue

        # Connector start latency
        start_latency_metric = _build_connector_start_latency_metric(
            cc_pair, recent_attempt, second_most_recent_attempt, redis_std
        )
        if start_latency_metric:
            metrics.append(start_latency_metric)

        # Connector run success/failure
        run_success_metric = _build_run_success_metric(
            cc_pair, recent_attempt, redis_std
        )
        if run_success_metric:
            metrics.append(run_success_metric)

    return metrics


def _collect_sync_metrics(db_session: Session, redis_std: Redis) -> list[Metric]:
    """Collect metrics about document set and group syncing speed"""
    # NOTE: use get_db_current_time since the SyncRecord times are set based on DB time
    one_hour_ago = get_db_current_time(db_session) - timedelta(hours=1)

    # Get all sync records from the last hour
    recent_sync_records = db_session.scalars(
        select(SyncRecord)
        .where(SyncRecord.sync_start_time >= one_hour_ago)
        .order_by(SyncRecord.sync_start_time.desc())
    ).all()

    metrics = []
    for sync_record in recent_sync_records:
        # Skip if no end time (sync still in progress)
        if not sync_record.sync_end_time:
            continue

        # Check if we already emitted a metric for this sync record
        metric_key = (
            f"sync_speed:{sync_record.sync_type}:"
            f"{sync_record.entity_id}:{sync_record.id}"
        )
        if _has_metric_been_emitted(redis_std, metric_key):
            task_logger.debug(
                f"Skipping metric for sync record {sync_record.id} "
                "because it has already been emitted"
            )
            continue

        # Calculate sync duration in minutes
        sync_duration_mins = (
            sync_record.sync_end_time - sync_record.sync_start_time
        ).total_seconds() / 60.0

        # Calculate sync speed (docs/min) - avoid division by zero
        sync_speed = (
            sync_record.num_docs_synced / sync_duration_mins
            if sync_duration_mins > 0
            else None
        )

        if sync_speed is None:
            task_logger.error(
                "Something went wrong with sync speed calculation. "
                f"Sync record: {sync_record.id}"
            )
            continue

        metrics.append(
            Metric(
                key=metric_key,
                name="sync_speed_docs_per_min",
                value=sync_speed,
                tags={
                    "sync_type": str(sync_record.sync_type),
                    "status": str(sync_record.sync_status),
                },
            )
        )

        # Add sync start latency metric
        start_latency_key = (
            f"sync_start_latency:{sync_record.sync_type}"
            f":{sync_record.entity_id}:{sync_record.id}"
        )
        if _has_metric_been_emitted(redis_std, start_latency_key):
            task_logger.debug(
                f"Skipping start latency metric for sync record {sync_record.id} "
                "because it has already been emitted"
            )
            continue

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
            # Skip other sync types
            task_logger.debug(
                f"Skipping sync record {sync_record.id} "
                f"with type {sync_record.sync_type} "
                f"and id {sync_record.entity_id} "
                "because it is not a document set or user group"
            )
            continue

        if entity is None:
            task_logger.error(
                f"Could not find entity for sync record {sync_record.id} "
                f"with type {sync_record.sync_type} and id {sync_record.entity_id}"
            )
            continue

        # Calculate start latency in seconds
        start_latency = (
            sync_record.sync_start_time - entity.time_last_modified_by_user
        ).total_seconds()
        if start_latency < 0:
            task_logger.error(
                f"Start latency is negative for sync record {sync_record.id} "
                f"with type {sync_record.sync_type} and id {sync_record.entity_id}."
                "This is likely because the entity was updated between the time the "
                "time the sync finished and this job ran. Skipping."
            )
            continue

        metrics.append(
            Metric(
                key=start_latency_key,
                name="sync_start_latency_seconds",
                value=start_latency,
                tags={
                    "sync_type": str(sync_record.sync_type),
                },
            )
        )

    return metrics


@shared_task(
    name=OnyxCeleryTask.MONITOR_BACKGROUND_PROCESSES,
    soft_time_limit=_MONITORING_SOFT_TIME_LIMIT,
    time_limit=_MONITORING_TIME_LIMIT,
    queue=OnyxCeleryQueues.MONITORING,
    bind=True,
)
def monitor_background_processes(self: Task, *, tenant_id: str | None) -> None:
    """Collect and emit metrics about background processes.
    This task runs periodically to gather metrics about:
    - Queue lengths for different Celery queues
    - Connector run metrics (start latency, success rate)
    - Syncing speed metrics
    - Worker status and task counts
    """
    task_logger.info("Starting background monitoring")
    r = get_redis_client(tenant_id=tenant_id)

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
        redis_std = get_redis_client(tenant_id=tenant_id)

        # Define metric collection functions and their dependencies
        metric_functions: list[Callable[[], list[Metric]]] = [
            lambda: _collect_queue_metrics(redis_celery),
            lambda: _collect_connector_metrics(db_session, redis_std),
            lambda: _collect_sync_metrics(db_session, redis_std),
        ]
        # Collect and log each metric
        with get_session_with_tenant(tenant_id) as db_session:
            for metric_fn in metric_functions:
                metrics = metric_fn()
                for metric in metrics:
                    metric.log()
                    metric.emit()
                    if metric.key:
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
