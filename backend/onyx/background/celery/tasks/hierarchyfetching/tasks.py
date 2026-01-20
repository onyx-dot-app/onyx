"""Celery tasks for hierarchy fetching.

This module provides tasks for fetching hierarchy node information from connectors.
Hierarchy nodes represent structural elements like folders, spaces, and pages that
can be used to filter search results.

The hierarchy fetching pipeline runs once per day per connector and fetches
structural information from the connector source.
"""

import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

from celery import Celery
from celery import shared_task
from celery import Task
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.interfaces import HierarchyConnector
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.db.connector import mark_cc_pair_as_hierarchy_fetched
from onyx.db.connector_credential_pair import (
    fetch_indexable_standard_connector_credential_pair_ids,
)
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.hierarchy import upsert_hierarchy_nodes_batch
from onyx.db.models import ConnectorCredentialPair
from onyx.redis.redis_hierarchy import cache_hierarchy_nodes_batch
from onyx.redis.redis_hierarchy import HierarchyNodeCacheEntry
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Hierarchy fetching runs once per day (24 hours in seconds)
HIERARCHY_FETCH_INTERVAL_SECONDS = 24 * 60 * 60


def _is_hierarchy_fetching_due(cc_pair: ConnectorCredentialPair) -> bool:
    """Returns boolean indicating if hierarchy fetching is due for this connector.

    Hierarchy fetching should run once per day for active connectors.
    """
    # Skip if not active
    if cc_pair.status != ConnectorCredentialPairStatus.ACTIVE:
        return False

    # Skip if connector has never successfully indexed
    if not cc_pair.last_successful_index_time:
        return False

    # Check if we've fetched hierarchy recently
    last_fetch = cc_pair.last_time_hierarchy_fetch
    if last_fetch is None:
        # Never fetched before - fetch now
        return True

    # Check if enough time has passed since last fetch
    next_fetch_time = last_fetch + timedelta(seconds=HIERARCHY_FETCH_INTERVAL_SECONDS)
    return datetime.now(timezone.utc) >= next_fetch_time


def _try_creating_hierarchy_fetching_task(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    db_session: Session,
    r: Redis,
    tenant_id: str,
) -> str | None:
    """Try to create a hierarchy fetching task for a connector.

    Returns the task ID if created, None otherwise.
    """
    LOCK_TIMEOUT = 30

    # Serialize task creation attempts
    lock: RedisLock = r.lock(
        DANSWER_REDIS_FUNCTION_LOCK_PREFIX + f"hierarchy_fetching_{cc_pair.id}",
        timeout=LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking_timeout=LOCK_TIMEOUT / 2)
    if not acquired:
        return None

    try:
        # Refresh to get latest state
        db_session.refresh(cc_pair)
        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            return None

        # Generate task ID
        custom_task_id = f"hierarchy_fetching_{cc_pair.id}_{uuid4()}"

        # Send the task
        result = celery_app.send_task(
            OnyxCeleryTask.CONNECTOR_HIERARCHY_FETCHING_TASK,
            kwargs=dict(
                cc_pair_id=cc_pair.id,
                tenant_id=tenant_id,
            ),
            queue=OnyxCeleryQueues.CONNECTOR_HIERARCHY_FETCHING,
            task_id=custom_task_id,
            priority=OnyxCeleryPriority.LOW,
        )

        if not result:
            raise RuntimeError("send_task for hierarchy_fetching_task failed.")

        task_logger.info(
            f"Created hierarchy fetching task: "
            f"cc_pair={cc_pair.id} "
            f"celery_task_id={custom_task_id}"
        )

        return custom_task_id

    except Exception:
        task_logger.exception(
            f"Failed to create hierarchy fetching task: cc_pair={cc_pair.id}"
        )
        return None
    finally:
        if lock.owned():
            lock.release()


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_HIERARCHY_FETCHING,
    soft_time_limit=300,
    bind=True,
)
def check_for_hierarchy_fetching(self: Task, *, tenant_id: str) -> int | None:
    """Check for connectors that need hierarchy fetching and spawn tasks.

    This task runs periodically (once per day) and checks all active connectors
    to see if they need hierarchy information fetched.
    """
    time_start = time.monotonic()
    task_logger.info("check_for_hierarchy_fetching - Starting")

    tasks_created = 0
    locked = False
    redis_client = get_redis_client()

    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_HIERARCHY_FETCHING_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # These tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        locked = True

        with get_session_with_current_tenant() as db_session:
            # Get all active connector credential pairs
            cc_pair_ids = fetch_indexable_standard_connector_credential_pair_ids(
                db_session=db_session,
                active_cc_pairs_only=True,
            )

            for cc_pair_id in cc_pair_ids:
                lock_beat.reacquire()
                cc_pair = get_connector_credential_pair_from_id(
                    db_session=db_session,
                    cc_pair_id=cc_pair_id,
                )

                if not cc_pair or not _is_hierarchy_fetching_due(cc_pair):
                    continue

                task_id = _try_creating_hierarchy_fetching_task(
                    celery_app=self.app,
                    cc_pair=cc_pair,
                    db_session=db_session,
                    r=redis_client,
                    tenant_id=tenant_id,
                )

                if task_id:
                    tasks_created += 1

    except Exception:
        task_logger.exception("check_for_hierarchy_fetching - Unexpected error")
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "check_for_hierarchy_fetching - Lock not owned on completion"
                )

    time_elapsed = time.monotonic() - time_start
    task_logger.info(
        f"check_for_hierarchy_fetching finished: "
        f"tasks_created={tasks_created} elapsed={time_elapsed:.2f}s"
    )
    return tasks_created


