"""Runs an admin marked resolved. A resolution only moves a run out of the open
failures and errors; the run keeps its status."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, exists, literal, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.db.enums import CCPairRunKind
from onyx.db.models import CCPairRunResolution


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
    not counted. ``user_id`` None is the system."""
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
    return len(db_session.scalars(stmt).all())


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
