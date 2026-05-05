"""Celery tasks for proposal review — discovered by autodiscover_tasks."""

from __future__ import annotations

from uuid import UUID

from celery import shared_task
from redis.lock import Lock as RedisLock

from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


@shared_task(
    name="run_proposal_review",
    bind=True,
    ignore_result=True,
    soft_time_limit=3600,
    time_limit=3660,
)
def run_proposal_review(
    _self: object,
    review_run_id: str,
    tenant_id: str,
    rule_ids: list[str] | None = None,
) -> None:
    """Evaluate rules for a review run.

    When rule_ids is None, evaluates all active rules in the run's ruleset
    (full run). When rule_ids is provided, evaluates only those specific
    rules (retry flow).
    """
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    try:
        from onyx.tracing.framework.create import trace

        with trace(
            "proposal_review",
            metadata={"review_run_id": review_run_id},
        ):
            from onyx.server.features.proposal_review.engine.review_engine import (
                _execute_review,
            )

            _execute_review(review_run_id, rule_ids=rule_ids)
    except Exception as e:
        logger.error("Review run %s failed: %s", review_run_id, e, exc_info=True)
        from onyx.server.features.proposal_review.engine.review_engine import (
            _mark_run_failed,
        )

        _mark_run_failed(review_run_id)
        raise
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.set(None)


@shared_task(name="run_checklist_import", bind=True, ignore_result=True)
def run_checklist_import(_self: object, import_job_id: str, tenant_id: str) -> None:
    """Background task: decompose a checklist via LLM and save rules."""
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    try:
        from onyx.tracing.framework.create import trace

        with trace(
            "checklist_import",
            metadata={"import_job_id": import_job_id},
        ):
            from onyx.server.features.proposal_review.engine.review_engine import (
                _execute_checklist_import,
            )

            _execute_checklist_import(import_job_id)
    except Exception as e:
        logger.error("Import job %s failed: %s", import_job_id, e, exc_info=True)
        from onyx.server.features.proposal_review.engine.review_engine import (
            _mark_import_failed,
        )

        _mark_import_failed(import_job_id, str(e))
        raise
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.set(None)


@shared_task(
    name="sync_decision_to_jira",
    bind=True,
    ignore_result=True,
    soft_time_limit=60,
    time_limit=90,
)
def sync_decision_to_jira(_self: object, proposal_id: str, tenant_id: str) -> None:
    """Writes officer decision back to Jira.

    Dispatched from the sync-jira API endpoint.
    """
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.server.features.proposal_review.engine.jira_sync import sync_to_jira

        with get_session_with_current_tenant() as db_session:
            sync_to_jira(UUID(proposal_id), db_session)
            db_session.commit()

        logger.info("Jira sync completed for proposal %s", proposal_id)

    except Exception as e:
        logger.error(
            "Jira sync failed for proposal %s: %s", proposal_id, e, exc_info=True
        )
        raise
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.set(None)


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_DANGLING_IMPORT_JOBS,
    bind=True,
    ignore_result=True,
    soft_time_limit=60,
    time_limit=90,
)
def check_for_dangling_import_jobs(_self: object, *, tenant_id: str) -> None:
    """Beat task: mark import jobs stuck in PENDING/RUNNING as FAILED.

    A job is considered stuck if it has been in a non-terminal state for
    longer than the stale threshold (default 60 minutes).  This handles
    cases where the Celery message was discarded (e.g. worker restart
    before the task was registered) or the task crashed without marking
    the job as FAILED.
    """
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.server.features.proposal_review.db import imports as imports_db

    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    locked = False
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_DANGLING_IMPORT_JOBS_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    if not lock.acquire(blocking=False):
        logger.info(
            "check_for_dangling_import_jobs - Lock not acquired: tenant=%s",
            tenant_id,
        )
        return None

    try:
        locked = True
        with get_session_with_current_tenant() as db_session:
            dangling = imports_db.get_dangling_import_jobs(
                db_session, stale_threshold_minutes=60
            )
            if not dangling:
                return

            for job in dangling:
                logger.warning(
                    "Marking dangling import job %s as FAILED "
                    "(status=%s, created_at=%s)",
                    job.id,
                    job.status,
                    job.created_at,
                )
                imports_db.mark_import_job_failed(
                    job,
                    "Import timed out — the background task did not complete. "
                    "Please try importing again.",
                    db_session,
                )

            db_session.commit()
            logger.info(
                "Cleaned up %d dangling import job(s) for tenant %s",
                len(dangling),
                tenant_id,
            )
    except Exception:
        logger.exception("Unexpected error during dangling import job cleanup")
    finally:
        if locked:
            if lock.owned():
                lock.release()
            else:
                logger.error(
                    "check_for_dangling_import_jobs - "
                    "Lock not owned on completion: tenant=%s",
                    tenant_id,
                )
        CURRENT_TENANT_ID_CONTEXTVAR.set(None)
