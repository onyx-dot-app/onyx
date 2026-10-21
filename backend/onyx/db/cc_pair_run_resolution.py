"""Runs an admin marked resolved. A resolution only moves a run out of the open
failures and errors; the run keeps its status."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, exists, literal, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.configs.constants import NotificationType
from onyx.db.connector_alerts import clear_connector_alerts__no_commit
from onyx.db.enums import CCPairRunKind, IndexingStatus, IndexModelStatus
from onyx.db.models import (
    CCPairRunResolution,
    ConnectorCredentialPair,
    IndexAttempt,
    SearchSettings,
)


def run_is_resolved(
    kind: CCPairRunKind, run_id: InstrumentedAttribute[int]
) -> ColumnElement[bool]:
    """Whether the run of ``kind`` at ``run_id`` has a resolution, for a feed query."""
    return exists().where(
        CCPairRunResolution.run_kind == literal(kind.value),
        CCPairRunResolution.attempt_id == run_id,
    )


def resolve_runs__no_commit(
    db_session: Session,
    runs: dict[tuple[CCPairRunKind, int], int],
    user_id: UUID | None,
) -> int:
    """Marks each (kind, id) resolved against the pair it maps to and returns
    how many it marked. A run resolved before keeps its first resolution and is
    not counted. ``user_id`` None is the system. Clears the repeated error flag
    of a pair whose latest failure it resolves."""
    if not runs:
        return 0
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
        .returning(CCPairRunResolution.attempt_id)
    )
    marked = len(db_session.scalars(stmt).all())
    clear_resolved_repeated_error_states__no_commit(
        db_session,
        {
            cc_pair_id
            for (kind, _), cc_pair_id in runs.items()
            if kind is CCPairRunKind.INDEXING
        },
    )
    return marked


def clear_resolved_repeated_error_states__no_commit(
    db_session: Session, cc_pair_ids: Collection[int]
) -> None:
    """Takes each flagged pair whose latest failed index attempt under the
    current search settings is resolved out of the repeated error state, and
    clears its alert. The pair keeps its status, so a pair Cloud paused stays
    paused until an admin resumes it."""
    if not cc_pair_ids:
        return
    latest_failed = db_session.execute(
        select(IndexAttempt.connector_credential_pair_id, IndexAttempt.id)
        .join(SearchSettings)
        .join(ConnectorCredentialPair)
        .where(
            IndexAttempt.connector_credential_pair_id.in_(cc_pair_ids),
            ConnectorCredentialPair.in_repeated_error_state.is_(True),
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
    cleared = [
        cc_pair_id
        for cc_pair_id, attempt_id in latest_failed
        if (CCPairRunKind.INDEXING, attempt_id) in resolved
    ]
    if not cleared:
        return
    db_session.execute(
        update(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.id.in_(cleared))
        .values(in_repeated_error_state=False)
    )
    for cc_pair_id in cleared:
        clear_connector_alerts__no_commit(
            db_session, cc_pair_id, NotificationType.CONNECTOR_REPEATED_ERRORS
        )


def get_resolution_times(
    db_session: Session, runs: list[tuple[CCPairRunKind, int]]
) -> dict[tuple[CCPairRunKind, int], datetime]:
    """When each resolved run among ``runs`` was resolved."""
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
            )
        )
    ).all()
    return {
        (CCPairRunKind(kind), run_id): resolved_at for kind, run_id, resolved_at in rows
    }
