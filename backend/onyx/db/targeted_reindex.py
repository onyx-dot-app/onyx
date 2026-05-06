"""DB helpers for the targeted-reindex flow.

The API path takes a list of error IDs (failure-driven retry) or a list
of `(cc_pair_id, document_id)` tuples (arbitrary reindex), validates +
dedups them, then writes:

    1. one `targeted_reindex_job` row,
    2. N `targeted_reindex_job_target` rows (one per doc),
    3. one synthetic `IndexAttempt` per `(cc_pair_id, search_settings_id)`
       tuple the targets span. The synthetic attempts carry
       `targeted_reindex_job_id` and skip the
       `try_create_index_attempt` fence (full crawls are allowed to
       overlap with retries by design).

Nothing here enqueues celery work — that's the caller's job. Helpers
return the job_id + per-request counts for the API response.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import IndexingStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import TargetedReindexJob
from onyx.db.models import TargetedReindexJobTarget
from onyx.db.search_settings import get_active_search_settings_list
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Cap per request. Holds at the API layer; documented in the design doc.
MAX_TARGETS_PER_REQUEST = 100


class TargetSpec(BaseModel):
    """A doc the caller wants reindexed.

    `source_error_id` is set when the API resolved this target from an
    `IndexAttemptError`; NULL when the request came in as an arbitrary
    `(cc_pair_id, document_id)` pair.
    """

    cc_pair_id: int
    document_id: str
    source_error_id: int | None = None


class CreateTargetedReindexJobResult(BaseModel):
    """Return value of `create_targeted_reindex_job`.

    - `targeted_reindex_job_id`: row id; the FE polls the GET status
      endpoint with this value.
    - `celery_task_id`: pre-allocated UUID. Caller (API endpoint) uses
      this as the `task_id` arg to `apply_async` so the orphan-detector
      can clean up if dispatch fails after the DB rows commit.
    - `queued_count`: targets that survived dedup and got persisted.
    - `skipped_count`: dedup + caller-supplied upstream skips, persisted
      on the job row so the GET endpoint returns it before the task
      runs.
    - `cc_pair_search_settings_pairs`: the (cc_pair_id, search_settings_id)
      tuples we spawned synthetic IndexAttempts for. Mostly informational
      — the task re-queries by `targeted_reindex_job_id` and doesn't
      need this field directly.
    - `synthetic_attempt_ids`: the IndexAttempt rows the task will
      transition through the lifecycle.
    """

    targeted_reindex_job_id: int
    celery_task_id: str
    queued_count: int
    skipped_count: int
    cc_pair_search_settings_pairs: list[tuple[int, int]]
    synthetic_attempt_ids: list[int]


def resolve_error_ids_to_targets(
    db_session: Session, error_ids: Sequence[int]
) -> tuple[list[TargetSpec], int]:
    """Convert a list of error IDs into target specs.

    Returns `(targets, skipped_count)` where `skipped_count` counts
    errors that were already resolved at request time (no work to do)
    and errors that were entity-level (not document-level) and so can't
    be retried per-doc.
    """
    if not error_ids:
        return [], 0

    rows = (
        db_session.execute(
            select(IndexAttemptError).where(IndexAttemptError.id.in_(error_ids))
        )
        .scalars()
        .all()
    )

    targets: list[TargetSpec] = []
    skipped = 0
    for err in rows:
        if err.is_resolved:
            skipped += 1
            continue
        if err.document_id is None:
            # Entity-level error (e.g. a Confluence space failed); not
            # reindexable per-document.
            skipped += 1
            continue
        targets.append(
            TargetSpec(
                cc_pair_id=err.connector_credential_pair_id,
                document_id=err.document_id,
                source_error_id=err.id,
            )
        )
    # Errors not found in DB (caller passed invalid IDs) are also skipped.
    found_ids = {err.id for err in rows}
    skipped += len(set(error_ids) - found_ids)
    return targets, skipped


def create_targeted_reindex_job(
    db_session: Session,
    requested_by_user_id: UUID | None,
    targets: Sequence[TargetSpec],
    upstream_skipped_count: int = 0,
) -> CreateTargetedReindexJobResult:
    """Persist a targeted reindex request.

    Writes the job row, target rows, and one synthetic IndexAttempt per
    `(cc_pair_id, search_settings_id)` tuple. Pre-allocates the celery
    task UUID so the orphan-detector can clean up if `apply_async` fails
    after this returns.

    `upstream_skipped_count` is added to the dedup-skipped count and
    persisted on the job row so the GET status endpoint can return the
    full at-create-time skip count (e.g. error_ids that resolved to
    already-resolved or entity-level rows in the API layer). The task
    later folds in any runtime skips.

    The caller (API endpoint) is responsible for enqueueing the celery
    task with the returned `celery_task_id` after this commits.
    """
    if not targets:
        raise ValueError("at least one target required")
    if len(targets) > MAX_TARGETS_PER_REQUEST:
        raise ValueError(
            "too many targets: %s > %s" % (len(targets), MAX_TARGETS_PER_REQUEST)
        )

    # Validate cc_pair_ids exist before writing anything.
    cc_pair_ids = {t.cc_pair_id for t in targets}
    existing_pairs = {
        row[0]
        for row in db_session.execute(
            select(ConnectorCredentialPair.id).where(
                ConnectorCredentialPair.id.in_(cc_pair_ids)
            )
        ).all()
    }
    missing = cc_pair_ids - existing_pairs
    if missing:
        raise ValueError("unknown cc_pair_ids: %s" % sorted(missing))

    celery_task_id = str(uuid4())

    # Dedup at the (cc_pair_id, document_id) level — composite PK on the
    # target table would catch this anyway, but better to error early.
    # When the same (cc_pair, doc) appears more than once, prefer the
    # spec that carries `source_error_id`. The API can hand us derived
    # (failure-driven) and manual specs in any order; the linkage-bearing
    # one must win or the task can't mark the original error resolved.
    by_key: dict[tuple[int, str], TargetSpec] = {}
    for t in targets:
        key = (t.cc_pair_id, t.document_id)
        existing = by_key.get(key)
        if existing is None or (
            existing.source_error_id is None and t.source_error_id is not None
        ):
            by_key[key] = t
    deduped: list[TargetSpec] = list(by_key.values())

    dedup_skipped = len(targets) - len(deduped)
    initial_skipped = dedup_skipped + upstream_skipped_count

    job = TargetedReindexJob(
        requested_by_user_id=requested_by_user_id,
        celery_task_id=celery_task_id,
        status=IndexingStatus.NOT_STARTED,
        skipped_count=initial_skipped,
    )
    db_session.add(job)
    db_session.flush()

    for t in deduped:
        db_session.add(
            TargetedReindexJobTarget(
                targeted_reindex_job_id=job.id,
                cc_pair_id=t.cc_pair_id,
                document_id=t.document_id,
                source_error_id=t.source_error_id,
            )
        )

    # Spawn a synthetic IndexAttempt per (cc_pair_id, search_settings_id).
    # These bypass try_create_index_attempt — full crawls are allowed to
    # overlap with retries (per-doc row-locks handle write conflicts).
    # Active search settings = primary plus the secondary if a model swap
    # is in progress (FUTURE); reusing the canonical helper here keeps
    # the targeted-reindex flow aligned with the main indexing path.
    cc_pair_ids = {t.cc_pair_id for t in deduped}
    active_search_settings = get_active_search_settings_list(db_session)
    attempt_ids: list[int] = []
    pairs: list[tuple[int, int]] = []
    for cc_pair_id in cc_pair_ids:
        for search_settings in active_search_settings:
            attempt = IndexAttempt(
                connector_credential_pair_id=cc_pair_id,
                search_settings_id=search_settings.id,
                from_beginning=False,
                status=IndexingStatus.NOT_STARTED,
                targeted_reindex_job_id=job.id,
            )
            db_session.add(attempt)
            db_session.flush()
            attempt_ids.append(attempt.id)
            pairs.append((cc_pair_id, search_settings.id))

    db_session.commit()
    db_session.refresh(job)

    return CreateTargetedReindexJobResult(
        targeted_reindex_job_id=job.id,
        celery_task_id=celery_task_id,
        queued_count=len(deduped),
        skipped_count=initial_skipped,
        cc_pair_search_settings_pairs=pairs,
        synthetic_attempt_ids=attempt_ids,
    )


def get_targeted_reindex_job(
    db_session: Session, job_id: int
) -> TargetedReindexJob | None:
    return db_session.get(TargetedReindexJob, job_id)


def count_targets_for_job(db_session: Session, job_id: int) -> int:
    return (
        db_session.query(TargetedReindexJobTarget)
        .filter(TargetedReindexJobTarget.targeted_reindex_job_id == job_id)
        .count()
    )


def get_targets_for_job(
    db_session: Session, job_id: int
) -> list[TargetedReindexJobTarget]:
    """All target rows for a targeted-reindex job, in insertion order."""
    return (
        db_session.query(TargetedReindexJobTarget)
        .filter(TargetedReindexJobTarget.targeted_reindex_job_id == job_id)
        .all()
    )


def get_index_attempts_for_targeted_reindex_job(
    db_session: Session, job_id: int
) -> list[IndexAttempt]:
    """All synthetic IndexAttempts spawned for a targeted-reindex job."""
    return (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.targeted_reindex_job_id == job_id)
        .all()
    )


def resolve_failure_derived_targets(
    db_session: Session,
    job_id: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Mark `IndexAttemptError` rows resolved for every target whose
    `source_error_id` is set. Returns `(resolved_count, summary)`.

    `summary` is a snapshot of the cleared error rows captured before
    we update them, so it survives the eventual retention cleanup of
    `index_attempt_errors`.
    """
    target_rows = (
        db_session.query(TargetedReindexJobTarget)
        .filter(
            TargetedReindexJobTarget.targeted_reindex_job_id == job_id,
            TargetedReindexJobTarget.source_error_id.isnot(None),
        )
        .all()
    )
    if not target_rows:
        return 0, []

    error_ids = [
        t.source_error_id for t in target_rows if t.source_error_id is not None
    ]
    error_rows = (
        db_session.query(IndexAttemptError)
        .filter(
            IndexAttemptError.id.in_(error_ids),
            IndexAttemptError.is_resolved.is_(False),
        )
        .all()
    )

    summary = [
        {
            "id": e.id,
            "document_id": e.document_id,
            "failure_message": e.failure_message,
            "error_type": e.error_type,
            "connector_credential_pair_id": e.connector_credential_pair_id,
            "index_attempt_id": e.index_attempt_id,
        }
        for e in error_rows
    ]

    for e in error_rows:
        e.is_resolved = True

    return len(error_rows), summary
