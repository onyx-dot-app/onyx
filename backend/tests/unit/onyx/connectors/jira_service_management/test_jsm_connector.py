from unittest.mock import MagicMock, patch
import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from tests.unit.onyx.connectors.jira_service_management.conftest import (
    make_mock_jsm_issue,
    MockComment,
    MockUser,
)


def test_jsm_initialization() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://support.example.com",
        project_key="ITSM",
        include_attachments=False,
        include_internal_comments=True,
    )
    assert connector.jira_base == "https://support.example.com"
    assert connector.jira_project == "ITSM"
    assert connector.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert connector.include_attachments is False
    assert connector.include_internal_comments is True


def test_jsm_validation_missing_credentials() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://support.example.com",
        project_key="ITSM",
    )
    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()


def test_jsm_validation_missing_project_key(mock_jira_client: MagicMock) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://support.example.com",
        project_key="",
    )
    connector._jira_client = mock_jira_client
    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()


def test_jsm_validation_success(jsm_connector: JiraServiceManagementConnector) -> None:
    # Should not raise
    jsm_connector.validate_connector_settings()
    jsm_connector.jira_client.project.assert_called_with("ITSM")


def test_jsm_issue_processing_full_metadata(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    issue = make_mock_jsm_issue(
        organizations=["Acme Corp", "Beta LLC"],
    )

    doc = jsm_connector._process_issue(issue)
    assert doc is not None

    # Check basic document properties
    assert doc.id == "https://support.example.com/browse/ITSM-101"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.semantic_identifier == "[ITSM] ITSM-101: VPN Connection Issue"
    assert doc.title == "[ITSM-101] VPN Connection Issue"

    # Check JSM metadata
    assert doc.metadata["customer_request_type"] == "Get IT help"
    assert doc.metadata["organizations"] == ["Acme Corp", "Beta LLC"]
    assert "Time to first response: Met" in doc.metadata["sla_status"]
    assert "Time to resolution: In Progress" in doc.metadata["sla_status"]
    assert doc.metadata["reporter"] == "Alice Requester"
    assert doc.metadata["reporter_email"] == "alice@example.com"
    assert doc.metadata["assignee"] == "Bob Agent"
    assert doc.metadata["assignee_email"] == "bob@example.com"
    assert doc.metadata["project"] == "ITSM"
    assert doc.metadata["project_name"] == "IT Service Desk"

    # Check sections and content
    assert len(doc.sections) == 1
    section_text = doc.sections[0].text
    assert "Request Type: Get IT help" in section_text
    assert "Organizations: Acme Corp, Beta LLC" in section_text
    assert "Time to first response: Met" in section_text
    assert "Time to resolution: In Progress" in section_text
    assert "Unable to connect to the corporate VPN from remote office." in section_text
    # Internal comments should be marked with [Internal Note]
    assert "[Internal Note] Checked RADIUS logs, user certificate expired." in section_text
    assert "Please provide your operating system version." in section_text


def test_jsm_issue_processing_exclude_internal_comments() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://support.example.com",
        project_key="ITSM",
        include_internal_comments=False,
    )
    issue = make_mock_jsm_issue()
    doc = connector._process_issue(issue)
    assert doc is not None

    section_text = doc.sections[0].text
    # Public comment should be included
    assert "Please provide your operating system version." in section_text
    # Internal comment should be excluded
    assert "Checked RADIUS logs, user certificate expired." not in section_text


def test_jsm_issue_processing_skip_labels(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jsm_connector.labels_to_skip = {"sensitive", "internal_confidential"}
    issue = make_mock_jsm_issue(labels=["vpn", "sensitive"])
    doc = jsm_connector._process_issue(issue)
    assert doc is None


def test_jsm_slim_documents(jsm_connector: JiraServiceManagementConnector) -> None:
    issue = make_mock_jsm_issue(key="ITSM-200", summary="Printer broken")

    with patch(
        "onyx.connectors.jira.connector._perform_jql_search",
        return_value=[issue],
    ):
        slim_batches = list(
            jsm_connector.retrieve_all_slim_docs(start=0, end=1000)
        )
        assert len(slim_batches) > 0
        all_slim_ids = [
            doc.id for batch in slim_batches for doc in batch if hasattr(doc, "id")
        ]
        assert "https://support.example.com/browse/ITSM-200" in all_slim_ids
