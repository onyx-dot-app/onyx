import os
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import JiraServiceManagementCheckpoint
from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_from_connector


def _make_connector() -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ.get("JIRA_BASE_URL", "https://example.atlassian.net"),
        project_key=os.environ.get("JIRA_PROJECT_KEY", "IT"),
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ.get("JIRA_USER_EMAIL", "test@example.com"),
            "jira_api_token": os.environ.get("JIRA_API_TOKEN", "fake-token"),
        }
    )
    return connector


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    return _make_connector()


def test_jsm_connector_initialization(jsm_connector: JiraServiceManagementConnector) -> None:
    """Basic smoke test for connector initialization."""
    assert jsm_connector.jira_base == "https://danswerai.atlassian.net"
    assert jsm_connector.project_key == "IT"


def test_jsm_connector_build_dummy_checkpoint(jsm_connector: JiraServiceManagementConnector) -> None:
    """Check that dummy checkpoint is created correctly."""
    checkpoint = jsm_connector.build_dummy_checkpoint()
    assert checkpoint.has_more is True
    assert checkpoint.start_at == 0


def test_jsm_connector_validate_checkpoint_json(jsm_connector: JiraServiceManagementConnector) -> None:
    """Check that checkpoint JSON validation works."""
    checkpoint_json = '{"start_at": 50, "has_more": true}'
    checkpoint = jsm_connector.validate_checkpoint_json(checkpoint_json)
    assert checkpoint.start_at == 50
    assert checkpoint.has_more is True


@patch("onyx.connectors.jira_service_management.connector.JiraServiceManagementConnector.jira_client")
def test_jsm_connector_load_from_checkpoint_mock(
    mock_jira_client, jsm_connector: JiraServiceManagementConnector
) -> None:
    """Mock test for load_from_checkpoint with empty result set."""
    mock_jira_client.search_issues.return_value = []

    checkpoint = jsm_connector.build_dummy_checkpoint()
    # load_from_checkpoint is a generator — its terminal state is a `return <checkpoint>`
    # which becomes StopIteration.value. Drain manually to capture it.
    gen = jsm_connector.load_from_checkpoint(start=0, end=100, checkpoint=checkpoint)
    yielded = []
    try:
        while True:
            yielded.append(next(gen))
    except StopIteration as exc:
        final_checkpoint = exc.value

    assert len(yielded) == 0
    assert isinstance(final_checkpoint, JiraServiceManagementCheckpoint)
    assert final_checkpoint.has_more is False


def test_jsm_connector_source_enum() -> None:
    """Ensure JIRA_SERVICE_MANAGEMENT is in DocumentSource."""
    assert hasattr(DocumentSource, "JIRA_SERVICE_MANAGEMENT")
    assert DocumentSource.JIRA_SERVICE_MANAGEMENT == "jira_service_management"
