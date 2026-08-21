"""Recorder tests: blocking validation outcomes become persisted reports.

Runs the two hook sites (``validate_ccpair_for_user`` and docfetching's
``_get_connector_runner``) against real Postgres with the connector
instantiation mocked: the subject is the recording side effect and its
guarantees (fallback shape, no-clobber, never breaking validation), not the
per-connector validation logic.
"""

from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing import run_docfetching
from onyx.configs.constants import DocumentSource
from onyx.connectors import factory
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks import recorder
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CredentialCapabilityReport,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.factory import validate_ccpair_for_user
from onyx.connectors.interfaces import BaseConnector
from onyx.db.credential_capability import (
    get_capability_report_row,
    upsert_completed_capability_report,
)
from onyx.db.enums import (
    AccessType,
    CapabilityCheckTrigger,
    CapabilityReportRunStatus,
    IndexingStatus,
)
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def blocking_validation(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[ConnectorCredentialPair, MagicMock], None, None]:
    """A Slack cc-pair plus a mocked connector behind the blocking validation.

    Committed on purpose: the recorder reads and writes through its own session,
    which cannot see this session's uncommitted rows. Teardown removes the pair;
    report rows cascade with the credential.
    """
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    connector_mock = MagicMock(spec=BaseConnector)
    monkeypatch.setattr(
        factory, "instantiate_connector", MagicMock(return_value=connector_mock)
    )
    # The early return would skip validation (and thus recording) entirely.
    monkeypatch.setattr(factory, "INTEGRATION_TESTS_MODE", False)
    yield cc_pair, connector_mock
    cleanup_cc_pair(db_session, cc_pair)


@pytest.mark.usefixtures("tenant_context")
def test_success_records_a_fallback_shaped_passed_report(
    db_session: Session,
    blocking_validation: tuple[ConnectorCredentialPair, MagicMock],
) -> None:
    # Precondition.
    cc_pair, _ = blocking_validation

    # Under test.
    result = validate_ccpair_for_user(
        cc_pair.connector_id, cc_pair.credential_id, AccessType.PUBLIC, db_session
    )

    # Postcondition.
    assert result is True
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.trigger == CapabilityCheckTrigger.CC_PAIR_VALIDATION
    assert row.run_status == CapabilityReportRunStatus.COMPLETED
    assert row.connector_config_hash is not None
    assert row.report is not None
    assert row.report["verdicts"]["indexing"] == "passed"
    (check_result,) = row.report["check_results"]
    assert check_result["check_id"] == "slack_connector_settings"
    assert check_result["is_fallback"] is True
    assert check_result["status"] == "passed"


@pytest.mark.usefixtures("tenant_context")
def test_caller_supplied_trigger_lands_on_the_report_row(
    db_session: Session,
    blocking_validation: tuple[ConnectorCredentialPair, MagicMock],
) -> None:
    """
    Verifies non-creation callers (the perm-sync task) can relabel their
    recordings.
    """
    # Precondition.
    cc_pair, _ = blocking_validation

    # Under test.
    validate_ccpair_for_user(
        cc_pair.connector_id,
        cc_pair.credential_id,
        AccessType.PUBLIC,
        db_session,
        trigger=CapabilityCheckTrigger.PERM_SYNC_ATTEMPT,
    )

    # Postcondition.
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.trigger == CapabilityCheckTrigger.PERM_SYNC_ATTEMPT


@pytest.mark.usefixtures("tenant_context")
def test_validation_failure_records_failed_and_still_raises(
    db_session: Session,
    blocking_validation: tuple[ConnectorCredentialPair, MagicMock],
) -> None:
    # Precondition.
    cc_pair, connector_mock = blocking_validation
    connector_mock.validate_connector_settings.side_effect = ConnectorValidationError(
        "missing scope"
    )

    # Under test.
    with pytest.raises(ConnectorValidationError, match="missing scope"):
        validate_ccpair_for_user(
            cc_pair.connector_id, cc_pair.credential_id, AccessType.PUBLIC, db_session
        )

    # Postcondition.
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.report is not None
    assert row.report["verdicts"]["indexing"] == "failed"
    (check_result,) = row.report["check_results"]
    assert check_result["status"] == "failed"
    assert check_result["message"] == "missing scope"
    assert check_result["error_type"] == "ConnectorValidationError"


@pytest.mark.usefixtures("tenant_context")
def test_unexpected_failure_records_indeterminate(
    db_session: Session,
    blocking_validation: tuple[ConnectorCredentialPair, MagicMock],
) -> None:
    """
    Verifies the exception contract carries over: a transient failure is never
    recorded as proof of a broken credential.
    """
    # Precondition.
    cc_pair, connector_mock = blocking_validation
    connector_mock.validate_connector_settings.side_effect = UnexpectedValidationError(
        "source hiccup"
    )

    # Under test.
    with pytest.raises(UnexpectedValidationError):
        validate_ccpair_for_user(
            cc_pair.connector_id, cc_pair.credential_id, AccessType.PUBLIC, db_session
        )

    # Postcondition.
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.report is not None
    assert row.report["verdicts"]["indexing"] == "indeterminate"


@pytest.mark.usefixtures("tenant_context")
def test_wrapped_creation_failure_records_the_original_exception(
    db_session: Session,
    blocking_validation: tuple[ConnectorCredentialPair, MagicMock],
) -> None:
    """
    Verifies the creation gate raises its wrapper while the report keeps the
    original exception: an unexpected error is INDETERMINATE, never FAILED.
    """
    # Precondition.
    cc_pair, connector_mock = blocking_validation
    connector_mock.validate_connector_settings.side_effect = RuntimeError("boom")

    # Under test.
    with pytest.raises(ConnectorValidationError, match="boom"):
        validate_ccpair_for_user(
            cc_pair.connector_id, cc_pair.credential_id, AccessType.PUBLIC, db_session
        )

    # Postcondition.
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.report is not None
    assert row.report["verdicts"]["indexing"] == "indeterminate"
    (check_result,) = row.report["check_results"]
    assert check_result["error_type"] == "RuntimeError"


