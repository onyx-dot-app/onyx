"""DB accessors for the latest-only credential capability reports.

One row per (credential, connector-scope): ``connector_id`` NULL is the
config-less credential-time report, non-NULL is one per attached connector.
Writers upsert against the scope's partial unique index, so concurrent writers
resolve to one row instead of racing an insert.
"""

from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import CredentialCapabilityReport
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import CredentialCapabilityReportRow


class _CapabilityReportValues(TypedDict, total=False):
    """Columns an upsert may write; each writer passes only what it changes."""

    source: DocumentSource
    trigger: CapabilityCheckTrigger
    report: dict[str, Any]
    connector_config_hash: str | None
    run_status: CapabilityReportRunStatus
    run_started_at: ColumnElement[datetime]
    time_updated: ColumnElement[datetime]


def _scope_conflict_kwargs(connector_id: int | None) -> dict[str, Any]:
    """ON CONFLICT inference for the row's scope-specific partial index."""
    index_elements = [CredentialCapabilityReportRow.credential_id]
    index_where = "connector_id IS NULL"
    if connector_id is not None:
        index_elements.append(CredentialCapabilityReportRow.connector_id)
        index_where = "connector_id IS NOT NULL"
    return {"index_elements": index_elements, "index_where": text(index_where)}


def _upsert_row(
    db_session: Session,
    *,
    credential_id: int,
    connector_id: int | None,
    values: _CapabilityReportValues,
) -> CredentialCapabilityReportRow:
    """Inserts or updates the scope's single row with ``values``.

    Columns absent from ``values`` keep their stored value on the update path,
    which is how RUNNING marks preserve the previous report and completion
    writes preserve ``run_started_at``. The statement executes immediately, but
    the caller owns the transaction and must commit.
    """
    # Stamp both the insert and the conflict-update path explicitly: the model's
    # ``onupdate`` is not applied to ON CONFLICT SET clauses, and the ``now()``
    # defaults are transaction-start time, which would stamp every write of one
    # transaction identically.
    stamped: _CapabilityReportValues = {
        **values,
        "time_updated": func.statement_timestamp(),
    }
    stmt = (
        insert(CredentialCapabilityReportRow)
        .values(credential_id=credential_id, connector_id=connector_id, **stamped)
        .on_conflict_do_update(
            **_scope_conflict_kwargs(connector_id),
            set_=stamped,
        )
        .returning(CredentialCapabilityReportRow)
    )
    # ``populate_existing``: without it, RETURNING resolves to the stale
    # identity-map instance when the caller's session already holds this row.
    return db_session.scalars(stmt, execution_options={"populate_existing": True}).one()


def upsert_completed_capability_report(
    db_session: Session,
    *,
    credential_id: int,
    connector_id: int | None,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
    report: CredentialCapabilityReport,
    connector_config_hash: str | None = None,
) -> CredentialCapabilityReportRow:
    """Writes a finished report onto the scope's row (latest-only replace)."""
    # A connector-scoped report always ran against a config, a credential-time
    # one never did; enforcing the pairing keeps an omitted hash from silently
    # erasing the staleness signal.
    assert (connector_id is None) == (connector_config_hash is None), (
        "Connector-scoped reports must carry a config hash; credential-scoped "
        "reports must not."
    )
    return _upsert_row(
        db_session,
        credential_id=credential_id,
        connector_id=connector_id,
        values={
            "source": source,
            "trigger": trigger,
            "report": report.model_dump(mode="json"),
            "connector_config_hash": connector_config_hash,
            "run_status": CapabilityReportRunStatus.COMPLETED,
        },
    )


def mark_capability_report_running(
    db_session: Session,
    *,
    credential_id: int,
    connector_id: int | None,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
) -> CredentialCapabilityReportRow:
    """Flags the scope's row RUNNING with a fresh start time.

    The previous COMPLETED ``report`` stays readable while the run is in flight.
    """
    return _upsert_row(
        db_session,
        credential_id=credential_id,
        connector_id=connector_id,
        values={
            "source": source,
            "trigger": trigger,
            "run_status": CapabilityReportRunStatus.RUNNING,
            # Statement time, not ``now()``: the run starts now, not when the
            # caller's transaction began.
            "run_started_at": func.statement_timestamp(),
        },
    )


def get_capability_report_row(
    db_session: Session,
    credential_id: int,
    connector_id: int | None,
) -> CredentialCapabilityReportRow | None:
    """Returns the scope's row; it is the latest report by construction."""
    stmt = select(CredentialCapabilityReportRow).where(
        CredentialCapabilityReportRow.credential_id == credential_id
    )
    if connector_id is None:
        stmt = stmt.where(CredentialCapabilityReportRow.connector_id.is_(None))
    else:
        stmt = stmt.where(CredentialCapabilityReportRow.connector_id == connector_id)
    return db_session.scalars(stmt).one_or_none()


def get_capability_report_rows_for_source(
    db_session: Session,
    source: DocumentSource,
) -> list[CredentialCapabilityReportRow]:
    """Returns every report row for a source, most recently updated first."""
    stmt = (
        select(CredentialCapabilityReportRow)
        .where(CredentialCapabilityReportRow.source == source)
        # ``id`` breaks timestamp ties deterministically.
        .order_by(
            CredentialCapabilityReportRow.time_updated.desc(),
            CredentialCapabilityReportRow.id.desc(),
        )
    )
    return list(db_session.scalars(stmt).all())
