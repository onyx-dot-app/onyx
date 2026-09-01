"""Integration tests for the capability-check trigger endpoint and its task.

MOCK_CONNECTOR is the target source: the runner deliberately exempts no source,
and the mock connector needs no external service on these paths (a config-less
run cannot construct it, and a connector-scoped run fails fast against a closed
local port), so runs complete deterministically without real probes.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import update

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.models import (
    CapabilityCheckStatus,
    CapabilityVerdict,
)
from onyx.connectors.models import InputType
from onyx.db.credential_capability import mark_capability_report_running
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import CredentialCapabilityReportRow
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.test_models import DATestUser

_MOCK_CONFIG: dict[str, Any] = {
    "mock_server_host": "localhost",
    # A closed local port: instantiation fails fast without leaving the host.
    "mock_server_port": 9,
}

_RUN_COMPLETION_TIMEOUT_SECONDS = 60


def _check_url(credential_id: int) -> str:
    return f"{API_SERVER_URL}/manage/admin/credential/{credential_id}/capability-check"


def _report_url(credential_id: int) -> str:
    return f"{API_SERVER_URL}/manage/admin/credential/{credential_id}/capability-report"


def _poll_until_completed(
    credential_id: int, connector_id: int | None, headers: dict[str, str]
) -> dict[str, Any]:
    """Polls the report GET until the run completes; the FE will do the same."""
    params = {} if connector_id is None else {"connector_id": connector_id}
    deadline = time.monotonic() + _RUN_COMPLETION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        response = client.get(
            _report_url(credential_id), params=params, headers=headers
        )
        response.raise_for_status()
        snapshot = response.json()
        if (
            snapshot is not None
            and snapshot["run_status"] == CapabilityReportRunStatus.COMPLETED.value
        ):
            return snapshot
        time.sleep(0.5)
    raise AssertionError(
        f"Capability check run for credential {credential_id} did not complete "
        f"within {_RUN_COMPLETION_TIMEOUT_SECONDS}s."
    )


def test_credential_scoped_run_completes_and_persists_a_report(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )

    # Under test.
    response = client.post(
        _check_url(credential.id), json={}, headers=admin_user.headers
    )

    # Postcondition.
    response.raise_for_status()
    accepted = response.json()
    assert accepted["run_status"] == CapabilityReportRunStatus.RUNNING.value
    assert accepted["trigger"] == CapabilityCheckTrigger.MANUAL.value
    assert accepted["run_started_at"] is not None
    assert accepted["report"] is None
    completed = _poll_until_completed(credential.id, None, admin_user.headers)
    assert completed["connector_config_hash"] is None
    report = completed["report"]
    assert report["connector_id"] is None
    assert report["trigger"] == CapabilityCheckTrigger.MANUAL.value
    assert report["check_results"]
    # Config-less: the mock connector cannot be constructed, so every
    # instance-requiring check skips rather than probing anything.
    assert all(
        result["status"] == CapabilityCheckStatus.SKIPPED.value
        for result in report["check_results"]
    )
    indexing_verdict = report["verdicts"][CredentialCapability.INDEXING.value]
    assert indexing_verdict == CapabilityVerdict.SKIPPED.value


def test_connector_scoped_run_carries_the_config_hash(admin_user: DATestUser) -> None:
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    connector = ConnectorManager.create(
        source=DocumentSource.MOCK_CONNECTOR,
        # The mock connector is checkpoint-based and rejects the manager's
        # LOAD_STATE default at instantiation.
        input_type=InputType.POLL,
        connector_specific_config=_MOCK_CONFIG,
        user_performing_action=admin_user,
    )

    # Under test.
    response = client.post(
        _check_url(credential.id),
        json={"connector_id": connector.id},
        headers=admin_user.headers,
    )

    # Postcondition.
    response.raise_for_status()
    assert response.json()["connector_id"] == connector.id
    completed = _poll_until_completed(credential.id, connector.id, admin_user.headers)
    assert completed["connector_id"] == connector.id
    assert completed["connector_config_hash"] is not None
    assert completed["report"]["connector_id"] == connector.id


def test_second_trigger_while_a_run_is_active_is_a_noop(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    # Seed an active RUNNING mark directly: a real run on the mock source
    # completes too fast to race against.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    with get_session_with_current_tenant() as db_session:
        row = mark_capability_report_running(
            db_session,
            credential_id=credential.id,
            connector_id=None,
            source=DocumentSource.MOCK_CONNECTOR,
            trigger=CapabilityCheckTrigger.MANUAL,
            active_within=timedelta(hours=1),
        )
        assert row is not None
        started_at = row.run_started_at
        db_session.commit()
    assert started_at is not None

    # Under test.
    response = client.post(
        _check_url(credential.id), json={}, headers=admin_user.headers
    )

    # Postcondition.
    response.raise_for_status()
    snapshot = response.json()
    assert snapshot["run_status"] == CapabilityReportRunStatus.RUNNING.value
    assert datetime.fromisoformat(snapshot["run_started_at"]) == started_at


def test_stale_running_mark_is_replaced_and_the_run_proceeds(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    # An hours-old RUNNING mark: a crashed or expired run.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    stale_started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    with get_session_with_current_tenant() as db_session:
        row = mark_capability_report_running(
            db_session,
            credential_id=credential.id,
            connector_id=None,
            source=DocumentSource.MOCK_CONNECTOR,
            trigger=CapabilityCheckTrigger.MANUAL,
            active_within=timedelta(hours=1),
        )
        assert row is not None
        db_session.execute(
            update(CredentialCapabilityReportRow)
            .where(CredentialCapabilityReportRow.id == row.id)
            .values(run_started_at=stale_started_at)
        )
        db_session.commit()

    # Under test.
    response = client.post(
        _check_url(credential.id), json={}, headers=admin_user.headers
    )

    # Postcondition.
    response.raise_for_status()
    snapshot = response.json()
    assert datetime.fromisoformat(snapshot["run_started_at"]) > stale_started_at
    _poll_until_completed(credential.id, None, admin_user.headers)


def test_config_without_connector_id_is_invalid_input(admin_user: DATestUser) -> None:
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )

    # Under test.
    response = client.post(
        _check_url(credential.id),
        json={"connector_specific_config": {"mock_server_host": "localhost"}},
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


def test_connector_source_mismatch_is_invalid_input(admin_user: DATestUser) -> None:
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    file_connector = ConnectorManager.create(
        source=DocumentSource.FILE, user_performing_action=admin_user
    )

    # Under test.
    response = client.post(
        _check_url(credential.id),
        json={"connector_id": file_connector.id},
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


def test_unknown_credential_maps_to_credential_not_found(
    admin_user: DATestUser,
) -> None:
    # Under test.
    response = client.post(_check_url(999_999_999), json={}, headers=admin_user.headers)

    # Postcondition.
    assert response.status_code == 404
    assert response.json()["error_code"] == "CREDENTIAL_NOT_FOUND"


def test_unknown_connector_maps_to_connector_not_found(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )

    # Under test.
    response = client.post(
        _check_url(credential.id),
        json={"connector_id": 999_999_999},
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 404
    assert response.json()["error_code"] == "CONNECTOR_NOT_FOUND"


def test_trigger_requires_connector_management_permission(
    basic_user: DATestUser,
) -> None:
    # Under test and postcondition.
    response = client.post(_check_url(1), json={}, headers=basic_user.headers)
    assert response.status_code == 403
    assert response.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"