@pytest.mark.usefixtures("tenant_context", "enable_ee")
def test_sync_success_mirrors_the_outcome_onto_perm_sync(
    db_session: Session,
    blocking_validation: tuple[ConnectorCredentialPair, MagicMock],
) -> None:
    """
    Verifies a SYNC-access success also claims the applicable perm-sync
    capability (EE resolution on: applicability comes from the EE hook).
    """
    # Precondition.
    cc_pair, _ = blocking_validation

    # Under test.
    validate_ccpair_for_user(
        cc_pair.connector_id, cc_pair.credential_id, AccessType.SYNC, db_session
    )

    # Postcondition.
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.report is not None
    check_ids = {result["check_id"] for result in row.report["check_results"]}
    assert check_ids == {"slack_connector_settings", "slack_perm_sync"}
    assert row.report["verdicts"]["doc_permission_sync"] == "passed"


@pytest.mark.usefixtures("tenant_context")
def test_no_clobber_of_a_granular_report(
    db_session: Session,
    blocking_validation: tuple[ConnectorCredentialPair, MagicMock],
) -> None:
    """
    Verifies the coarse recorder never overwrites a named-checks report.
    """
    # Precondition.
    cc_pair, _ = blocking_validation
    granular = CredentialCapabilityReport(
        credential_id=cc_pair.credential_id,
        source=DocumentSource.SLACK,
        connector_id=cc_pair.connector_id,
        checked_at=datetime.now(timezone.utc),
        trigger=CapabilityCheckTrigger.MANUAL,
        verdicts={CredentialCapability.INDEXING: CapabilityVerdict.FAILED},
        check_results=[
            CapabilityCheckResult(
                capability=CredentialCapability.INDEXING,
                check_id="slack_token_auth",
                display_name="Bot token is valid",
                required=True,
                status=CapabilityCheckStatus.FAILED,
                is_fallback=False,
            )
        ],
    )
    upsert_completed_capability_report(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=granular,
        # Connector-scoped writes must carry the config hash they ran with.
        connector_config_hash="seeded-hash",
    )
    # Commit the seed: the recorder's own session cannot see it uncommitted, and
    # its upsert would block on this transaction's index lock.
    db_session.commit()

    # Under test.
    validate_ccpair_for_user(
        cc_pair.connector_id, cc_pair.credential_id, AccessType.PUBLIC, db_session
    )

    # Postcondition.
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.trigger == CapabilityCheckTrigger.MANUAL
    assert row.report is not None
    (check_result,) = row.report["check_results"]
    assert check_result["check_id"] == "slack_token_auth"


@pytest.mark.usefixtures("tenant_context")
def test_recorder_failure_never_breaks_validation(
    db_session: Session,
    blocking_validation: tuple[ConnectorCredentialPair, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Precondition.
    cc_pair, _ = blocking_validation
    monkeypatch.setattr(
        recorder,
        "upsert_completed_capability_report_unless_granular",
        MagicMock(side_effect=RuntimeError("db down")),
    )

    # Under test and postcondition.
    assert (
        validate_ccpair_for_user(
            cc_pair.connector_id, cc_pair.credential_id, AccessType.PUBLIC, db_session
        )
        is True
    )


@pytest.fixture
def docfetching_validation(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[IndexAttempt, MagicMock], None, None]:
    """A committed Slack index attempt with docfetching's instantiation mocked.

    Mirrors ``blocking_validation`` for the ``_get_connector_runner`` hook.
    """
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=None,
        from_beginning=False,
        status=IndexingStatus.NOT_STARTED,
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    instantiate_mock = MagicMock()
    monkeypatch.setattr(run_docfetching, "instantiate_connector", instantiate_mock)
    monkeypatch.setattr(run_docfetching, "INTEGRATION_TESTS_MODE", False)
    yield attempt, instantiate_mock
    # The attempt does not cascade from the pair; its stage-metric rows cascade
    # from the attempt.
    db_session.query(IndexAttempt).filter(IndexAttempt.id == attempt.id).delete(
        synchronize_session="fetch"
    )
    db_session.commit()
    cleanup_cc_pair(db_session, cc_pair)


@pytest.mark.usefixtures("tenant_context")
def test_docfetching_failure_records_through_the_indexing_attempt_hook(
    db_session: Session,
    docfetching_validation: tuple[IndexAttempt, MagicMock],
) -> None:
    """
    Verifies the second hook site: a validation failure at docfetching start
    lands as an INDEXING_ATTEMPT-triggered report and still propagates.
    """
    # Precondition.
    attempt, instantiate_mock = docfetching_validation
    instantiate_mock.side_effect = RuntimeError("source down")
    cc_pair = attempt.connector_credential_pair

    # Under test.
    with pytest.raises(RuntimeError, match="source down"):
        run_docfetching._get_connector_runner(
            db_session=db_session,
            attempt=attempt,
            batch_size=16,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            include_permissions=False,
            # True skips the pause-the-pair branch, which is not under test.
            leave_connector_active=True,
        )

    # Postcondition.
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.trigger == CapabilityCheckTrigger.INDEXING_ATTEMPT
    assert row.report is not None
    assert row.report["verdicts"]["indexing"] == "indeterminate"
    (check_result,) = row.report["check_results"]
    assert check_result["is_fallback"] is True
    assert check_result["error_type"] == "RuntimeError"
