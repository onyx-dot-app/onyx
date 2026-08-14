"""Accessor tests for the latest-only credential capability report rows.

Runs against real Postgres: the upsert semantics live in the two partial unique
indexes and ON CONFLICT inference, which mocks cannot exercise. Nothing here
commits (the accessors leave the transaction to the caller), so every test's
rows roll back when its session closes.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CredentialCapabilityReport,
)
from onyx.db.credential_capability import (
    get_capability_report_row,
    get_capability_report_rows_for_source,
    mark_capability_report_running,
    upsert_completed_capability_report,
    upsert_completed_capability_report_unless_granular,
)
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import Credential
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


def _report(
    credential_id: int,
    connector_id: int | None = None,
    check_id: str = "slack_token_auth",
    is_fallback: bool = False,
) -> CredentialCapabilityReport:
    return CredentialCapabilityReport(
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        connector_id=connector_id,
        checked_at=datetime.now(timezone.utc),
        trigger=CapabilityCheckTrigger.MANUAL,
        verdicts={
            CredentialCapability.INDEXING: CapabilityVerdict.PASSED,
            CredentialCapability.DOC_PERMISSION_SYNC: CapabilityVerdict.NOT_APPLICABLE,
            CredentialCapability.EXTERNAL_GROUP_SYNC: CapabilityVerdict.NOT_APPLICABLE,
        },
        check_results=[
            CapabilityCheckResult(
                capability=CredentialCapability.INDEXING,
                check_id=check_id,
                display_name="Test check",
                required=True,
                status=CapabilityCheckStatus.PASSED,
                is_fallback=is_fallback,
            )
        ],
    )


@pytest.mark.usefixtures("tenant_context")
def test_upsert_inserts_then_replaces(db_session: Session) -> None:
    """Verifies latest-only semantics: a second write lands on the same row."""
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id

    # Under test.
    first = upsert_completed_capability_report(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(credential_id, check_id="first"),
    )
    second = upsert_completed_capability_report(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CREDENTIAL_CREATED,
        report=_report(credential_id, check_id="second"),
    )

    # Postcondition.
    assert second.id == first.id
    row = get_capability_report_row(db_session, credential_id, None)
    assert row is not None
    assert row.trigger == CapabilityCheckTrigger.CREDENTIAL_CREATED
    assert row.run_status == CapabilityReportRunStatus.COMPLETED
    assert row.report is not None
    assert row.report["check_results"][0]["check_id"] == "second"


@pytest.mark.usefixtures("tenant_context")
def test_credential_and_connector_scopes_coexist(db_session: Session) -> None:
    """
    Verifies the config-less credential-time row and a connector-scoped row are
    distinct rows for one credential, each fetched by its scope.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    connector_id = cc_pair.connector_id

    # Under test.
    credential_scope = upsert_completed_capability_report(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CREDENTIAL_CREATED,
        report=_report(credential_id),
    )
    connector_scope = upsert_completed_capability_report(
        db_session,
        credential_id=credential_id,
        connector_id=connector_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        report=_report(credential_id, connector_id=connector_id),
        connector_config_hash="abc123",
    )

    # Postcondition.
    assert credential_scope.id != connector_scope.id
    fetched_credential_scope = get_capability_report_row(
        db_session, credential_id, None
    )
    fetched_connector_scope = get_capability_report_row(
        db_session, credential_id, connector_id
    )
    assert fetched_credential_scope is not None
    assert fetched_credential_scope.id == credential_scope.id
    assert fetched_connector_scope is not None
    assert fetched_connector_scope.id == connector_scope.id
    assert fetched_connector_scope.connector_config_hash == "abc123"


