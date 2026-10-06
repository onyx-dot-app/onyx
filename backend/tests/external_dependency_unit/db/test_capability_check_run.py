"""Accessor tests for the append-only capability-check run history.

Runs against real Postgres: the RUNNING guards on the terminal writers, the
JSONB input matching, and the server-side timestamps are statement-level
semantics that mocks cannot exercise. Nothing here commits (the accessors leave
the transaction to the caller), so every test's rows roll back when its session
closes.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
)
from onyx.db.capability_check_run import (
    complete_capability_check_run,
    create_capability_check_run,
    delete_capability_check_runs_older_than,
    fail_capability_check_run,
    find_recent_capability_check_run,
    get_capability_check_run,
    get_capability_check_runs_for_session,
    get_latest_capability_check_run_for_scope,
    record_capability_check_run_progress,
)
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import Credential
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


def _result(check_id: str) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id=check_id,
        display_name="Test check",
        required=True,
        status=CapabilityCheckStatus.PASSED,
    )


@pytest.mark.usefixtures("tenant_context")
def test_create_appends_a_running_row_with_its_inputs(db_session: Session) -> None:
    """Verifies the insert records the attempt's inputs and lifecycle start."""
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    session_id = uuid4()

    # Under test.
    row = create_capability_check_run(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        creation_session_id=session_id,
        check_ids_requested=["a_check", "b_check"],
        connector_config={"channels": ["general"]},
        connector_config_hash="abc123",
    )

    # Postcondition.
    assert row.run_status == CapabilityReportRunStatus.RUNNING
    assert row.run_started_at is not None
    assert row.run_finished_at is None
    assert row.results is None
    assert row.check_ids_requested == ["a_check", "b_check"]
    assert row.connector_config == {"channels": ["general"]}
    fetched = get_capability_check_run(db_session, row.run_id)
    assert fetched is not None
    assert fetched.run_id == row.run_id
    assert fetched.creation_session_id == session_id


@pytest.mark.usefixtures("tenant_context")
def test_attempts_append_instead_of_replacing(db_session: Session) -> None:
    """
    Verifies the core history property: a second run for the same scope is a new
    row, both remain readable, and latest-by-scope returns the newer one.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id

    # Under test.
    first = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )
    completed_first = complete_capability_check_run(
        db_session, run_id=first.run_id, results=[_result("first")]
    )
    second = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )

    # Postcondition.
    assert completed_first is not None
    assert second.run_id != first.run_id
    assert get_capability_check_run(db_session, first.run_id) is not None
    assert get_capability_check_run(db_session, second.run_id) is not None
    latest = get_latest_capability_check_run_for_scope(db_session, credential_id, None)
    assert latest is not None
    assert latest.run_id == second.run_id


@pytest.mark.usefixtures("tenant_context")
def test_scopes_are_distinct_for_latest_lookup(db_session: Session) -> None:
    """
    Verifies the credential-time scope (``connector_id`` NULL) and a
    connector-scoped run resolve independently.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    connector_id = cc_pair.connector_id

    # Under test.
    credential_scope = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CREDENTIAL_CREATED,
    )
    connector_scope = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        connector_id=connector_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        connector_config={"channels": ["general"]},
        connector_config_hash="abc123",
    )

    # Postcondition.
    latest_credential_scope = get_latest_capability_check_run_for_scope(
        db_session, credential_id, None
    )
    latest_connector_scope = get_latest_capability_check_run_for_scope(
        db_session, credential_id, connector_id
    )
    assert latest_credential_scope is not None
    assert latest_credential_scope.run_id == credential_scope.run_id
    assert latest_connector_scope is not None
    assert latest_connector_scope.run_id == connector_scope.run_id


