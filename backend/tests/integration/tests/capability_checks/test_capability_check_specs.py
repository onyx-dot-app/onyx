"""Integration tests for the static capability-check listing endpoint.

The listing is the registry, so it needs no credential, no connector, and no
stored row. It is what a client renders before the first run and while one is
in flight, so its rows must line up with the result rows a run writes.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.db.enums import CapabilityReportRunStatus
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.capability_checks.test_capability_check_run import (
    _poll_until_run_status,
)

_SPECS_URL = f"{API_SERVER_URL}/manage/admin/capability-checks"


def _check_url(credential_id: int) -> str:
    return f"{API_SERVER_URL}/manage/admin/credential/{credential_id}/capability-check"


def test_unmigrated_source_lists_the_settings_fallback(admin_user: DATestUser) -> None:
    # Under test.
    response = client.get(
        _SPECS_URL,
        params={"source": DocumentSource.MOCK_CONNECTOR.value},
        headers=admin_user.headers,
    )

    # Postcondition.
    response.raise_for_status()
    specs = response.json()
    (settings_spec,) = [
        spec
        for spec in specs
        if spec["capability"] == CredentialCapability.INDEXING.value
    ]
    assert settings_spec["check_id"] == "mock_connector_connector_settings"
    assert settings_spec["is_fallback"] is True
    assert settings_spec["required"] is True
    assert settings_spec["requires_connector_instance"] is True


def test_migrated_source_lists_its_named_checks_in_run_order(
    admin_user: DATestUser,
) -> None:
    # Under test.
    response = client.get(
        _SPECS_URL,
        params={"source": DocumentSource.SLACK.value},
        headers=admin_user.headers,
    )

    # Postcondition.
    response.raise_for_status()
    specs = response.json()
    check_ids = [spec["check_id"] for spec in specs]
    assert "slack_token_auth" in check_ids
    assert "slack_connector_settings" not in check_ids
    assert all(spec["is_fallback"] is False for spec in specs)
    # Token auth is the first probe: nothing else is meaningful without it.
    assert check_ids[0] == "slack_token_auth"
    (configured_channels_spec,) = [
        spec
        for spec in specs
        if spec["check_id"] == "slack_configured_channels_visible"
    ]
    assert configured_channels_spec["requires_connector_config"] is True


def test_specs_line_up_with_a_completed_report(admin_user: DATestUser) -> None:
    """The listing and a run's result rows pair one-to-one on (capability, id)."""
    # Precondition.
    credential = CredentialManager.create(
        source=DocumentSource.MOCK_CONNECTOR, user_performing_action=admin_user
    )
    response = client.post(
        _check_url(credential.id), json={}, headers=admin_user.headers
    )
    response.raise_for_status()

    # Under test.
    specs_response = client.get(
        _SPECS_URL,
        params={"source": DocumentSource.MOCK_CONNECTOR.value},
        headers=admin_user.headers,
    )

    # Postcondition.
    completed = _poll_until_run_status(
        credential.id, None, admin_user.headers, CapabilityReportRunStatus.COMPLETED
    )
    specs_response.raise_for_status()
    spec_keys = [
        (spec["capability"], spec["check_id"]) for spec in specs_response.json()
    ]
    result_keys = [
        (result["capability"], result["check_id"])
        for result in completed["report"]["check_results"]
    ]
    assert spec_keys == result_keys
    assert completed["in_progress_results"] is None


def test_specs_require_connector_management_permission(
    basic_user: DATestUser,
) -> None:
    # Under test and postcondition.
    response = client.get(
        _SPECS_URL,
        params={"source": DocumentSource.SLACK.value},
        headers=basic_user.headers,
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"
