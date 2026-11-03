"""Celery task for executing a targeted reindex.

This task wires the job-and-target rows persisted by the API to the
synthetic IndexAttempt(s) that drive per-cc-pair execution. Lifecycle
+ counter aggregation + resolution-tracking gating live here; per-cc-pair
connector invocation + indexing pipeline plumbing live in
`onyx.background.indexing.run_targeted_reindex`.
"""

import datetime
import logging
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from celery import Task, shared_task
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.models import ConnectorFailure
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import (
    create_index_attempt_errors__no_commit,
    resolve_index_attempt_errors_for_documents__no_commit,
)
from onyx.db.models import IndexAttempt, TargetedReindexJobTarget
from onyx.db.targeted_reindex import (
    get_index_attempts_for_targeted_reindex_job,
    get_targeted_reindex_job,
    get_targets_for_job,
    resolve_failure_derived_targets,
    targets_to_connector_failures,
)
from shared_configs.contextvars import get_current_tenant_id

if TYPE_CHECKING:
    from onyx.background.indexing.run_targeted_reindex import CCPairReindexResult

_TARGETED_REINDEX_SOFT_TIME_LIMIT = 60 * 30  # 30 minutes
_TARGETED_REINDEX_TIME_LIMIT = _TARGETED_REINDEX_SOFT_TIME_LIMIT + 60
_CANCELED_MSG = "Canceled by a user."


@dataclass(frozen=True)
class _PairEnd:
    """How a pair's retry attempts end: FAILED with ``error_msg`` when every
    target failed again, SUCCESS when it is None, with one error per document
    that failed again."""

    failures: list[ConnectorFailure]
    error_msg: str | None = None
    exception_trace: str | None = None


def _processed_end(
    db_session: Session,
    targets: Sequence[TargetedReindexJobTarget],
    result: "CCPairReindexResult",
) -> _PairEnd:
    """Each failed document keeps this run's failure. A pair that ended before
    fetching files its reason, or the original error when it has none."""
    failed = [t for t in targets if t.document_id in result.failed_doc_ids]
    originals = targets_to_connector_failures(failed, db_session)
    if result.reason is not None:
        failures = [
            original.model_copy(update={"failure_message": result.reason})
            for original in originals
        ]
        return _PairEnd(failures, result.reason)
    failures = [
        result.failures.get(target.document_id, original)
        for target, original in zip(failed, originals, strict=True)
    ]
    if not failures or len(failures) < len(targets):
        return _PairEnd(failures)
    return _PairEnd(failures, "Every retried document failed again.")


def _raised_end(
    db_session: Session,
    targets: Sequence[TargetedReindexJobTarget],
    error: Exception,
) -> _PairEnd:
    message = str(error) or type(error).__name__
    failures = [
        failure.model_copy(update={"failure_message": message, "exception": error})
        for failure in targets_to_connector_failures(targets, db_session)
    ]
    return _PairEnd(failures, message, "".join(traceback.format_exception(error)))


def _canceled_pair_ids(db_session: Session, attempts: list[IndexAttempt]) -> set[int]:
    """Pairs with a Cancel on any of their retry attempts. The cancel route
    commits in its own session, so the flag is reread."""
    for attempt in attempts:
        db_session.refresh(attempt, ["cancellation_requested"])
    return {
        attempt.connector_credential_pair_id
        for attempt in attempts
        if attempt.cancellation_requested
    }


def _end_attempts__no_commit(
    db_session: Session,
    attempts: list[IndexAttempt],
    pair_ends: dict[int, _PairEnd],
    now: datetime.datetime,
) -> None:
    canceled = _canceled_pair_ids(db_session, attempts)
    for attempt in attempts:
        end = pair_ends.get(attempt.connector_credential_pair_id, _PairEnd([]))
        if attempt.connector_credential_pair_id in canceled:
            attempt.status = IndexingStatus.CANCELED
            attempt.error_msg = _CANCELED_MSG
        else:
            attempt.status = (
                IndexingStatus.SUCCESS
                if end.error_msg is None
                else IndexingStatus.FAILED
            )
            attempt.error_msg = end.error_msg
        attempt.full_exception_trace = end.exception_trace
        attempt.time_updated = now
        attempt.time_finished = now
        create_index_attempt_errors__no_commit(db_session, attempt, end.failures)


def run_targeted_reindex(
    targeted_reindex_job_id: int,
    celery_task_id: str | None = None,
) -> None:
    """Body of the targeted-reindex task. Lifted out of the @shared_task
    decorator so tests can call it directly without going through
    celery's binding machinery."""
    from onyx.background.indexing.run_targeted_reindex import (
        group_targets_by_cc_pair,
        process_targets_for_cc_pair,
    )

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
            pair_ends: dict[int, _PairEnd] = {}
            for cc_pair_id, cc_targets in by_cc_pair.items():
                # A Cancel stops the pairs not yet fetched. One that arrives
                # while a pair runs ends that pair's attempts CANCELED after it.
                if cc_pair_id in _canceled_pair_ids(db_session, attempts):
                    continue
                try:
                    result = process_targets_for_cc_pair(
                        cc_pair_id=cc_pair_id,
                        targets=cc_targets,
                        attempts=attempts,
                        tenant_id=tenant_id,
                        db_session=db_session,
                    )
                except Exception as e:
                    # One bad cc_pair must not poison the rest of the
                    # job — log, mark its targets still_failing, and
                    # carry on to the next cc_pair.
                    log.exception(
                        "process_targets_for_cc_pair raised for cc_pair_id=%s",
                        cc_pair_id,
                    )
                    failed_keys.update((cc_pair_id, t.document_id) for t in cc_targets)
                    pair_ends[cc_pair_id] = _raised_end(db_session, cc_targets, e)
                    continue
                landed_keys.update(
                    (cc_pair_id, doc_id) for doc_id in result.landed_doc_ids
                )
                failed_keys.update(
                    (cc_pair_id, doc_id) for doc_id in result.failed_doc_ids
                )
                pair_ends[cc_pair_id] = _processed_end(db_session, cc_targets, result)
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
            # A landed document closes every open error it has on the pair, as
            # a full run does, including those an earlier retry filed.
            for cc_pair_id in by_cc_pair:
                resolve_index_attempt_errors_for_documents__no_commit(
                    db_session,
                    cc_pair_id,
                    [
                        doc_id
                        for pair_id, doc_id in landed_keys
                        if pair_id == cc_pair_id
                    ],
                )

            still_failing_count = len(failed_keys)
            total_attempted = len(target_rows)

            # 5. terminal state and the errors of documents that failed
            # again on the synthetic IndexAttempts, committed with the job.
            now = datetime.datetime.now(datetime.timezone.utc)
            _end_attempts__no_commit(db_session, attempts, pair_ends, now)

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
            job.completed_at = now
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
                            attempt.time_finished = now
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


@shared_task(  # ty: ignore[invalid-argument-type]
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