@pytest.mark.usefixtures("tenant_context")
def test_progress_streams_only_onto_a_running_row(db_session: Session) -> None:
    """
    Verifies the progress writer replaces the list wholesale while the run is
    RUNNING and is discarded once the row is terminal.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    row = create_capability_check_run(
        db_session,
        credential_id=cc_pair.credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )

    # Under test.
    first = record_capability_check_run_progress(
        db_session, run_id=row.run_id, results=[_result("first")]
    )
    second = record_capability_check_run_progress(
        db_session, run_id=row.run_id, results=[_result("first"), _result("second")]
    )

    # Postcondition.
    assert first is True
    assert second is True
    db_session.expire_all()
    fetched = get_capability_check_run(db_session, row.run_id)
    assert fetched is not None
    assert fetched.results is not None
    assert [result["check_id"] for result in fetched.results] == ["first", "second"]

    # Under test and postcondition (a terminal row discards late progress).
    completed = complete_capability_check_run(
        db_session, run_id=row.run_id, results=[_result("final")]
    )
    assert completed is not None
    late = record_capability_check_run_progress(
        db_session, run_id=row.run_id, results=[_result("straggler")]
    )
    assert late is False
    db_session.expire_all()
    fetched = get_capability_check_run(db_session, row.run_id)
    assert fetched is not None
    assert fetched.results is not None
    assert [result["check_id"] for result in fetched.results] == ["final"]


@pytest.mark.usefixtures("tenant_context")
def test_terminal_write_lands_at_most_once(db_session: Session) -> None:
    """
    Verifies finished rows are immutable history: the first terminal write wins
    and every later terminal write returns None without rewriting the row.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    row = create_capability_check_run(
        db_session,
        credential_id=cc_pair.credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )

    # Under test.
    completed = complete_capability_check_run(
        db_session, run_id=row.run_id, results=[_result("final")]
    )
    completed_again = complete_capability_check_run(
        db_session, run_id=row.run_id, results=[_result("rewrite")]
    )
    failed_late = fail_capability_check_run(db_session, run_id=row.run_id)

    # Postcondition.
    assert completed is not None
    assert completed.run_status == CapabilityReportRunStatus.COMPLETED
    assert completed.run_finished_at is not None
    assert completed_again is None
    assert failed_late is None
    db_session.expire_all()
    fetched = get_capability_check_run(db_session, row.run_id)
    assert fetched is not None
    assert fetched.run_status == CapabilityReportRunStatus.COMPLETED
    assert fetched.results is not None
    assert [result["check_id"] for result in fetched.results] == ["final"]


@pytest.mark.usefixtures("tenant_context")
def test_fail_keeps_streamed_partial_results(db_session: Session) -> None:
    """Verifies a dying run's recorded progress survives its FAILED_TO_RUN."""
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    row = create_capability_check_run(
        db_session,
        credential_id=cc_pair.credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )
    record_capability_check_run_progress(
        db_session, run_id=row.run_id, results=[_result("died_after_this")]
    )

    # Under test.
    failed = fail_capability_check_run(db_session, run_id=row.run_id)

    # Postcondition.
    assert failed is not None
    assert failed.run_status == CapabilityReportRunStatus.FAILED_TO_RUN
    assert failed.run_finished_at is not None
    assert failed.results is not None
    assert [result["check_id"] for result in failed.results] == ["died_after_this"]


@pytest.mark.usefixtures("tenant_context")
def test_session_listing_returns_only_that_session_newest_first(
    db_session: Session,
) -> None:
    """Verifies the sticky-card read: one session's runs, newest first."""
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    session_id = uuid4()
    other_session_id = uuid4()
    first = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        creation_session_id=session_id,
    )
    second = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        creation_session_id=session_id,
    )
    create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        creation_session_id=other_session_id,
    )
    create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )
    # Same-transaction inserts share the statement clock only when they execute
    # in one statement; distinct flushes get distinct timestamps. Still, force
    # an unambiguous order for the assertion.
    first.run_started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.flush()

    # Under test.
    runs = get_capability_check_runs_for_session(db_session, session_id)

    # Postcondition.
    assert [run.run_id for run in runs] == [second.run_id, first.run_id]


