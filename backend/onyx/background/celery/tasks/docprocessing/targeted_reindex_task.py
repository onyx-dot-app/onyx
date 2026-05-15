"""Celery task for executing a targeted reindex.

This task wires the job-and-target rows persisted by the API to the
synthetic IndexAttempt(s) that drive per-cc-pair execution. Lifecycle
+ counter aggregation + resolution-tracking gating live here; per-cc-pair
connector invocation + indexing pipeline plumbing live in
`onyx.background.indexing.run_targeted_reindex`.
"""

import datetime
import logging

from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.indexing.run_targeted_reindex import group_targets_by_cc_pair
from onyx.background.indexing.run_targeted_reindex import process_targets_for_cc_pair
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.targeted_reindex import get_index_attempts_for_targeted_reindex_job
from onyx.db.targeted_reindex import get_targeted_reindex_job
from onyx.db.targeted_reindex import get_targets_for_job
from onyx.db.targeted_reindex import resolve_failure_derived_targets
from shared_configs.contextvars import get_current_tenant_id

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
            tenant_id = get_current_tenant_id()

            # 2. group targets by cc_pair (the unit of connector invocation).
            target_rows = get_targets_for_job(db_session, targeted_reindex_job_id)
            by_cc_pair = group_targets_by_cc_pair(target_rows)

            log.info(
                "Targeted reindex starting: %d cc_pair(s), %d target(s)",
                len(by_cc_pair),
                len(target_rows),
            )

            # 3. per-cc-pair connector fetch + pipeline run. Track
            # outcomes at (cc_pair_id, document_id) granularity — the
            # same doc can be a target across multiple cc_pairs and
            # landing it for one must not clear an error filed against
            # another.
            landed_keys: set[tuple[int, str]] = set()
            failed_keys: set[tuple[int, str]] = set()
            for cc_pair_id, cc_targets in by_cc_pair.items():
                try:
                    result = process_targets_for_cc_pair(
                        cc_pair_id=cc_pair_id,
                        targets=cc_targets,
                        attempts=attempts,
                        tenant_id=tenant_id,
                        db_session=db_session,
                    )
                except Exception:
                    # One bad cc_pair must not poison the rest of the
                    # job — log, mark its targets still_failing, and
                    # carry on to the next cc_pair.
                    log.exception(
                        "process_targets_for_cc_pair raised for cc_pair_id=%s",
                        cc_pair_id,
                    )
                    failed_keys.update((cc_pair_id, t.document_id) for t in cc_targets)
                    continue
                landed_keys.update(
                    (cc_pair_id, doc_id) for doc_id in result.landed_doc_ids
                )
                failed_keys.update(
                    (cc_pair_id, doc_id) for doc_id in result.failed_doc_ids
                )
                if result.unsupported:
                    log.info(
                        "cc_pair_id=%s connector does not support targeted reindex",
                        cc_pair_id,
                    )

            # 4. resolution tracking: clear error rows only for the
            #    (cc_pair, doc) pairs that actually landed. Errors
            #    whose target failed to land stay open so the admin can
            #    retry.
            resolved_count, summary = resolve_failure_derived_targets(
                db_session, targeted_reindex_job_id, landed_keys
            )

            still_failing_count = len(failed_keys)
            total_attempted = len(target_rows)

            # 5. terminal state on synthetic IndexAttempts.
            for attempt in attempts:
                attempt.status = IndexingStatus.SUCCESS
                attempt.time_updated = datetime.datetime.now(datetime.timezone.utc)

            # 6. terminal state on the job + counters + summary snapshot.
            # `runtime_skipped` covers the residual: targets that neither
            # resolved (landed + had a source error) nor failed (connector/
            # pipeline rejected). Added on top of the create-time
            # skipped_count (dedup + upstream errors the API already
            # counted) so counters reflect total skip universe.
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
