"""Runs and errors an admin marked resolved. A resolution only moves a run out
of the open failures and errors; the run keeps its status."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    and_,
    exists,
    func,
    literal,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased

from onyx.configs.constants import NotificationType
from onyx.db.connector_alerts import clear_connector_alerts__no_commit
from onyx.db.enums import (
    CCPairRunKind,
    IndexAttemptErrorResolvedReason,
    IndexingStatus,
    IndexModelStatus,
)
from onyx.db.models import (
    CCPairRunResolution,
    ConnectorCredentialPair,
    IndexAttempt,
    IndexAttemptError,
    SearchSettings,
)


def index_attempt_error_is_open(
    error: type[IndexAttemptError] = IndexAttemptError,
) -> ColumnElement[bool]:
    """An error no run closed and no admin resolved."""
    # NOT is_resolved, not `IS false`, so Postgres matches the partial index.
    return and_(~error.is_resolved, error.resolved_reason.is_(None))


def index_attempt_error_closure(
    reason: IndexAttemptErrorResolvedReason, resolved_by_index_attempt_id: int | None
) -> dict[str, object]:
    """The values that close an error for ``reason``. The time is the
    database's, which ``time_created`` and run resolutions use too."""
    return {
        "is_resolved": reason is not IndexAttemptErrorResolvedReason.WITHOUT_RETRY,
        "resolved_reason": reason,
        "resolved_by_index_attempt_id": resolved_by_index_attempt_id,
        "resolved_at": func.now(),
    }


def _reopened_after_resolution() -> ColumnElement[bool]:
    """A resolved index run that holds an open error, or failed after its
    resolution. Resolving closes the committed errors stamped before it, so an
    open one arrived later, even from a writer that began before the click."""
    open_error: type[IndexAttemptError] = aliased(IndexAttemptError)
    attempt: type[IndexAttempt] = aliased(IndexAttempt)
    return and_(
        CCPairRunResolution.run_kind == CCPairRunKind.INDEXING.value,
        or_(
            exists().where(
                open_error.index_attempt_id == CCPairRunResolution.attempt_id,
                index_attempt_error_is_open(open_error),
            ),
            exists().where(
                attempt.id == CCPairRunResolution.attempt_id,
                attempt.status == IndexingStatus.FAILED,
                attempt.time_finished > CCPairRunResolution.resolved_at,
            ),
        ),
    )


def run_is_resolved(
    kind: CCPairRunKind, run_id: InstrumentedAttribute[int]
) -> ColumnElement[bool]:
    """Whether the run of ``kind`` at ``run_id`` has a resolution nothing
    reopened, for a feed query."""
    return exists().where(
        CCPairRunResolution.run_kind == literal(kind.value),
        CCPairRunResolution.attempt_id == run_id,
        ~_reopened_after_resolution(),
    )


