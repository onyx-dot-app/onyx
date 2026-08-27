"""Integration tests for the read-only credential capability report endpoints.

``INTEGRATION_TESTS_MODE`` disables the blocking-validation recorder hooks, so
these tests seed rows by invoking the recorder directly, then read them back
through the API the way the frontend will.
"""

from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.models import (
    CapabilityCheckStatus,
    CapabilityVerdict,
)
from onyx.connectors.capability_checks.recorder import (
    record_blocking_validation_outcome,
)
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.test_models import DATestUser

_CONNECTOR_CONFIG: dict[str, Any] = {"channels": ["general"]}

_REPORTS_FOR_SOURCE_URL = f"{API_SERVER_URL}/manage/admin/credential/capability-reports"


def _report_url(credential_id: int) -> str:
    return f"{API_SERVER_URL}/manage/admin/credential/{credential_id}/capability-report"


def _seed_report_row(
    credential_id: int, connector_id: int, source: DocumentSource
) -> None:
    """
    Writes one connector-scoped row the way the production blocking paths do.
    """
    record_blocking_validation_outcome(
        credential_id=credential_id,
        connector_id=connector_id,
        source=source,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        error=None,
        perm_sync_validated=False,
        connector_specific_config=_CONNECTOR_CONFIG,
    )


def test_connector_scoped_report_round_trips(admin_user: DATestUser) -> None:
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.SLACK, user_performing_action=admin_user
    )
    connector = ConnectorManager.create(
        source=DocumentSource.SLACK,
        connector_specific_config=_CONNECTOR_CONFIG,
        user_performing_action=admin_user,
    )
    _seed_report_row(credential.id, connector.id, DocumentSource.SLACK)

    # Under test.
    response = client.get(
        _report_url(credential.id),
        params={"connector_id": connector.id},
        headers=admin_user.headers,
    )

    # Postcondition.
    response.raise_for_status()
    snapshot = response.json()
    assert snapshot["credential_id"] == credential.id
    assert snapshot["connector_id"] == connector.id
    assert snapshot["source"] == DocumentSource.SLACK.value
    assert snapshot["trigger"] == CapabilityCheckTrigger.CC_PAIR_VALIDATION.value
    assert snapshot["run_status"] == CapabilityReportRunStatus.COMPLETED.value
    assert snapshot["connector_config_hash"] is not None
    report = snapshot["report"]
    assert report["credential_id"] == credential.id
    indexing_verdict = report["verdicts"][CredentialCapability.INDEXING.value]
    assert indexing_verdict == CapabilityVerdict.PASSED.value
    (settings_result,) = [
        result
        for result in report["check_results"]
        if result["check_id"] == "slack_connector_settings"
    ]
    assert settings_result["is_fallback"] is True
    assert settings_result["status"] == CapabilityCheckStatus.PASSED.value


def test_scopes_without_rows_return_null(admin_user: DATestUser) -> None:
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.SLACK, user_performing_action=admin_user
    )

    # Under test and postcondition.
    # The recorder only writes connector-scoped rows, so both the credential
    # scope and an unwritten connector scope read back as null rather than an
    # error.
    for params in ({}, {"connector_id": 999_999_999}):
        response = client.get(
            _report_url(credential.id), params=params, headers=admin_user.headers
        )
        response.raise_for_status()
        assert response.json() is None


def test_unknown_credential_maps_to_credential_not_found(
    admin_user: DATestUser,
) -> None:
    # Under test.
    response = client.get(_report_url(999_999_999), headers=admin_user.headers)

    # Postcondition.
    assert response.status_code == 404
    assert response.json()["error_code"] == "CREDENTIAL_NOT_FOUND"


def test_reports_require_connector_management_permission(
    basic_user: DATestUser,
) -> None:
    # Under test and postcondition.
    for url, params in (
        (_report_url(1), {}),
        (_REPORTS_FOR_SOURCE_URL, {"source": DocumentSource.SLACK.value}),
    ):
        response = client.get(url, params=params, headers=basic_user.headers)
        assert response.status_code == 403
        assert response.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"


def test_list_for_source_returns_visible_rows_newest_first(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    slack_connector = ConnectorManager.create(
        source=DocumentSource.SLACK,
        connector_specific_config=_CONNECTOR_CONFIG,
        user_performing_action=admin_user,
    )
    file_connector = ConnectorManager.create(
        source=DocumentSource.FILE, user_performing_action=admin_user
    )
    older = CredentialManager.create(
        source=DocumentSource.SLACK, user_performing_action=admin_user
    )
    newer = CredentialManager.create(
        source=DocumentSource.SLACK, user_performing_action=admin_user
    )
    other_source = CredentialManager.create(
        source=DocumentSource.FILE, user_performing_action=admin_user
    )
    _seed_report_row(older.id, slack_connector.id, DocumentSource.SLACK)
    _seed_report_row(newer.id, slack_connector.id, DocumentSource.SLACK)
    _seed_report_row(other_source.id, file_connector.id, DocumentSource.FILE)

    # Under test.
    response = client.get(
        _REPORTS_FOR_SOURCE_URL,
        params={"source": DocumentSource.SLACK.value},
        headers=admin_user.headers,
    )

    # Postcondition.
    response.raise_for_status()
    rows = response.json()
    assert all(row["source"] == DocumentSource.SLACK.value for row in rows)
    credential_ids = [row["credential_id"] for row in rows]
    assert other_source.id not in credential_ids
    assert newer.id in credential_ids
    assert older.id in credential_ids
    # Rows from other tests may interleave; only relative order is pinned.
    assert credential_ids.index(newer.id) < credential_ids.index(older.id)
