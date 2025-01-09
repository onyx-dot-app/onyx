import json
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from celery import shared_task
from celery import Task
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.vespa.tasks import celery_get_queue_length
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine import get_session_with_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType


_CONNECTOR_INDEX_ATTEMPT_KEY_FMT = (
    "monitoring_connector_index_attempt:{cc_pair_id}:{index_attempt_id}"
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
        data = {
            "metric": self.name,
            "value": self.value,
            "tags": self.tags,
        }
        optional_telemetry(
            record_type=RecordType.USAGE,
            data=data,
        )


def _collect_queue_metrics(redis_celery: Redis) -> list[Metric]:
    """Collect metrics about queue lengths for different Celery queues"""
    metrics = []
    queue_mappings = {
        "celery": "celery",
        "indexing": OnyxCeleryQueues.CONNECTOR_INDEXING,
        "sync": OnyxCeleryQueues.VESPA_METADATA_SYNC,
        "deletion": OnyxCeleryQueues.CONNECTOR_DELETION,
        "pruning": OnyxCeleryQueues.CONNECTOR_PRUNING,
        "permissions_sync": OnyxCeleryQueues.CONNECTOR_DOC_PERMISSIONS_SYNC,
        "external_group_sync": OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC,
        "permissions_upsert": OnyxCeleryQueues.DOC_PERMISSIONS_UPSERT,
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


def _collect_connector_metrics(db_session: Session, redis_std: Redis) -> list[Metric]:
    """Collect metrics about connector runs from the past hour"""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    # Get all connector credential pairs
    cc_pairs = db_session.scalars(select(ConnectorCredentialPair)).all()

    metrics = []
    for cc_pair in cc_pairs:
        base_tags = {
            "source": cc_pair.connector.source,
            "connector_id": str(cc_pair.connector.id),
        }

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
        if not recent_attempt or not recent_attempt.time_started:
            continue

        # check if we already emitted a metric for this index attempt
        metric_key = _CONNECTOR_INDEX_ATTEMPT_KEY_FMT.format(
            cc_pair_id=cc_pair.id,
            index_attempt_id=recent_attempt.id,
        )
        if _has_metric_been_emitted(redis_std, metric_key):
            task_logger.info(
                f"Skipping metric for connector {cc_pair.connector.id} "
                f"index attempt {recent_attempt.id} because it has already been "
                "emitted"
            )
            continue

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
                continue

            desired_start_time = second_most_recent_attempt.time_updated + timedelta(
                seconds=cc_pair.connector.refresh_freq
            )

        start_latency = (
            recent_attempt.time_started - desired_start_time
        ).total_seconds()

        metrics.append(
            Metric(
                key=metric_key,
                name="connector_start_latency",
                value=start_latency,
                tags={
                    **base_tags,
                    "index_attempt_id": str(recent_attempt.id),
                },
            )
        )

        # Connector run success/failure
        if recent_attempt.status in [
            IndexingStatus.SUCCESS,
            IndexingStatus.FAILED,
            IndexingStatus.CANCELED,
        ]:
            metrics.append(
                Metric(
                    key=metric_key,
                    name="connector_run_succeeded",
                    value=(1 if recent_attempt.status == IndexingStatus.SUCCESS else 0),
                    tags={
                        **base_tags,
                        "index_attempt_id": str(recent_attempt.id),
                    },
                )
            )

    return metrics


def _collect_sync_metrics(db_session: Session) -> list[Metric]:
    """Collect metrics about document set and group syncing speed"""
    # TODO: Implement this
    return []


@shared_task(
    name=OnyxCeleryTask.MONITOR_BACKGROUND_PROCESSES,
    soft_time_limit=JOB_TIMEOUT,
    queue="monitoring",
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
    task_logger.info("Starting background process monitoring")

    try:
        # Get Redis client for Celery broker
        redis_celery = self.app.broker_connection().channel().client  # type: ignore
        redis_std = get_redis_client(tenant_id=tenant_id)

        # Define metric collection functions and their dependencies
        metric_functions: list[Callable[[], list[Metric]]] = [
            lambda: _collect_queue_metrics(redis_celery),
            lambda: _collect_connector_metrics(db_session, redis_std),
            lambda: _collect_sync_metrics(db_session),
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

        task_logger.info("Successfully collected background process metrics")

    except Exception as e:
        task_logger.exception("Error collecting background process metrics")
        raise e
