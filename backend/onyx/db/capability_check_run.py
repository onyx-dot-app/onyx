"""DB accessors for the append-only capability-check run history.

One row per run attempt: the row is inserted RUNNING with the run's inputs,
accumulates results as checks complete, and is finished exactly once with a
terminal status. Because each attempt owns its row, none of the latest-only
table's machinery applies here: no upsert, no run-id fencing, no no-clobber
guards (contrast ``onyx.db.credential_capability``). The terminal writers are
guarded on RUNNING instead, which makes a finished row immutable history.

Nothing here commits; the caller owns the transaction. A time-based retention
sweep (``delete_capability_check_runs_older_than``) bounds the table.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, cast, delete, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import CapabilityCheckResult
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import CapabilityCheckRunRow

# Ordering shared by every listing: newest first, with ``run_id`` breaking
# statement-timestamp ties deterministically (inserts in one transaction share
# the clock).
_NEWEST_FIRST = (
    CapabilityCheckRunRow.run_started_at.desc(),
    CapabilityCheckRunRow.run_id.desc(),
)


def _connector_scope_clause(connector_id: int | None) -> ColumnElement[bool]:
    """WHERE clause selecting a scope's rows; None is the credential-time scope."""
    if connector_id is None:
        return CapabilityCheckRunRow.connector_id.is_(None)
    return CapabilityCheckRunRow.connector_id == connector_id


def create_capability_check_run(
    db_session: Session,
    *,
    credential_id: int,
    connector_id: int | None = None,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
    creation_session_id: UUID | None = None,
    check_ids_requested: list[str] | None = None,
    connector_config: dict[str, Any] | None = None,
    connector_config_hash: str | None = None,
) -> CapabilityCheckRunRow:
    """Appends a RUNNING row recording the attempt and its inputs.

    ``check_ids_requested`` must be canonically sorted by the caller (the dedup
    lookup compares it by JSONB equality, which is order-sensitive); None is a
    full-registry run. ``connector_config`` must never contain credential
    material -- credential inputs are the ``credential_id`` alone.
    """
    # The hash is derived from the config: each must appear with the other, or
    # the dedup key would silently stop matching the stored inputs.
    if (connector_config is None) != (connector_config_hash is None):
        raise ValueError(
            "A config snapshot and its hash must be stored together or not at all."
        )
    row = CapabilityCheckRunRow(
        credential_id=credential_id,
        connector_id=connector_id,
        source=source,
        creation_session_id=creation_session_id,
        trigger=trigger,
        check_ids_requested=check_ids_requested,
        connector_config=connector_config,
        connector_config_hash=connector_config_hash,
        run_status=CapabilityReportRunStatus.RUNNING,
        # Statement time, not ``now()``: the run starts now, not when the
        # caller's transaction began.
        run_started_at=func.statement_timestamp(),
        results=None,
    )
    db_session.add(row)
    db_session.flush()
    # Resolve the server-side start timestamp so the returned row is readable.
    db_session.refresh(row)
    return row


def record_capability_check_run_progress(
    db_session: Session,
    *,
    run_id: UUID,
    results: Sequence[CapabilityCheckResult],
) -> bool:
    """Writes the run's results-so-far onto its row; True when it landed.

    Every write replaces the whole list, so the column always holds a prefix of
    the list the run will finish with. Guarded on RUNNING: a finished row is
    immutable history, so a straggler thread's late progress is discarded.
    """
    stmt = (
        update(CapabilityCheckRunRow)
        .where(
            CapabilityCheckRunRow.run_id == run_id,
            CapabilityCheckRunRow.run_status == CapabilityReportRunStatus.RUNNING,
        )
        .values(results=[result.model_dump(mode="json") for result in results])
    )
    result = db_session.execute(stmt)
    return int(result.rowcount) > 0  # ty: ignore[unresolved-attribute]


def _finish_capability_check_run(
    db_session: Session,
    run_id: UUID,
    run_status: CapabilityReportRunStatus,
    results: Sequence[CapabilityCheckResult] | None,
) -> CapabilityCheckRunRow | None:
    """The single terminal writer; lands at most once per row.

    Guarded on RUNNING, so whichever terminal write executes first wins and
    every later one returns None instead of rewriting history. ``results`` None
    preserves whatever progress the run streamed before dying.
    """
    values: dict[str, Any] = {
        "run_status": run_status,
        "run_finished_at": func.statement_timestamp(),
    }
    if results is not None:
        values["results"] = [result.model_dump(mode="json") for result in results]
    stmt = (
        update(CapabilityCheckRunRow)
        .where(
            CapabilityCheckRunRow.run_id == run_id,
            CapabilityCheckRunRow.run_status == CapabilityReportRunStatus.RUNNING,
        )
        .values(**values)
        .returning(CapabilityCheckRunRow)
    )
    # ``populate_existing``: without it, RETURNING resolves to the stale
    # identity-map instance when the caller's session already holds this row.
    return db_session.scalars(
        stmt, execution_options={"populate_existing": True}
    ).one_or_none()