def resolve_runs__no_commit(
    db_session: Session,
    runs: dict[tuple[CCPairRunKind, int], int],
    user_id: UUID | None,
) -> dict[tuple[CCPairRunKind, int], int]:
    """Marks each (kind, id) resolved against the pair it maps to, closes the
    errors each index run filed so far without retry, and returns the runs it
    changed with their pairs. A run resolved before counts only when something
    reopened it or it had errors to close. ``user_id`` None is the system."""
    if not runs:
        return {}
    index_run_ids: list[int] = [
        run_id for kind, run_id in runs if kind is CCPairRunKind.INDEXING
    ]
    stmt = (
        insert(CCPairRunResolution)
        .values(
            [
                {
                    "run_kind": kind.value,
                    "attempt_id": run_id,
                    "cc_pair_id": cc_pair_id,
                    "resolved_by_user_id": user_id,
                }
                for (kind, run_id), cc_pair_id in runs.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["run_kind", "attempt_id"])
        .returning(CCPairRunResolution.run_kind, CCPairRunResolution.attempt_id)
    )
    changed: set[tuple[CCPairRunKind, int]] = {
        (CCPairRunKind(kind), run_id) for kind, run_id in db_session.execute(stmt)
    }
    if index_run_ids:
        reresolved = _reresolve_reopened_index_runs__no_commit(
            db_session, index_run_ids, user_id
        )
        closed = _close_without_retry__no_commit(
            db_session,
            IndexAttemptError.index_attempt_id,
            IndexAttemptError.index_attempt_id.in_(index_run_ids),
            # The transaction start the resolution records, so an error
            # stamped after the click stays open and reopens the run.
            IndexAttemptError.time_created <= func.now(),
        )
        changed.update(
            (CCPairRunKind.INDEXING, run_id) for run_id in [*reresolved, *closed]
        )
    clear_resolved_repeated_error_states__no_commit(db_session, set(runs.values()))
    return {run: runs[run] for run in changed}


def _reresolve_reopened_index_runs__no_commit(
    db_session: Session, index_run_ids: list[int], user_id: UUID | None
) -> list[int]:
    """Moves the reopened resolutions among ``index_run_ids`` to now and returns
    their runs, so only what follows this resolution reopens them again."""
    return list(
        db_session.scalars(
            update(CCPairRunResolution)
            .where(
                CCPairRunResolution.run_kind == CCPairRunKind.INDEXING.value,
                CCPairRunResolution.attempt_id.in_(index_run_ids),
                _reopened_after_resolution(),
            )
            .values(resolved_at=func.now(), resolved_by_user_id=user_id)
            .returning(CCPairRunResolution.attempt_id)
            .execution_options(synchronize_session=False)
        ).all()
    )


def _close_without_retry__no_commit(
    db_session: Session,
    returning: InstrumentedAttribute[int],
    *scope: ColumnElement[bool],
) -> list[int]:
    """Marks the open errors in ``scope`` resolved without retry and returns
    ``returning`` of each row it marked."""
    return list(
        db_session.scalars(
            update(IndexAttemptError)
            .where(index_attempt_error_is_open(), *scope)
            .values(
                **index_attempt_error_closure(
                    IndexAttemptErrorResolvedReason.WITHOUT_RETRY, None
                )
            )
            .returning(returning)
            .execution_options(synchronize_session=False)
        ).all()
    )


def resolve_errors_without_retry__no_commit(
    db_session: Session, cc_pair_id: int, error_ids: Collection[int]
) -> list[int]:
    """Closes the pair's chosen open errors without retry and returns the ids
    it closed. Errors of other pairs and errors already closed are skipped."""
    if not error_ids:
        return []
    return _close_without_retry__no_commit(
        db_session,
        IndexAttemptError.id,
        IndexAttemptError.id.in_(error_ids),
        IndexAttemptError.connector_credential_pair_id == cc_pair_id,
    )


def clear_resolved_repeated_error_states__no_commit(
    db_session: Session, cc_pair_ids: Collection[int]
) -> list[int]:
    """Clears the repeated error flag and alert of each pair whose latest failed
    index attempt is resolved, and returns the pairs whose flag it cleared. The
    pair keeps its status, so a pair Cloud paused stays paused."""
    if not cc_pair_ids:
        return []
    latest_failed = db_session.execute(
        select(IndexAttempt.connector_credential_pair_id, IndexAttempt.id)
        .join(SearchSettings)
        .where(
            IndexAttempt.connector_credential_pair_id.in_(cc_pair_ids),
            SearchSettings.status == IndexModelStatus.PRESENT,
            IndexAttempt.status == IndexingStatus.FAILED,
            IndexAttempt.targeted_reindex_job_id.is_(None),
            IndexAttempt.is_backfill.is_(False),
        )
        .distinct(IndexAttempt.connector_credential_pair_id)
        .order_by(
            IndexAttempt.connector_credential_pair_id,
            IndexAttempt.time_created.desc(),
            IndexAttempt.id.desc(),
        )
    ).all()
    resolved = get_resolution_times(
        db_session,
        [(CCPairRunKind.INDEXING, attempt_id) for _, attempt_id in latest_failed],
    )
    resolved_pairs = [
        cc_pair_id
        for cc_pair_id, attempt_id in latest_failed
        if (CCPairRunKind.INDEXING, attempt_id) in resolved
    ]
    if not resolved_pairs:
        return []
    # Unflagged pairs too: a beat can raise the alert just before it sets the flag.
    for cc_pair_id in resolved_pairs:
        clear_connector_alerts__no_commit(
            db_session, cc_pair_id, NotificationType.CONNECTOR_REPEATED_ERRORS
        )
    return list(
        db_session.scalars(
            update(ConnectorCredentialPair)
            .where(
                ConnectorCredentialPair.id.in_(resolved_pairs),
                ConnectorCredentialPair.in_repeated_error_state.is_(True),
            )
            .values(in_repeated_error_state=False)
            .returning(ConnectorCredentialPair.id)
        ).all()
    )


def get_resolution_times(
    db_session: Session, runs: list[tuple[CCPairRunKind, int]]
) -> dict[tuple[CCPairRunKind, int], datetime]:
    """When each resolved run among ``runs`` was resolved, leaving out the
    reopened ones."""
    if not runs:
        return {}
    rows = db_session.execute(
        select(
            CCPairRunResolution.run_kind,
            CCPairRunResolution.attempt_id,
            CCPairRunResolution.resolved_at,
        ).where(
            tuple_(CCPairRunResolution.run_kind, CCPairRunResolution.attempt_id).in_(
                [(kind.value, run_id) for kind, run_id in runs]
            ),
            ~_reopened_after_resolution(),
        )
    ).all()
    return {
        (CCPairRunKind(kind), run_id): resolved_at for kind, run_id, resolved_at in rows
    }
