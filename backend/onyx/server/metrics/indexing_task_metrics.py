"""Per-connector Prometheus metrics for indexing tasks.

Enriches the two primary indexing tasks (docfetching_proxy_task and
docprocessing_task) with connector-level labels: source, tenant_id,
and cc_pair_id.

Note: connector_name is intentionally excluded from push-based per-task
counters because it is a user-defined free-form string that can create
unbounded cardinality. The pull-based collectors on the monitoring worker
(see indexing_pipeline.py) include connector_name since they have bounded
cardinality (one series per connector, not per task execution).

Uses an in-memory cache for cc_pair_id → (source, name) lookups.
Connectors never change source type, and names change rarely, so the
cache is safe to hold for the worker's lifetime.

Usage in a worker app module:
    from onyx.server.metrics.indexing_task_metrics import (
        on_indexing_task_prerun,
        on_indexing_task_postrun,
    )
"""

import threading
import time
from dataclasses import dataclass

from celery import Task
from prometheus_client import Counter
from prometheus_client import Histogram

from onyx.configs.constants import OnyxCeleryTask
from onyx.server.metrics.celery_task_metrics import _MAX_START_TIME_AGE_SECONDS
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass(frozen=True)
class ConnectorInfo:
    """Cached connector metadata for metric labels."""

    source: str
    name: str


_UNKNOWN_CONNECTOR = ConnectorInfo(source="unknown", name="unknown")

# (tenant_id, cc_pair_id) → ConnectorInfo (populated on first encounter).
# Keyed by tenant to avoid cross-tenant cache poisoning in multi-tenant
# deployments where different tenants can share the same cc_pair_id value.
_connector_cache: dict[tuple[str, int], ConnectorInfo] = {}

# Lock protecting _connector_cache — multiple thread-pool workers may
# resolve connectors concurrently.
_connector_cache_lock = threading.Lock()

# Only enrich these task types with per-connector labels
_INDEXING_TASK_NAMES: frozenset[str] = frozenset(
    {
        OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK,
        OnyxCeleryTask.DOCPROCESSING_TASK,
    }
)

# connector_name is intentionally excluded — see module docstring.
INDEXING_TASK_STARTED = Counter(
    "onyx_indexing_task_started_total",
    "Indexing tasks started per connector",
    ["task_name", "source", "tenant_id", "cc_pair_id"],
)

INDEXING_TASK_COMPLETED = Counter(
    "onyx_indexing_task_completed_total",
    "Indexing tasks completed per connector",
    [
        "task_name",
        "source",
        "tenant_id",
        "cc_pair_id",
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

# Lock protecting _indexing_start_times — prerun, postrun, and eviction may
# run concurrently on thread-pool workers.
_indexing_start_times_lock = threading.Lock()


def _evict_stale_start_times() -> None:
    """Remove _indexing_start_times entries older than _MAX_START_TIME_AGE_SECONDS.

    Must be called while holding _indexing_start_times_lock.
    """
    now = time.monotonic()
    stale_ids = [
        tid
        for tid, start in _indexing_start_times.items()
        if now - start > _MAX_START_TIME_AGE_SECONDS
    ]
    for tid in stale_ids:
        _indexing_start_times.pop(tid, None)


def _resolve_connector(cc_pair_id: int, tenant_id: str) -> ConnectorInfo:
    """Resolve cc_pair_id to ConnectorInfo, using cache when possible.

    On cache miss, does a single DB query with eager connector load.
    On any failure, returns _UNKNOWN_CONNECTOR without caching, so that
    subsequent calls can retry the lookup once the DB is available.

    tenant_id must be passed in explicitly. The signal callbacks that call
    this run outside the TenantAwareTask body (prerun fires before, postrun
    fires after the contextvar is cleared), so CURRENT_TENANT_ID_CONTEXTVAR
    is not reliably set at this point.
    """
    if not tenant_id or tenant_id == "unknown":
        return _UNKNOWN_CONNECTOR

    cache_key = (tenant_id, cc_pair_id)

    with _connector_cache_lock:
        cached = _connector_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        from onyx.db.connector_credential_pair import (
            get_connector_credential_pair_from_id,
        )
        from onyx.db.engine.sql_engine import get_session_with_tenant

        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            cc_pair = get_connector_credential_pair_from_id(
                db_session,
                cc_pair_id,
                eager_load_connector=True,
            )
            if cc_pair is None:
                # DB lookup succeeded but cc_pair doesn't exist — don't cache,
                # it may appear later (race with connector creation).
                return _UNKNOWN_CONNECTOR

            info = ConnectorInfo(
                source=cc_pair.connector.source.value,
                name=cc_pair.name,
            )
            with _connector_cache_lock:
                _connector_cache[cache_key] = info
            return info
    except Exception:
        logger.debug(
            "Failed to resolve connector info for cc_pair_id=%s",
            cc_pair_id,
            exc_info=True,
        )
        return _UNKNOWN_CONNECTOR


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

        info = _resolve_connector(cc_pair_id, tenant_id)

        INDEXING_TASK_STARTED.labels(
            task_name=task_name,
            source=info.source,
            tenant_id=tenant_id,
            cc_pair_id=str(cc_pair_id),
        ).inc()

        with _indexing_start_times_lock:
            _evict_stale_start_times()
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

        info = _resolve_connector(cc_pair_id, tenant_id)
        outcome = "success" if state == "SUCCESS" else "failure"

        INDEXING_TASK_COMPLETED.labels(
            task_name=task_name,
            source=info.source,
            tenant_id=tenant_id,
            cc_pair_id=str(cc_pair_id),
            outcome=outcome,
        ).inc()

        with _indexing_start_times_lock:
            start = _indexing_start_times.pop(task_id, None)
        if start is not None:
            INDEXING_TASK_DURATION.labels(
                task_name=task_name,
                source=info.source,
                tenant_id=tenant_id,
            ).observe(time.monotonic() - start)
    except Exception:
        logger.debug("Failed to record indexing task postrun metrics", exc_info=True)
