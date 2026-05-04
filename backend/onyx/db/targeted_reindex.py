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
from uuid import UUID
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import SearchSettings
from onyx.db.models import TargetedReindexJob
from onyx.db.models import TargetedReindexJobTarget
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


def _group_targets_by_search_settings(
    db_session: Session, targets: Sequence[TargetSpec]
) -> dict[int, set[int]]:
    """Map cc_pair_id → set of `search_settings_id` it should write to.

    A targeted reindex needs to write to whatever search settings the
    cc_pair currently indexes against. During an embedding-model swap
    that's both PRESENT and FUTURE — otherwise the FUTURE index lags
    by the targeted-reindex delta until the next full crawl.
    """
    cc_pair_ids = {t.cc_pair_id for t in targets}
    if not cc_pair_ids:
        return {}
    active_settings = (
        db_session.execute(
            select(SearchSettings).where(
                SearchSettings.status.in_(
                    [IndexModelStatus.PRESENT, IndexModelStatus.FUTURE]
                )
            )
        )
        .scalars()
        .all()
    )
    settings_ids = {s.id for s in active_settings}
    return {cc_pair_id: settings_ids for cc_pair_id in cc_pair_ids}


def create_targeted_reindex_job(
    db_session: Session,
    requested_by_user_id: UUID | None,
    targets: Sequence[TargetSpec],
) -> CreateTargetedReindexJobResult:
    """Persist a targeted reindex request.

    Writes the job row, target rows, and one synthetic IndexAttempt per
    `(cc_pair_id, search_settings_id)` tuple. Pre-allocates the celery
    task UUID so the orphan-detector can clean up if `apply_async` fails
    after this returns.

    The caller (API endpoint) is responsible for enqueueing the celery
    task with the returned `celery_task_id` after this commits.
    """
    if not targets:
        raise ValueError("at least one target required")
    if len(targets) > MAX_TARGETS_PER_REQUEST:
        raise ValueError(
            f"too many targets: {len(targets)} > {MAX_TARGETS_PER_REQUEST}"
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
        raise ValueError(f"unknown cc_pair_ids: {sorted(missing)}")

    celery_task_id = str(uuid4())

    job = TargetedReindexJob(
        requested_by_user_id=requested_by_user_id,
        celery_task_id=celery_task_id,
        status=IndexingStatus.NOT_STARTED,
    )
    db_session.add(job)
    db_session.flush()

    # Dedup at the (cc_pair_id, document_id) level — composite PK on the
    # target table would catch this anyway, but better to error early.
    seen: set[tuple[int, str]] = set()
    deduped: list[TargetSpec] = []
    for t in targets:
        key = (t.cc_pair_id, t.document_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)

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
    grouped = _group_targets_by_search_settings(db_session, deduped)
    attempt_ids: list[int] = []
    pairs: list[tuple[int, int]] = []
    for cc_pair_id, search_settings_ids in grouped.items():
        for search_settings_id in search_settings_ids:
            attempt = IndexAttempt(
                connector_credential_pair_id=cc_pair_id,
                search_settings_id=search_settings_id,
                from_beginning=False,
                status=IndexingStatus.NOT_STARTED,
                targeted_reindex_job_id=job.id,
            )
            db_session.add(attempt)
            db_session.flush()
            attempt_ids.append(attempt.id)
            pairs.append((cc_pair_id, search_settings_id))

    db_session.commit()
    db_session.refresh(job)

    return CreateTargetedReindexJobResult(
        targeted_reindex_job_id=job.id,
        celery_task_id=celery_task_id,
        queued_count=len(deduped),
        skipped_count=len(targets) - len(deduped),
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
