"""
Unit tests for the Jira Service Management connector.

These tests mock the JIRA client and the JSM Service Desk API so they run
without any external network calls or credentials.
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira import JIRA
from requests import Response

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira.utils import JIRA_SERVER_API_VERSION
from onyx.connectors.jira_service_management.connector import _get_jsm_project_keys
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def jira_base_url() -> str:
    return "https://example.atlassian.net"


@pytest.fixture
def jsm_project_key() -> str:
    return "IT"


@pytest.fixture
def mock_jira_client() -> MagicMock:
    """Minimal mock JIRA client (server/DC — v2 REST API)."""
    mock = MagicMock(spec=JIRA)
    mock.search_issues = MagicMock(return_value=[])
    mock.project = MagicMock()
    mock.projects = MagicMock(return_value=[])
    mock.server_url = "https://example.atlassian.net"
    mock._options = {"rest_api_version": JIRA_SERVER_API_VERSION}
    return mock


@pytest.fixture
def jsm_connector(
    jira_base_url: str,
    jsm_project_key: str,
    mock_jira_client: MagicMock,
) -> Generator[JiraServiceManagementConnector, None, None]:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=jsm_project_key,
        comment_email_blacklist=[],
    )
    # Inject mock credentials / client
    connector._jira_client = mock_jira_client
    # Build inner connector with same mock
    from onyx.connectors.jira.connector import JiraConnector

    inner = JiraConnector(
        jira_base_url=jira_base_url,
        project_key=jsm_project_key,
    )
    inner._jira_client = mock_jira_client
    connector._jira_connector = inner
    yield connector


# ---------------------------------------------------------------------------
# Tests: basic construction
# ---------------------------------------------------------------------------


def test_constructor_sets_fields(jira_base_url: str, jsm_project_key: str) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=jsm_project_key,
    )
    assert connector.jira_base == jira_base_url
    assert connector.project_key == jsm_project_key
    assert connector._jira_client is None
    assert connector._jira_connector is None


def test_constructor_strips_trailing_slash(jsm_project_key: str) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net/",
        project_key=jsm_project_key,
    )
    assert connector.jira_base == "https://example.atlassian.net"


# ---------------------------------------------------------------------------
# Tests: load_credentials
# ---------------------------------------------------------------------------


def test_load_credentials_creates_jira_client(
    jira_base_url: str, jsm_project_key: str
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=jsm_project_key,
    )
    fake_client = MagicMock(spec=JIRA)
    fake_client._options = {"rest_api_version": JIRA_SERVER_API_VERSION}

    with patch(
        "onyx.connectors.jira_service_management.connector.build_jira_client",
        return_value=fake_client,
    ):
        result = connector.load_credentials(
            {
                "jira_user_email": "user@example.com",
                "jira_api_token": "token123",
            }
        )

    assert result is None
    assert connector._jira_client is fake_client
    assert connector._jira_connector is not None
    assert connector._jira_connector._jira_client is fake_client


# ---------------------------------------------------------------------------
# Tests: _connector property raises when not loaded
# ---------------------------------------------------------------------------


def test_connector_property_raises_without_credentials(
    jira_base_url: str, jsm_project_key: str
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=jsm_project_key,
    )
    with pytest.raises(ConnectorMissingCredentialError):
        _ = connector._connector


# ---------------------------------------------------------------------------
# Tests: _get_jsm_project_keys
# ---------------------------------------------------------------------------


def test_get_jsm_project_keys_returns_keys(mock_jira_client: MagicMock) -> None:
    mock_response = MagicMock(spec=Response)
    mock_response.json.return_value = {
        "values": [
            {"id": "1", "projectKey": "IT", "projectName": "IT Service Desk"},
            {"id": "2", "projectKey": "HR", "projectName": "HR Help Desk"},
        ]
    }
    mock_jira_client._session.get.return_value = mock_response

    keys = _get_jsm_project_keys(mock_jira_client)
    assert keys == ["IT", "HR"]


def test_get_jsm_project_keys_returns_empty_on_error(
    mock_jira_client: MagicMock,
) -> None:
    mock_jira_client._session.get.side_effect = Exception("network error")

    keys = _get_jsm_project_keys(mock_jira_client)
    assert keys == []


def test_get_jsm_project_keys_returns_empty_on_empty_response(
    mock_jira_client: MagicMock,
) -> None:
    mock_response = MagicMock(spec=Response)
    mock_response.json.return_value = {"values": []}
    mock_jira_client._session.get.return_value = mock_response

    keys = _get_jsm_project_keys(mock_jira_client)
    assert keys == []


# ---------------------------------------------------------------------------
# Tests: validate_connector_settings
# ---------------------------------------------------------------------------


def test_validate_raises_without_credentials(
    jira_base_url: str, jsm_project_key: str
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=jsm_project_key,
    )
    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()


def test_validate_raises_when_not_a_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_client: MagicMock,
) -> None:
    # Service desk API returns a different project key
    mock_response = MagicMock(spec=Response)
    mock_response.json.return_value = {
        "values": [
            {"id": "1", "projectKey": "HELP", "projectName": "Help Desk"},
        ]
    }
    mock_jira_client._session.get.return_value = mock_response

    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        jsm_connector.validate_connector_settings()


def test_validate_passes_when_project_is_service_desk(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_client: MagicMock,
) -> None:
    # Service desk API returns our project key
    mock_response = MagicMock(spec=Response)
    mock_response.json.return_value = {
        "values": [
            {"id": "1", "projectKey": "IT", "projectName": "IT Service Desk"},
        ]
    }
    mock_jira_client._session.get.return_value = mock_response
    mock_jira_client.project.return_value = MagicMock()

    # Should not raise
    jsm_connector.validate_connector_settings()


def test_validate_passes_when_jsm_api_unavailable(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_client: MagicMock,
) -> None:
    """When the JSM API is unavailable (e.g. Jira Server without JSM),
    validation should still pass (skip JSM-specific check)."""
    mock_jira_client._session.get.side_effect = Exception("service not available")
    mock_jira_client.project.return_value = MagicMock()

    # Should not raise — falls back to Jira connector validation
    jsm_connector.validate_connector_settings()


# ---------------------------------------------------------------------------
# Tests: checkpoint helpers
# ---------------------------------------------------------------------------


def test_build_dummy_checkpoint(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    checkpoint = jsm_connector.build_dummy_checkpoint()
    assert isinstance(checkpoint, JiraConnectorCheckpoint)
    assert checkpoint.has_more is True


def test_validate_checkpoint_json(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    checkpoint = JiraConnectorCheckpoint(has_more=False)
    json_str = checkpoint.model_dump_json()
    parsed = jsm_connector.validate_checkpoint_json(json_str)
    assert isinstance(parsed, JiraConnectorCheckpoint)
    assert parsed.has_more is False


# ---------------------------------------------------------------------------
# Tests: delegation to inner connector
# ---------------------------------------------------------------------------


def test_load_from_checkpoint_delegates(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    checkpoint = JiraConnectorCheckpoint(has_more=True)
    jsm_connector._jira_connector.load_from_checkpoint = MagicMock(  # type: ignore[union-attr]
        return_value=JiraConnectorCheckpoint(has_more=False)
    )

    result = jsm_connector.load_from_checkpoint(
        start=0,
        end=1_000_000,
        checkpoint=checkpoint,
    )

    jsm_connector._jira_connector.load_from_checkpoint.assert_called_once()  # type: ignore[union-attr]
    assert isinstance(result, JiraConnectorCheckpoint)


def test_retrieve_all_slim_docs_delegates(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jsm_connector._jira_connector.retrieve_all_slim_docs_perm_sync = MagicMock(  # type: ignore[union-attr]
        return_value=iter([])
    )

    list(jsm_connector.retrieve_all_slim_docs_perm_sync())

    jsm_connector._jira_connector.retrieve_all_slim_docs_perm_sync.assert_called_once()  # type: ignore[union-attr]