@pytest.mark.usefixtures("tenant_context")
def test_mark_running_preserves_report_and_completion_keeps_start_time(
    db_session: Session,
) -> None:
    """
    Verifies the run lifecycle on one row: RUNNING keeps the previous report
    readable, and the completing write keeps the run's start time.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    upsert_completed_capability_report(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(credential_id, check_id="previous"),
    )

    # Under test.
    running = mark_capability_report_running(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )

    # Postcondition.
    assert running.run_status == CapabilityReportRunStatus.RUNNING
    assert running.run_started_at is not None
    assert running.report is not None
    assert running.report["check_results"][0]["check_id"] == "previous"

    # Under test and postcondition (completion preserves the start time).
    completed = upsert_completed_capability_report(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(credential_id, check_id="fresh"),
    )
    assert completed.run_status == CapabilityReportRunStatus.COMPLETED
    assert completed.run_started_at == running.run_started_at
    assert completed.report is not None
    assert completed.report["check_results"][0]["check_id"] == "fresh"


@pytest.mark.usefixtures("tenant_context")
def test_mark_running_creates_the_row_when_none_exists(db_session: Session) -> None:
    """Verifies a first-ever run starts from a report-less RUNNING row."""
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)

    # Under test.
    row = mark_capability_report_running(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CREDENTIAL_CREATED,
    )

    # Postcondition.
    assert row.run_status == CapabilityReportRunStatus.RUNNING
    assert row.report is None


@pytest.mark.usefixtures("tenant_context")
def test_rows_for_source_lists_most_recently_updated_first(
    db_session: Session,
) -> None:
    """Verifies the per-source listing includes both rows, freshest first."""
    # Precondition.
    first_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    second_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    for pair in (first_pair, second_pair):
        upsert_completed_capability_report(
            db_session,
            credential_id=pair.credential_id,
            connector_id=None,
            source=DocumentSource.SLACK,
            trigger=CapabilityCheckTrigger.MANUAL,
            report=_report(pair.credential_id),
        )
    # Touch the first row so it becomes more recently updated than the second.
    upsert_completed_capability_report(
        db_session,
        credential_id=first_pair.credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(first_pair.credential_id, check_id="touched"),
    )
    # A fresh insert after the touch must sort first: inserts and updates share
    # the statement-time clock.
    third_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    upsert_completed_capability_report(
        db_session,
        credential_id=third_pair.credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(third_pair.credential_id),
    )

    # Under test.
    rows = get_capability_report_rows_for_source(db_session, DocumentSource.SLACK)

    # Postcondition.
    # The DB may hold committed SLACK rows from other suites or prior runs, so
    # assert relative order, not equality.
    row_credential_ids = [row.credential_id for row in rows]
    third_index = row_credential_ids.index(third_pair.credential_id)
    first_index = row_credential_ids.index(first_pair.credential_id)
    second_index = row_credential_ids.index(second_pair.credential_id)
    assert third_index < first_index < second_index
    assert all(row.source == DocumentSource.SLACK for row in rows)


@pytest.mark.usefixtures("tenant_context")
def test_unless_granular_preserves_a_granular_report(db_session: Session) -> None:
    """
    Verifies the no-clobber guard: the guarded upsert is a no-op against a
    stored named-checks report and signals it by returning None.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    upsert_completed_capability_report(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(credential_id, check_id="granular"),
    )

    # Under test.
    result = upsert_completed_capability_report_unless_granular(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        report=_report(credential_id, check_id="fallback", is_fallback=True),
    )

    # Postcondition.
    assert result is None
    row = get_capability_report_row(db_session, credential_id, None)
    assert row is not None
    assert row.trigger == CapabilityCheckTrigger.MANUAL
    assert row.report is not None
    assert row.report["check_results"][0]["check_id"] == "granular"


@pytest.mark.usefixtures("tenant_context")
def test_unless_granular_inserts_and_replaces_fallback_reports(
    db_session: Session,
) -> None:
    """
    Verifies the guard only protects granular state: the guarded upsert still
    inserts into an empty scope and replaces fallback-shaped reports.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id

    # Under test.
    inserted = upsert_completed_capability_report_unless_granular(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        report=_report(credential_id, check_id="first", is_fallback=True),
    )
    replaced = upsert_completed_capability_report_unless_granular(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.INDEXING_ATTEMPT,
        report=_report(credential_id, check_id="second", is_fallback=True),
    )

    # Postcondition.
    assert inserted is not None
    assert replaced is not None
    assert replaced.id == inserted.id
    assert replaced.trigger == CapabilityCheckTrigger.INDEXING_ATTEMPT
    assert replaced.report is not None
    assert replaced.report["check_results"][0]["check_id"] == "second"


@pytest.mark.usefixtures("tenant_context")
def test_rows_cascade_with_their_credential(db_session: Session) -> None:
    """Verifies report rows die with the credential, not as orphans."""
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    upsert_completed_capability_report(
        db_session,
        credential_id=credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(credential_id),
    )

    # Under test.
    db_session.delete(cc_pair)
    credential = db_session.get(Credential, credential_id)
    assert credential is not None, "The cc-pair helper persists its credential."
    db_session.delete(credential)
    # The FK cascade fires at statement execution; no commit needed, so the
    # deletions roll back with the rest of the test's rows.
    db_session.flush()

    # Postcondition.
    assert get_capability_report_row(db_session, credential_id, None) is None