# Batch size for hierarchy node processing
HIERARCHY_NODE_BATCH_SIZE = 100


def _run_hierarchy_extraction(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    source: DocumentSource,
    tenant_id: str,
) -> int:
    """
    Run the hierarchy extraction for a connector.

    Instantiates the connector and calls load_hierarchy() if the connector
    implements HierarchyConnector.

    Returns the total number of hierarchy nodes extracted.
    """
    connector = cc_pair.connector
    credential = cc_pair.credential

    # Instantiate the connector using its configured input type
    runnable_connector = instantiate_connector(
        db_session=db_session,
        source=source,
        input_type=connector.input_type,
        connector_specific_config=connector.connector_specific_config,
        credential=credential,
    )

    # Check if the connector supports hierarchy fetching
    if not isinstance(runnable_connector, HierarchyConnector):
        task_logger.debug(
            f"Connector {source} does not implement HierarchyConnector, skipping"
        )
        return 0

    # Determine time range: start from last hierarchy fetch, end at now
    last_fetch = cc_pair.last_time_hierarchy_fetch
    start_time = last_fetch.timestamp() if last_fetch else 0
    end_time = datetime.now(timezone.utc).timestamp()

    total_nodes = 0
    node_batch: list[PydanticHierarchyNode] = []
    redis_client = get_redis_client(tenant_id=tenant_id)

    def _process_batch() -> int:
        """Process accumulated hierarchy nodes batch."""
        if not node_batch:
            return 0

        upserted_nodes = upsert_hierarchy_nodes_batch(
            db_session=db_session,
            nodes=node_batch,
            source=source,
            commit=True,
        )

        # Cache in Redis for fast ancestor resolution
        cache_entries = [
            HierarchyNodeCacheEntry.from_db_model(node) for node in upserted_nodes
        ]
        cache_hierarchy_nodes_batch(
            redis_client=redis_client,
            source=source,
            entries=cache_entries,
        )

        count = len(node_batch)
        node_batch.clear()
        return count

    # Fetch hierarchy nodes from the connector
    for node in runnable_connector.load_hierarchy(start=start_time, end=end_time):
        node_batch.append(node)
        if len(node_batch) >= HIERARCHY_NODE_BATCH_SIZE:
            total_nodes += _process_batch()

    # Process any remaining nodes
    total_nodes += _process_batch()

    return total_nodes


@shared_task(
    name=OnyxCeleryTask.CONNECTOR_HIERARCHY_FETCHING_TASK,
    soft_time_limit=3600,  # 1 hour soft limit
    time_limit=3900,  # 1 hour 5 min hard limit
    bind=True,
)
def connector_hierarchy_fetching_task(
    self: Task,
    *,
    cc_pair_id: int,
    tenant_id: str,
) -> None:
    """Fetch hierarchy information from a connector.

    This task fetches structural information (folders, spaces, pages, etc.)
    from the connector source and stores it in the database.
    """
    task_logger.info(
        f"connector_hierarchy_fetching_task starting: "
        f"cc_pair={cc_pair_id} tenant={tenant_id}"
    )

    try:
        with get_session_with_current_tenant() as db_session:
            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
            )

            if not cc_pair:
                task_logger.warning(
                    f"CC pair not found for hierarchy fetching: cc_pair={cc_pair_id}"
                )
                return

            if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
                task_logger.info(
                    f"Skipping hierarchy fetching for deleting connector: "
                    f"cc_pair={cc_pair_id}"
                )
                return

            source = cc_pair.connector.source
            total_nodes = _run_hierarchy_extraction(
                db_session=db_session,
                cc_pair=cc_pair,
                source=source,
                tenant_id=tenant_id,
            )

            task_logger.info(
                f"connector_hierarchy_fetching_task: "
                f"Extracted {total_nodes} hierarchy nodes for cc_pair={cc_pair_id}"
            )

            # Update the last fetch time to prevent re-running until next interval
            mark_cc_pair_as_hierarchy_fetched(db_session, cc_pair_id)

    except Exception:
        task_logger.exception(
            f"connector_hierarchy_fetching_task failed: cc_pair={cc_pair_id}"
        )
        raise

    task_logger.info(
        f"connector_hierarchy_fetching_task completed: cc_pair={cc_pair_id}"
    )
