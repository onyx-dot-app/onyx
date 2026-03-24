"""Per-connector Prometheus metrics for indexing tasks.

Enriches the two primary indexing tasks (docfetching_proxy_task and
docprocessing_task) with connector-level labels: source, tenant_id,
cc_pair_id, and connector_name.

Uses an in-memory cache for cc_pair_id → (source, name) lookups.
Connectors never change source type, and names change rarely, so the
cache is safe to hold for the worker's lifetime.

Usage in a worker app module:
    from onyx.server.metrics.indexing_task_metrics import (
        on_indexing_task_prerun,
        on_indexing_task_postrun,
    )
"""

import time
from dataclasses import dataclass

from celery import Task
from prometheus_client import Counter
from prometheus_client import Histogram

from onyx.configs.constants import OnyxCeleryTask
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass(frozen=True)
class ConnectorInfo:
    """Cached connector metadata for metric labels."""

    source: str
    name: str


_UNKNOWN_CONNECTOR = ConnectorInfo(source="unknown", name="unknown")

# cc_pair_id → ConnectorInfo (populated on first encounter)
_connector_cache: dict[int, ConnectorInfo] = {}

# Only enrich these task types with per-connector labels
_INDEXING_TASK_NAMES: frozenset[str] = frozenset(
    {
        OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK,
        OnyxCeleryTask.DOCPROCESSING_TASK,
    }
)

INDEXING_TASK_STARTED = Counter(
    "onyx_indexing_task_started_total",
    "Indexing tasks started per connector",
    ["task_name", "source", "tenant_id", "cc_pair_id", "connector_name"],
)

INDEXING_TASK_COMPLETED = Counter(
    "onyx_indexing_task_completed_total",
    "Indexing tasks completed per connector",
    [
        "task_name",
        "source",
        "tenant_id",
        "cc_pair_id",
        "connector_name",
        "outcome",
    ],
)

INDEXING_TASK_DURATION = Histogram(
    "onyx_indexing_task_duration_seconds",
    "Indexing task duration by connector type",
    ["task_name", "source", "tenant_id"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600],
)

# task_id → monotonic start time (for indexing tasks only)
_indexing_start_times: dict[str, float] = {}


def _resolve_connector(cc_pair_id: int) -> ConnectorInfo:
    """Resolve cc_pair_id to ConnectorInfo, using cache when possible.

    On cache miss, does a single DB query with eager connector load.
    On any failure, returns _UNKNOWN_CONNECTOR.
    """
    cached = _connector_cache.get(cc_pair_id)
    if cached is not None:
        return cached

    try:
        from onyx.db.connector_credential_pair import (
            get_connector_credential_pair_from_id,
        )
        from onyx.db.engine.sql_engine import get_session_with_current_tenant

        with get_session_with_current_tenant() as db_session:
            cc_pair = get_connector_credential_pair_from_id(
                db_session,
                cc_pair_id,
                eager_load_connector=True,
            )
            if cc_pair is None:
                info = _UNKNOWN_CONNECTOR
            else:
                info = ConnectorInfo(
                    source=cc_pair.connector.source.value,
                    name=cc_pair.name,
                )
    except Exception:
        logger.debug(
            f"Failed to resolve connector info for cc_pair_id={cc_pair_id}",
            exc_info=True,
        )
        info = _UNKNOWN_CONNECTOR

    _connector_cache[cc_pair_id] = info
    return info


def on_indexing_task_prerun(
    task_id: str | None,
    task: Task | None,
    kwargs: dict | None,
) -> None:
    """Record per-connector metrics at task start.

    Only fires for tasks in _INDEXING_TASK_NAMES. Silently returns for
    all other tasks.
    """
    if task is None or task_id is None or kwargs is None:
        return

    task_name = task.name or ""
    if task_name not in _INDEXING_TASK_NAMES:
        return

    try:
        cc_pair_id = kwargs.get("cc_pair_id")
        tenant_id = str(kwargs.get("tenant_id", "unknown"))

        if cc_pair_id is None:
            return

        info = _resolve_connector(cc_pair_id)

        INDEXING_TASK_STARTED.labels(
            task_name=task_name,
            source=info.source,
            tenant_id=tenant_id,
            cc_pair_id=str(cc_pair_id),
            connector_name=info.name,
        ).inc()

        _indexing_start_times[task_id] = time.monotonic()
    except Exception:
        logger.debug("Failed to record indexing task prerun metrics", exc_info=True)


def on_indexing_task_postrun(
    task_id: str | None,
    task: Task | None,
    kwargs: dict | None,
    state: str | None,
) -> None:
    """Record per-connector completion metrics.

    Only fires for tasks in _INDEXING_TASK_NAMES.
    """
    if task is None or task_id is None or kwargs is None:
        return

    task_name = task.name or ""
    if task_name not in _INDEXING_TASK_NAMES:
        return

    try:
        cc_pair_id = kwargs.get("cc_pair_id")
        tenant_id = str(kwargs.get("tenant_id", "unknown"))

        if cc_pair_id is None:
            return

        info = _resolve_connector(cc_pair_id)
        outcome = "success" if state == "SUCCESS" else "failure"

        INDEXING_TASK_COMPLETED.labels(
            task_name=task_name,
            source=info.source,
            tenant_id=tenant_id,
            cc_pair_id=str(cc_pair_id),
            connector_name=info.name,
            outcome=outcome,
        ).inc()

        start = _indexing_start_times.pop(task_id, None)
        if start is not None:
            INDEXING_TASK_DURATION.labels(
                task_name=task_name,
                source=info.source,
                tenant_id=tenant_id,
            ).observe(time.monotonic() - start)
    except Exception:
        logger.debug("Failed to record indexing task postrun metrics", exc_info=True)
