"""Celery task for executing a targeted reindex.

Stub for now: transitions the job to IN_PROGRESS, then to a terminal
state without doing any actual reindex work. The real implementation
(connector.reindex(), pipeline plumbing, error resolution, stale-write
mitigation) lands in the follow-up PR.

Lives here so the task name is registered with the celery app and the
API path's `apply_async` resolves. Without this stub, the task name
would route to a non-existent handler and the worker would log
`unknown task` errors on every retry submission.
"""

import datetime
import logging

from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.targeted_reindex import get_targeted_reindex_job

# Soft and hard time limits scoped generously for the eventual real
# implementation; stub completes in milliseconds.
_TARGETED_REINDEX_SOFT_TIME_LIMIT = 60 * 30  # 30 minutes
_TARGETED_REINDEX_TIME_LIMIT = _TARGETED_REINDEX_SOFT_TIME_LIMIT + 60


@shared_task(
    name=OnyxCeleryTask.TARGETED_REINDEX_TASK,
    soft_time_limit=_TARGETED_REINDEX_SOFT_TIME_LIMIT,
    time_limit=_TARGETED_REINDEX_TIME_LIMIT,
    bind=True,
)
def targeted_reindex_task(
    self: Task,
    *,
    targeted_reindex_job_id: int,
    tenant_id: str,  # noqa: ARG001  # consumed by TenantAwareTask wrapper
) -> None:
    """Stub: mark the job IN_PROGRESS and immediately COMPLETED.

    Real implementation in a follow-up PR will:
      - load targets, group by cc_pair
      - build connector for each cc_pair, call `connector.reindex(refs)`
      - pipe Documents through `index_doc_batch_with_handler`
      - mark `index_attempt_errors.is_resolved=True` for targets with
        a non-null `source_error_id` whose docs successfully landed
      - track `resolved_count` / `still_failing_count` on the job row
      - snapshot `resolved_summary` at completion
    """
    log = logging.LoggerAdapter(
        task_logger,
        extra={
            "targeted_reindex_job_id": targeted_reindex_job_id,
            "celery_task_id": self.request.id,
        },
    )
    log.info("Targeted reindex task picked up job (stub implementation)")

    with get_session_with_current_tenant() as db_session:
        job = get_targeted_reindex_job(db_session, targeted_reindex_job_id)
        if job is None:
            log.warning("Job not found, dropping task")
            return

        if job.status.is_terminal():
            log.info("Job already terminal, dropping task")
            return

        job.status = IndexingStatus.IN_PROGRESS
        db_session.commit()

        # Stub: nothing else to do yet. Mark complete.
        job.status = IndexingStatus.SUCCESS
        job.completed_at = datetime.datetime.now(datetime.timezone.utc)
        db_session.commit()

    log.info("Stub targeted reindex task done")