@pytest.mark.usefixtures("tenant_context")
def test_dedup_lookup_matches_the_full_input_identity(db_session: Session) -> None:
    """
    Verifies the idempotency key: credential, config hash, and check subset must
    all match, and only within the freshness bound.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    standing = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        connector_id=cc_pair.connector_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        check_ids_requested=["a_check", "b_check"],
        connector_config={"channels": ["general"]},
        connector_config_hash="abc123",
    )

    # Under test and postcondition (an identical re-post finds the run).
    found = find_recent_capability_check_run(
        db_session,
        credential_id=credential_id,
        connector_config_hash="abc123",
        check_ids_requested=["a_check", "b_check"],
        within=timedelta(minutes=5),
    )
    assert found is not None
    assert found.run_id == standing.run_id

    # Under test and postcondition (any differing input misses).
    assert (
        find_recent_capability_check_run(
            db_session,
            credential_id=credential_id,
            connector_config_hash="other",
            check_ids_requested=["a_check", "b_check"],
            within=timedelta(minutes=5),
        )
        is None
    )
    assert (
        find_recent_capability_check_run(
            db_session,
            credential_id=credential_id,
            connector_config_hash="abc123",
            check_ids_requested=["a_check"],
            within=timedelta(minutes=5),
        )
        is None
    )
    assert (
        find_recent_capability_check_run(
            db_session,
            credential_id=credential_id,
            connector_config_hash="abc123",
            check_ids_requested=None,
            within=timedelta(minutes=5),
        )
        is None
    )

    # Under test and postcondition (a stale standing run misses).
    standing.run_started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.flush()
    assert (
        find_recent_capability_check_run(
            db_session,
            credential_id=credential_id,
            connector_config_hash="abc123",
            check_ids_requested=["a_check", "b_check"],
            within=timedelta(minutes=5),
        )
        is None
    )


@pytest.mark.usefixtures("tenant_context")
def test_dedup_lookup_matches_configless_runs_and_skips_dead_attempts(
    db_session: Session,
) -> None:
    """
    Verifies NULL inputs match by nullness (a credential-time full run) and that
    a FAILED_TO_RUN attempt never absorbs its own retry.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    standing = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )

    # Under test and postcondition (nullness matches nullness).
    found = find_recent_capability_check_run(
        db_session,
        credential_id=credential_id,
        connector_config_hash=None,
        check_ids_requested=None,
        within=timedelta(minutes=5),
    )
    assert found is not None
    assert found.run_id == standing.run_id

    # Under test and postcondition (a dead attempt stops matching).
    failed = fail_capability_check_run(db_session, run_id=standing.run_id)
    assert failed is not None
    assert (
        find_recent_capability_check_run(
            db_session,
            credential_id=credential_id,
            connector_config_hash=None,
            check_ids_requested=None,
            within=timedelta(minutes=5),
        )
        is None
    )


@pytest.mark.usefixtures("tenant_context")
def test_retention_delete_is_age_based_and_status_blind(db_session: Session) -> None:
    """
    Verifies the sweep deletes everything past the bound (RUNNING corpses
    included) and keeps everything inside it.

    The table ships dark, so no committed rows from other suites can inflate the
    count.
    """
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    old_completed = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )
    complete_capability_check_run(
        db_session, run_id=old_completed.run_id, results=[_result("old")]
    )
    old_running_corpse = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )
    fresh = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
    )
    backdated = datetime.now(timezone.utc) - timedelta(days=90)
    for row in (old_completed, old_running_corpse):
        row.run_started_at = backdated
    db_session.flush()

    # Under test.
    deleted = delete_capability_check_runs_older_than(
        db_session, retain_for=timedelta(days=30)
    )

    # Postcondition.
    assert deleted == 2
    db_session.expire_all()
    assert get_capability_check_run(db_session, old_completed.run_id) is None
    assert get_capability_check_run(db_session, old_running_corpse.run_id) is None
    assert get_capability_check_run(db_session, fresh.run_id) is not None


@pytest.mark.usefixtures("tenant_context")
def test_rows_cascade_with_their_credential(db_session: Session) -> None:
    """Verifies run rows die with the credential, not as orphans."""
    # Precondition.
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
    credential_id = cc_pair.credential_id
    row = create_capability_check_run(
        db_session,
        credential_id=credential_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
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
    assert get_capability_check_run(db_session, row.run_id) is None