def complete_capability_check_run(
    db_session: Session,
    *,
    run_id: UUID,
    results: Sequence[CapabilityCheckResult],
) -> CapabilityCheckRunRow | None:
    """Finishes the run COMPLETED with its final results.

    Returns None when the row is missing or already terminal (the write did not
    land); stored history is never rewritten.
    """
    return _finish_capability_check_run(
        db_session, run_id, CapabilityReportRunStatus.COMPLETED, results
    )


def fail_capability_check_run(
    db_session: Session,
    *,
    run_id: UUID,
) -> CapabilityCheckRunRow | None:
    """Finishes the run FAILED_TO_RUN, keeping any streamed partial results.

    For attempts that verifiably will not complete: a failed enqueue, a failing
    task's own exit write, or a staleness sweep. Returns None when the row is
    missing or already terminal.
    """
    return _finish_capability_check_run(
        db_session, run_id, CapabilityReportRunStatus.FAILED_TO_RUN, None
    )


def get_capability_check_run(
    db_session: Session,
    run_id: UUID,
) -> CapabilityCheckRunRow | None:
    """Returns one run attempt by id.

    A SELECT rather than ``Session.get``: the identity map must not resurrect a
    row the retention sweep or an FK cascade deleted in the database.
    """
    stmt = select(CapabilityCheckRunRow).where(CapabilityCheckRunRow.run_id == run_id)
    return db_session.scalars(stmt).one_or_none()


def get_capability_check_runs_for_session(
    db_session: Session,
    creation_session_id: UUID,
) -> list[CapabilityCheckRunRow]:
    """Returns one creation-form session's runs, newest first."""
    stmt = (
        select(CapabilityCheckRunRow)
        .where(CapabilityCheckRunRow.creation_session_id == creation_session_id)
        .order_by(*_NEWEST_FIRST)
    )
    return list(db_session.scalars(stmt).all())


def get_latest_capability_check_run_for_scope(
    db_session: Session,
    credential_id: int,
    connector_id: int | None,
) -> CapabilityCheckRunRow | None:
    """Returns the scope's most recently started run attempt, if any.

    ``connector_id`` None is the config-less credential-time scope, mirroring
    the latest-only table's scoping.
    """
    stmt = (
        select(CapabilityCheckRunRow)
        .where(
            CapabilityCheckRunRow.credential_id == credential_id,
            _connector_scope_clause(connector_id),
        )
        .order_by(*_NEWEST_FIRST)
        .limit(1)
    )
    return db_session.scalars(stmt).one_or_none()


def find_recent_capability_check_run(
    db_session: Session,
    *,
    credential_id: int,
    connector_config_hash: str | None,
    check_ids_requested: list[str] | None,
    within: timedelta,
) -> CapabilityCheckRunRow | None:
    """Returns the newest run matching the request's input identity, if fresh.

    The idempotency lookup behind the decision endpoint: identical inputs
    (credential, config hash, canonically sorted check subset) re-posted within
    ``within`` resolve to the standing run instead of a duplicate enqueue.
    FAILED_TO_RUN attempts never match -- a dead attempt must not absorb its
    own retry. The cutoff is evaluated by Postgres against statement time,
    mirroring the writers' clock.
    """
    hash_clause = (
        CapabilityCheckRunRow.connector_config_hash.is_(None)
        if connector_config_hash is None
        else CapabilityCheckRunRow.connector_config_hash == connector_config_hash
    )
    # A Python list compares against JSONB only through an explicit cast; the
    # comparison is order-sensitive, hence the canonical-sort requirement.
    subset_clause = (
        CapabilityCheckRunRow.check_ids_requested.is_(None)
        if check_ids_requested is None
        else CapabilityCheckRunRow.check_ids_requested
        == cast(check_ids_requested, postgresql.JSONB())
    )
    stmt = (
        select(CapabilityCheckRunRow)
        .where(
            CapabilityCheckRunRow.credential_id == credential_id,
            hash_clause,
            subset_clause,
            CapabilityCheckRunRow.run_status != CapabilityReportRunStatus.FAILED_TO_RUN,
            CapabilityCheckRunRow.run_started_at >= func.statement_timestamp() - within,
        )
        .order_by(*_NEWEST_FIRST)
        .limit(1)
    )
    return db_session.scalars(stmt).one_or_none()


def delete_capability_check_runs_older_than(
    db_session: Session,
    *,
    retain_for: timedelta,
) -> int:
    """Deletes run rows started more than ``retain_for`` ago; returns the count.

    The retention sweep. Status-blind by design: a RUNNING row that old is a
    corpse no sweep retired, and history past the bound is gone either way.
    """
    stmt = delete(CapabilityCheckRunRow).where(
        CapabilityCheckRunRow.run_started_at < func.statement_timestamp() - retain_for
    )
    result = db_session.execute(stmt)
    return int(result.rowcount)  # ty: ignore[unresolved-attribute]
