"""Celery task for executing a targeted reindex.

This task wires the job-and-target rows persisted by the API to the
synthetic IndexAttempt(s) that drive per-cc-pair execution. It handles
lifecycle transitions, batches per-cc-pair execution, and updates
resolution tracking on `index_attempt_errors` for targets that came
in as failure-derived retries.

The actual connector invocation and indexing pipeline call still
need to be plumbed — that's the follow-up. This task currently:

  - loads the job + targets, groups them by cc_pair
  - transitions each linked synthetic IndexAttempt through
    NOT_STARTED → IN_PROGRESS → SUCCESS
  - marks every `IndexAttemptError` referenced by a target's
    `source_error_id` as resolved at completion (preserves the
    contract the FE polls)
  - snapshots `resolved_summary` for audit
  - updates `resolved_count` / `still_failing_count` / `skipped_count`
    on the job row
  - transitions the job to a terminal state

The follow-up adds the `connector.reindex()` call inside the per-cc-pair
loop and pipes yielded `Document` objects through
`index_doc_batch_with_handler`.
"""

import datetime
import logging
from collections import defaultdict

from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.targeted_reindex import get_index_attempts_for_targeted_reindex_job
from onyx.db.targeted_reindex import get_targeted_reindex_job
from onyx.db.targeted_reindex import get_targets_for_job
from onyx.db.targeted_reindex import resolve_failure_derived_targets

_TARGETED_REINDEX_SOFT_TIME_LIMIT = 60 * 30  # 30 minutes
_TARGETED_REINDEX_TIME_LIMIT = _TARGETED_REINDEX_SOFT_TIME_LIMIT + 60


def run_targeted_reindex(
    targeted_reindex_job_id: int,
    celery_task_id: str | None = None,
) -> None:
    """Body of the targeted-reindex task. Lifted out of the @shared_task
    decorator so tests can call it directly without going through
    celery's binding machinery."""
    log = logging.LoggerAdapter(
        task_logger,
        extra={
            "targeted_reindex_job_id": targeted_reindex_job_id,
            "celery_task_id": celery_task_id,
        },
    )

    with get_session_with_current_tenant() as db_session:
        job = get_targeted_reindex_job(db_session, targeted_reindex_job_id)
        if job is None:
            log.warning("Job not found, dropping task")
            return
        if job.status.is_terminal():
            log.info("Job already terminal, dropping task")
            return

        # 1. transition synthetic IndexAttempts + job to IN_PROGRESS.
        attempts = get_index_attempts_for_targeted_reindex_job(
            db_session, targeted_reindex_job_id
        )
        for attempt in attempts:
            attempt.status = IndexingStatus.IN_PROGRESS
            attempt.time_started = datetime.datetime.now(datetime.timezone.utc)
        job.status = IndexingStatus.IN_PROGRESS
        db_session.commit()

        resolved_count = 0
        still_failing_count = 0
        runtime_skipped = 0
        try:
            # 2. group targets by cc_pair (the unit of connector invocation).
            target_rows = get_targets_for_job(db_session, targeted_reindex_job_id)
            by_cc_pair: dict[int, list] = defaultdict(list)
            for t in target_rows:
                by_cc_pair[t.cc_pair_id].append(t)

            log.info(
                "Targeted reindex starting: %d cc_pair(s), %d target(s)",
                len(by_cc_pair),
                len(target_rows),
            )

            # 3. per-cc-pair work. Connector.reindex() and pipeline integration
            #    are the follow-up; for now we simply count what was requested
            #    and let the lifecycle code below mark the job complete.
            total_attempted = len(target_rows)

            # 4. resolution tracking: walk failure-derived targets and clear
            #    their error rows.
            resolved_count, summary = resolve_failure_derived_targets(
                db_session, targeted_reindex_job_id
            )

            # 5. terminal state on synthetic IndexAttempts.
            for attempt in attempts:
                attempt.status = IndexingStatus.SUCCESS
                attempt.time_updated = datetime.datetime.now(datetime.timezone.utc)

            # 6. terminal state on the job + counters + summary snapshot.
            # `still_failing_count` stays 0 here; the connector-invocation
            # follow-up bumps it when the connector yields ConnectorFailure.
            # `runtime_skipped` is whatever fell through the per-target
            # loop without resolving or still-failing. It is added on top
            # of the create-time skipped_count (dedup + upstream errors
            # the API already counted) so the three counters always reflect
            # the total skip universe across both phases.
            runtime_skipped = max(
                0, total_attempted - resolved_count - still_failing_count
            )
            job.resolved_count = resolved_count
            job.still_failing_count = still_failing_count
            job.skipped_count = (job.skipped_count or 0) + runtime_skipped
            job.resolved_summary = summary
            job.completed_at = datetime.datetime.now(datetime.timezone.utc)
            job.status = IndexingStatus.SUCCESS

            db_session.commit()
        except Exception:
            # Recover from any mid-task failure: roll back uncommitted
            # work, then mark the job + synthetic IndexAttempts FAILED so
            # the FE poll surfaces the failure instead of waiting on a
            # row stuck in IN_PROGRESS forever.
            #
            # The cleanup itself is wrapped so a secondary failure (e.g.
            # connection reset during the FAILED-state commit) does not
            # mask the original exception: we always re-raise the root
            # cause so celery records the right error.
            log.exception("Targeted reindex task failed; marking job FAILED")
            try:
                db_session.rollback()
                job = get_targeted_reindex_job(db_session, targeted_reindex_job_id)
                if job is not None and not job.status.is_terminal():
                    attempts = get_index_attempts_for_targeted_reindex_job(
                        db_session, targeted_reindex_job_id
                    )
                    now = datetime.datetime.now(datetime.timezone.utc)
                    for attempt in attempts:
                        if not attempt.status.is_terminal():
                            attempt.status = IndexingStatus.FAILED
                            attempt.time_updated = now
                    job.status = IndexingStatus.FAILED
                    job.completed_at = now
                    db_session.commit()
            except Exception:
                log.exception(
                    "Failed to mark job FAILED during error recovery; "
                    "row may remain IN_PROGRESS until the celery retry"
                )
            raise

    log.info(
        "Targeted reindex done: resolved=%d runtime_skipped=%d still_failing=%d",
        resolved_count,
        runtime_skipped,
        still_failing_count,
    )


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
    run_targeted_reindex(
        targeted_reindex_job_id=targeted_reindex_job_id,
        celery_task_id=self.request.id,
    )
