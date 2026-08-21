"""DB accessors for the latest-only credential capability reports.

One row per (credential, connector-scope): ``connector_id`` NULL is the
config-less credential-time report, non-NULL is one per attached connector.
Writers upsert against the scope's partial unique index, so concurrent writers
resolve to one row instead of racing an insert.

Two writer classes share these rows, with fixed precedence: granular named-check
runs write through ``upsert_completed_capability_report`` and replace whatever
is stored (latest-only truth); the coarse blocking-validation recorder writes
through the ``unless_granular`` variant and never replaces a granular report.
``mark_capability_report_running`` belongs to the check-runner lifecycle: it
flags a run in flight while the last completed report stays readable.
"""

from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy import ColumnElement, func, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import CredentialCapabilityReport
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import CredentialCapabilityReportRow

# A stored report is granular when any check result came from a named check;
# report serialization always writes ``is_fallback`` explicitly.
_STORED_REPORT_IS_NOT_GRANULAR: ColumnElement[bool] = or_(
    CredentialCapabilityReportRow.report.is_(None),
    ~func.jsonb_path_exists(
        CredentialCapabilityReportRow.report,
        literal_column("'$.check_results[*] ? (@.is_fallback == false)'::jsonpath"),
    ),
)


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
    update_where: ColumnElement[bool] | None = None,
) -> CredentialCapabilityReportRow | None:
    """Inserts or updates the scope's single row with ``values``.

    Columns absent from ``values`` keep their stored value on the update path,
    which is how RUNNING marks preserve the previous report and completion
    writes preserve ``run_started_at``. The statement executes immediately, but
    the caller owns the transaction and must commit. ``update_where`` guards
    only the conflict-update path: when the stored row fails it, nothing is
    written and None is returned.
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
            where=update_where,
        )
        .returning(CredentialCapabilityReportRow)
    )
    # ``populate_existing``: without it, RETURNING resolves to the stale
    # identity-map instance when the caller's session already holds this row.
    return db_session.scalars(
        stmt, execution_options={"populate_existing": True}
    ).one_or_none()


def _completed_values(
    connector_id: int | None,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
    report: CredentialCapabilityReport,
    connector_config_hash: str | None,
) -> _CapabilityReportValues:
    # A connector-scoped report always ran against a config, a credential-time
    # one never did; enforcing the pairing keeps an omitted hash from silently
    # erasing the staleness signal. ``connector_id`` is taken only for this.
    assert (connector_id is None) == (connector_config_hash is None), (
        "Connector-scoped reports must carry a config hash; credential-scoped "
        "reports must not."
    )
    return {
        "source": source,
        "trigger": trigger,
        "report": report.model_dump(mode="json"),
        "connector_config_hash": connector_config_hash,
        "run_status": CapabilityReportRunStatus.COMPLETED,
    }


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
    row = _upsert_row(
        db_session,
        credential_id=credential_id,
        connector_id=connector_id,
        values=_completed_values(
            connector_id, source, trigger, report, connector_config_hash
        ),
    )
    assert row is not None, "An unguarded upsert always returns the row."
    return row


def upsert_completed_capability_report_unless_granular(
    db_session: Session,
    *,
    credential_id: int,
    connector_id: int | None,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
    report: CredentialCapabilityReport,
    connector_config_hash: str | None = None,
) -> CredentialCapabilityReportRow | None:
    """Writes a finished report unless the stored one came from named checks.

    The "unless" is not Python logic: it compiles into the statement as ``ON
    CONFLICT DO UPDATE ... WHERE <stored report is not granular>``. A
    read-then-decide here would race a concurrent granular write; Postgres
    evaluates the guard against the stored row atomically, so a granular report
    can never be replaced by this coarse write (the no-clobber rule). Returns
    None when the stored report was preserved.
    """
    return _upsert_row(
        db_session,
        credential_id=credential_id,
        connector_id=connector_id,
        values=_completed_values(
            connector_id, source, trigger, report, connector_config_hash
        ),
        # The "unless": evaluated by Postgres inside the upsert, not here.
        update_where=_STORED_REPORT_IS_NOT_GRANULAR,
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
    row = _upsert_row(
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
    assert row is not None, "An unguarded upsert always returns the row."
    return row


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
