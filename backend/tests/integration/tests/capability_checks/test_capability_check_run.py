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

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import (
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryTask,
)
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.models import CapabilityVerdict
from onyx.connectors.models import InputType
from onyx.db.credential_capability import mark_capability_report_running
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import CredentialCapabilityReportRow
from shared_configs.contextvars import get_current_tenant_id
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


def _poll_until_run_status(
    credential_id: int,
    connector_id: int | None,
    headers: dict[str, str],
    run_status: CapabilityReportRunStatus,
) -> dict[str, Any]:
    """Polls the report GET until the run reaches ``run_status``, FE-style."""
    params = {} if connector_id is None else {"connector_id": connector_id}
    deadline = time.monotonic() + _RUN_COMPLETION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        response = client.get(
            _report_url(credential_id), params=params, headers=headers
        )
        response.raise_for_status()
        snapshot = response.json()
        if snapshot is not None and snapshot["run_status"] == run_status.value:
            return snapshot
        time.sleep(0.5)
    raise AssertionError(
        f"Capability check run for credential {credential_id} did not reach "
        f"{run_status.value} within {_RUN_COMPLETION_TIMEOUT_SECONDS}s."
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
    completed = _poll_until_run_status(
        credential.id, None, admin_user.headers, CapabilityReportRunStatus.COMPLETED
    )
    assert completed["connector_config_hash"] is None
    report = completed["report"]
    assert report["connector_id"] is None
    assert report["trigger"] == CapabilityCheckTrigger.MANUAL.value
    # The mock connector has no settings probe, so the run holds no check.
    assert report["check_results"] == []
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
    completed = _poll_until_run_status(
        credential.id,
        connector.id,
        admin_user.headers,
        CapabilityReportRunStatus.COMPLETED,
    )
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
            lease=timedelta(hours=1),
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


def _seed_running_mark(
    credential_id: int, *, started_at: datetime, deadline_at: datetime
) -> None:
    with get_session_with_current_tenant() as db_session:
        row = mark_capability_report_running(
            db_session,
            credential_id=credential_id,
            connector_id=None,
            source=DocumentSource.MOCK_CONNECTOR,
            trigger=CapabilityCheckTrigger.MANUAL,
            lease=timedelta(hours=1),
            active_within=None,
        )
        assert row is not None
        db_session.execute(
            update(CredentialCapabilityReportRow)
            .where(CredentialCapabilityReportRow.id == row.id)
            .values(run_started_at=started_at, run_deadline_at=deadline_at)
        )
        db_session.commit()


def test_run_past_its_deadline_reads_failed_and_rerun_replaces_it(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    # A fresh mark whose deadline passed: the worker died before renewing it,
    # and the sweep has not retired it yet.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    _seed_running_mark(
        credential.id,
        started_at=started_at,
        deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    # Under test and postcondition (the read shows the dead run).
    read = client.get(_report_url(credential.id), headers=admin_user.headers)
    read.raise_for_status()
    assert read.json()["run_status"] == CapabilityReportRunStatus.FAILED_TO_RUN.value
    assert read.json()["progress"] is None

    # Under test.
    response = client.post(
        _check_url(credential.id), json={}, headers=admin_user.headers
    )

    # Postcondition.
    response.raise_for_status()
    snapshot = response.json()
    assert snapshot["run_status"] == CapabilityReportRunStatus.RUNNING.value
    assert datetime.fromisoformat(snapshot["run_started_at"]) > started_at
    _poll_until_run_status(
        credential.id, None, admin_user.headers, CapabilityReportRunStatus.COMPLETED
    )


def test_rerun_replaces_a_live_run_started_minutes_ago(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    # A mark within its deadline but started long before the Re-run click.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    _seed_running_mark(
        credential.id,
        started_at=started_at,
        deadline_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    # Under test.
    response = client.post(
        _check_url(credential.id), json={}, headers=admin_user.headers
    )

    # Postcondition.
    response.raise_for_status()
    assert datetime.fromisoformat(response.json()["run_started_at"]) > started_at
    _poll_until_run_status(
        credential.id, None, admin_user.headers, CapabilityReportRunStatus.COMPLETED
    )


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


def test_sweep_retires_a_dead_run_and_retrigger_recovers(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    # A completed report, then a RUNNING mark past its deadline: a run that
    # died without a trace.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    response = client.post(
        _check_url(credential.id), json={}, headers=admin_user.headers
    )
    response.raise_for_status()
    completed = _poll_until_run_status(
        credential.id, None, admin_user.headers, CapabilityReportRunStatus.COMPLETED
    )
    assert completed["report"] is not None
    with get_session_with_current_tenant() as db_session:
        row = mark_capability_report_running(
            db_session,
            credential_id=credential.id,
            connector_id=None,
            source=DocumentSource.MOCK_CONNECTOR,
            trigger=CapabilityCheckTrigger.MANUAL,
            lease=timedelta(hours=1),
            active_within=timedelta(hours=1),
        )
        assert row is not None
        db_session.execute(
            update(CredentialCapabilityReportRow)
            .where(CredentialCapabilityReportRow.id == row.id)
            .values(run_deadline_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        db_session.commit()

    # Under test.
    # The sweep the beat schedule fires every ten minutes.
    client_app.send_task(
        OnyxCeleryTask.CHECK_FOR_STALE_CAPABILITY_RUNS,
        kwargs={"tenant_id": get_current_tenant_id()},
        priority=OnyxCeleryPriority.LOW,
        expires=300,
    )

    # Postcondition.
    # The dead run surfaces as FAILED_TO_RUN with the previous report preserved
    # unchanged, and a re-trigger recovers the scope. Nothing runs between the
    # two reads (the dead mark was crafted directly, with no task behind it), so
    # equality is deterministic.
    retired = _poll_until_run_status(
        credential.id,
        None,
        admin_user.headers,
        CapabilityReportRunStatus.FAILED_TO_RUN,
    )
    assert retired["report"] == completed["report"]
    response = client.post(
        _check_url(credential.id), json={}, headers=admin_user.headers
    )
    response.raise_for_status()
    assert response.json()["run_status"] == CapabilityReportRunStatus.RUNNING.value
    _poll_until_run_status(
        credential.id, None, admin_user.headers, CapabilityReportRunStatus.COMPLETED
    )


def test_config_override_is_validated(admin_user: DATestUser) -> None:
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    connector = ConnectorManager.create(
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config=_MOCK_CONFIG,
        user_performing_action=admin_user,
    )

    # Under test.
    response = client.post(
        _check_url(credential.id),
        json={
            "connector_id": connector.id,
            "connector_specific_config": {"mock_server_host": "localhost"},
        },
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 400
    assert "mock_server_port" in response.text
