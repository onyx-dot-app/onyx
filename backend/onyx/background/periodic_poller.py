"""Periodic poller for NO_VECTOR_DB deployments.

Replaces Celery Beat and background workers with a lightweight daemon thread
that runs from the API server process.  Two responsibilities:

1. Recovery polling (every 30 s): re-processes user files stuck in
   PROCESSING / DELETING / needs_sync states via the drain loops defined
   in ``task_utils.py``.

2. Periodic task execution (configurable intervals): runs LLM model updates
   and scheduled evals at their configured cadences, with Postgres advisory
   lock deduplication across multiple API server instances.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

from sqlalchemy import text

from onyx.utils.logger import setup_logger

logger = setup_logger()

RECOVERY_INTERVAL_SECONDS = 30
PERIODIC_TASK_LOCK_BASE = 20_000


# ------------------------------------------------------------------
# Periodic task definitions
# ------------------------------------------------------------------


@dataclass
class _PeriodicTaskDef:
    name: str
    interval_seconds: float
    lock_id: int
    run_fn: Callable[[], None]
    last_run_at: float = field(default=0.0)


def _run_auto_llm_update() -> None:
    from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL

    if not AUTO_LLM_CONFIG_URL:
        return

    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.llm.well_known_providers.auto_update_service import (
        sync_llm_models_from_github,
    )

    with get_session_with_current_tenant() as db_session:
        sync_llm_models_from_github(db_session)


def _run_cache_cleanup() -> None:
    from onyx.cache.postgres_backend import cleanup_expired_cache_entries

    cleanup_expired_cache_entries()


def _run_scheduled_eval() -> None:
    from onyx.configs.app_configs import BRAINTRUST_API_KEY
    from onyx.configs.app_configs import SCHEDULED_EVAL_DATASET_NAMES
    from onyx.configs.app_configs import SCHEDULED_EVAL_PERMISSIONS_EMAIL
    from onyx.configs.app_configs import SCHEDULED_EVAL_PROJECT

    if not all(
        [
            BRAINTRUST_API_KEY,
            SCHEDULED_EVAL_PROJECT,
            SCHEDULED_EVAL_DATASET_NAMES,
            SCHEDULED_EVAL_PERMISSIONS_EMAIL,
        ]
    ):
        return

    from datetime import datetime
    from datetime import timezone

    from onyx.evals.eval import run_eval
    from onyx.evals.models import EvalConfigurationOptions

    run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for dataset_name in SCHEDULED_EVAL_DATASET_NAMES:
        try:
            run_eval(
                configuration=EvalConfigurationOptions(
                    search_permissions_email=SCHEDULED_EVAL_PERMISSIONS_EMAIL,
                    dataset_name=dataset_name,
                    no_send_logs=False,
                    braintrust_project=SCHEDULED_EVAL_PROJECT,
                    experiment_name=f"{dataset_name} - {run_timestamp}",
                ),
                remote_dataset_name=dataset_name,
            )
        except Exception:
            logger.exception(
                f"Periodic poller - Failed scheduled eval for dataset {dataset_name}"
            )


_CACHE_CLEANUP_INTERVAL_SECONDS = 300


def _build_periodic_tasks() -> list[_PeriodicTaskDef]:
    from onyx.cache.interface import CacheBackendType
    from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL
    from onyx.configs.app_configs import AUTO_LLM_UPDATE_INTERVAL_SECONDS
    from onyx.configs.app_configs import CACHE_BACKEND
    from onyx.configs.app_configs import SCHEDULED_EVAL_DATASET_NAMES

    tasks: list[_PeriodicTaskDef] = []
    if CACHE_BACKEND == CacheBackendType.POSTGRES:
        tasks.append(
            _PeriodicTaskDef(
                name="cache-cleanup",
                interval_seconds=_CACHE_CLEANUP_INTERVAL_SECONDS,
                lock_id=PERIODIC_TASK_LOCK_BASE + 2,
                run_fn=_run_cache_cleanup,
            )
        )
    if AUTO_LLM_CONFIG_URL:
        tasks.append(
            _PeriodicTaskDef(
                name="auto-llm-update",
                interval_seconds=AUTO_LLM_UPDATE_INTERVAL_SECONDS,
                lock_id=PERIODIC_TASK_LOCK_BASE,
                run_fn=_run_auto_llm_update,
            )
        )
    if SCHEDULED_EVAL_DATASET_NAMES:
        tasks.append(
            _PeriodicTaskDef(
                name="scheduled-eval",
                interval_seconds=7 * 24 * 3600,
                lock_id=PERIODIC_TASK_LOCK_BASE + 1,
                run_fn=_run_scheduled_eval,
            )
        )
    return tasks


# ------------------------------------------------------------------
# Periodic task runner with advisory lock dedup
# ------------------------------------------------------------------


def _try_run_periodic_task(task_def: _PeriodicTaskDef) -> None:
    """Run *task_def* if its interval has elapsed and no peer holds the lock."""
    now = time.monotonic()
    if now - task_def.last_run_at < task_def.interval_seconds:
        return

    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    with get_session_with_current_tenant() as db_session:
        acquired = db_session.execute(
            text("SELECT pg_try_advisory_lock(:id)"),
            {"id": task_def.lock_id},
        ).scalar()
        if not acquired:
            return

        try:
            task_def.run_fn()
            task_def.last_run_at = now
        except Exception:
            logger.exception(
                f"Periodic poller - Error running periodic task {task_def.name}"
            )
        finally:
            db_session.execute(
                text("SELECT pg_advisory_unlock(:id)"),
                {"id": task_def.lock_id},
            )


# ------------------------------------------------------------------
# Recovery / drain loop runner
# ------------------------------------------------------------------


def _run_drain_loops(tenant_id: str) -> None:
    from onyx.background.task_utils import drain_delete_loop
    from onyx.background.task_utils import drain_processing_loop
    from onyx.background.task_utils import drain_project_sync_loop

    drain_processing_loop(tenant_id)
    drain_delete_loop(tenant_id)
    drain_project_sync_loop(tenant_id)


# ------------------------------------------------------------------
# Startup recovery (10g)
# ------------------------------------------------------------------


def recover_stuck_user_files(tenant_id: str) -> None:
    """Run all drain loops once to re-process files left in intermediate states.

    Called from ``lifespan()`` on startup when ``DISABLE_VECTOR_DB`` is set.
    """
    logger.info("recover_stuck_user_files - Checking for stuck user files")
    try:
        _run_drain_loops(tenant_id)
    except Exception:
        logger.exception("recover_stuck_user_files - Error during recovery")


# ------------------------------------------------------------------
# Daemon thread (10f)
# ------------------------------------------------------------------

_shutdown_event = threading.Event()
_poller_thread: threading.Thread | None = None


def _poller_loop(tenant_id: str) -> None:
    from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
    from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

    CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)

    periodic_tasks = _build_periodic_tasks()
    logger.info(
        f"Periodic poller started with {len(periodic_tasks)} periodic task(s): "
        f"{[t.name for t in periodic_tasks]}"
    )

    while not _shutdown_event.is_set():
        try:
            _run_drain_loops(tenant_id)
        except Exception:
            logger.exception("Periodic poller - Error in recovery polling")

        for task_def in periodic_tasks:
            try:
                _try_run_periodic_task(task_def)
            except Exception:
                logger.exception(
                    f"Periodic poller - Unhandled error checking task {task_def.name}"
                )

        _shutdown_event.wait(RECOVERY_INTERVAL_SECONDS)


def start_periodic_poller(tenant_id: str) -> None:
    """Start the periodic poller daemon thread."""
    global _poller_thread  # noqa: PLW0603
    _shutdown_event.clear()
    _poller_thread = threading.Thread(
        target=_poller_loop,
        args=(tenant_id,),
        daemon=True,
        name="no-vectordb-periodic-poller",
    )
    _poller_thread.start()
    logger.info("Periodic poller thread started")


def stop_periodic_poller() -> None:
    """Signal the periodic poller to stop and wait for it to exit."""
    global _poller_thread  # noqa: PLW0603
    if _poller_thread is None:
        return
    _shutdown_event.set()
    _poller_thread.join(timeout=10)
    if _poller_thread.is_alive():
        logger.warning("Periodic poller thread did not stop within timeout")
    _poller_thread = None
    logger.info("Periodic poller thread stopped")
