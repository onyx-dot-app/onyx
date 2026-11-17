import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.source_operations import JiraApiError
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.models import (
    JsmComment,
    JsmRequest,
    JsmServiceDesk,
    JsmSla,
)
from onyx.connectors.models import Document, SlimDocument
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
)


def _jsm_request_raw(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "issueId": "10001",
        "issueKey": "SD-1",
        "requestType": {"id": "1", "name": "Password reset"},
        "currentStatus": {"name": "Waiting for customer"},
        "serviceDesk": {"id": "1", "projectKey": "SD", "name": "IT Help"},
        "reporter": {"displayName": "Test Reporter", "emailAddress": "r@example.com"},
        "organization": [{"id": "1", "name": "Acme"}],
        "createdDate": "2023-01-01T11:00:00.000+0000",
        "updatedDate": "2023-01-01T12:00:00.000+0000",
    }
    raw.update(overrides)
    return raw


def _jsm_comment_raw(
    body: Any = "a comment",
    public: bool = True,
    email: str = "user@example.com",
    name: str = "Test User",
) -> dict[str, Any]:
    return {
        "id": "1",
        "body": body,
        "author": {"displayName": name, "emailAddress": email},
        "public": public,
        "created": {"iso": "2023-01-01T11:30:00.000+0000"},
    }


def _jsm_sla_raw(name: str, breached: bool, goal: str = "4h") -> dict[str, Any]:
    return {
        "id": "1",
        "name": name,
        "ongoingCycle": {"breached": breached},
        "goalDuration": {"friendly": goal},
    }


def _configure_jsm_ops(mock_jsm_operations: MagicMock, issue_key: str = "SD-1") -> None:
    mock_jsm_operations.get_request.return_value = JsmRequest.from_raw(
        _jsm_request_raw(issueKey=issue_key)
    )
    mock_jsm_operations.get_request_comments.return_value = [
        JsmComment.from_raw(_jsm_comment_raw({"type": "text", "text": "public note"})),
        JsmComment.from_raw(
            _jsm_comment_raw({"type": "text", "text": "internal note"}, public=False)
        ),
    ]
    mock_jsm_operations.get_request_slas.return_value = [
        JsmSla.from_raw(_jsm_sla_raw("Time to first response", breached=False)),
        JsmSla.from_raw(_jsm_sla_raw("Time to resolution", breached=True)),
    ]


def test_config_requires_project_key(jira_base_url: str) -> None:
    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig(jira_base_url=jira_base_url)

    config = JiraServiceManagementConnectorConfig(
        jira_base_url=jira_base_url, project_key="SD"
    )
    assert config.project_key == "SD"
    assert config.include_internal_comments is False


def test_connector_init_strips_blank_project(jira_base_url: str) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url, project_key="  SD  "
    )
    assert connector.jira_project == "SD"
    assert connector.jira_base == jira_base_url
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jql_scopes_to_project_and_window(jsm_connector: JiraServiceManagementConnector) -> None:
    start = 1672531200.0  # 2023-01-01T00:00:00Z
    end = 1672617600.0
    query = jsm_connector._get_jql_query(start, end)
    assert query == (
        f'project = "SD" AND updated >= {int(start * 1000)} '
        f"AND updated <= {int(end * 1000)}"
    )


def test_load_produces_jsm_documents(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
    create_mock_issue: Any,
) -> None:
    _configure_jsm_ops(mock_jsm_operations)
    mock_jira_operations.search_issues.side_effect = [
        [create_mock_issue()],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(
        connector=jsm_connector, start=0, end=time.time()
    )
    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert len(docs) == 1
    doc = docs[0]
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.id == "https://jsm.example.com/browse/SD-1"
    assert doc.semantic_identifier == "SD-1: Cannot log in"
    assert doc.metadata["project"] == "SD"
    assert doc.metadata["issuetype"] == "Service Request"
    # Service desk enrichment.
    assert doc.metadata["request_type"] == "Password reset"
    assert doc.metadata["service_desk"] == "IT Help"
    assert doc.metadata["request_status"] == "Waiting for customer"
    assert doc.metadata["organizations"] == ["Acme"]
    assert doc.metadata["sla"] == [
        "SLA Time to first response: within goal (goal 4h)",
        "SLA Time to resolution: breached (goal 4h)",
    ]
    # Internal comment is excluded by default, public comment is indexed.
    text = doc.sections[0].text
    assert "public note" in text
    assert "internal note" not in text
    assert "I forgot my password" in text
    # SLA section is appended as its own searchable section.
    assert len(doc.sections) == 2
    assert "SLA Time to resolution: breached" in doc.sections[1].text


def test_internal_comments_indexed_when_enabled(
    jira_base_url: str,
    project_key: str,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
    create_mock_issue: Any,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        include_internal_comments=True,
    )
    connector._source_operations = mock_jira_operations
    connector._jsm_operations = mock_jsm_operations
    _configure_jsm_ops(mock_jsm_operations)
    mock_jira_operations.search_issues.side_effect = [[create_mock_issue()], []]

    outputs = load_everything_from_checkpoint_connector(
        connector=connector, start=0, end=time.time()
    )
    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert len(docs) == 1
    text = docs[0].sections[0].text
    assert "public note" in text
    assert "internal note" in text


def test_comment_email_blacklist_applies(
    jira_base_url: str,
    project_key: str,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
    create_mock_issue: Any,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        comment_email_blacklist=["bot@example.com"],
    )
    connector._source_operations = mock_jira_operations
    connector._jsm_operations = mock_jsm_operations
    mock_jsm_operations.get_request.return_value = JsmRequest.from_raw(
        _jsm_request_raw()
    )
    mock_jsm_operations.get_request_comments.return_value = [
        JsmComment.from_raw(
            _jsm_comment_raw({"type": "text", "text": "bot says hi"}, email="bot@example.com")
        ),
        JsmComment.from_raw(_jsm_comment_raw({"type": "text", "text": "human says hi"})),
    ]
    mock_jsm_operations.get_request_slas.return_value = []
    mock_jira_operations.search_issues.side_effect = [[create_mock_issue()], []]

    outputs = load_everything_from_checkpoint_connector(
        connector=connector, start=0, end=time.time()
    )
    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert len(docs) == 1
    text = docs[0].sections[0].text
    assert "bot says hi" not in text
    assert "human says hi" in text


def test_comments_fall_back_to_embedded_on_servicedesk_error(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
    create_mock_issue: Any,
) -> None:
    """No JSM app on the site: embedded issue comments are used instead."""
    mock_jsm_operations.get_request_comments.side_effect = JiraApiError(
        "Not Found", status_code=404
    )
    mock_jsm_operations.get_request.side_effect = JiraApiError(
        "Not Found", status_code=404
    )
    mock_jsm_operations.get_request_slas.side_effect = JiraApiError(
        "Not Found", status_code=404
    )
    issue = create_mock_issue(
        comments=[
            {
                "author": {"emailAddress": "user@example.com"},
                "body": {"type": "doc", "content": [{"type": "text", "text": "embedded note"}]},
            }
        ]
    )
    mock_jira_operations.search_issues.side_effect = [[issue], []]

    outputs = load_everything_from_checkpoint_connector(
        connector=jsm_connector, start=0, end=time.time()
    )
    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert len(docs) == 1
    assert "embedded note" in docs[0].sections[0].text
    # No servicedesk enrichment, but the document still indexes.
    assert "request_type" not in docs[0].metadata


def test_labels_to_skip_drops_ticket(
    jira_base_url: str,
    project_key: str,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
    create_mock_issue: Any,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        labels_to_skip=["secret"],
    )
    connector._source_operations = mock_jira_operations
    connector._jsm_operations = mock_jsm_operations
    _configure_jsm_ops(mock_jsm_operations)
    mock_jira_operations.search_issues.side_effect = [
        [create_mock_issue(labels=["secret"]), create_mock_issue(key="SD-2")],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(
        connector=connector, start=0, end=time.time()
    )
    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert [doc.id for doc in docs] == ["https://jsm.example.com/browse/SD-2"]


def test_slim_docs_match_indexed_ids(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_operations: MagicMock,
    create_mock_issue: Any,
) -> None:
    mock_jira_operations.search_issues.side_effect = [
        [create_mock_issue(key="SD-1"), create_mock_issue(key="SD-2")],
        [],
    ]
    with patch("onyx.connectors.jira.connector.JIRA_SLIM_PAGE_SIZE", 2):
        slim_batches = list(
            jsm_connector.retrieve_all_slim_docs(start=0, end=time.time())
        )

    slim_docs = [
        doc for batch in slim_batches for doc in batch if isinstance(doc, SlimDocument)
    ]
    assert {doc.id for doc in slim_docs} == {
        "https://jsm.example.com/browse/SD-1",
        "https://jsm.example.com/browse/SD-2",
    }


def test_validate_connector_settings_rejects_non_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
) -> None:
    mock_jira_operations.get_project.return_value = {"key": "SD"}
    mock_jsm_operations.list_service_desks.return_value = [
        JsmServiceDesk(id="2", project_key="OTHER", project_name="Other")
    ]
    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        jsm_connector.validate_connector_settings()


def test_validate_connector_settings_accepts_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
) -> None:
    mock_jira_operations.get_project.return_value = {"key": "SD"}
    mock_jsm_operations.list_service_desks.return_value = [
        JsmServiceDesk(id="1", project_key="sd", project_name="Service Desk")
    ]
    jsm_connector.validate_connector_settings()


def test_validate_connector_settings_tolerates_missing_servicedesk_api(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
) -> None:
    """No JSM app on the site (servicedesk API 404): the Jira API project
    check already passed, so validation passes."""
    mock_jira_operations.get_project.return_value = {"key": "SD"}
    mock_jsm_operations.list_service_desks.side_effect = JiraApiError(
        "Not Found", status_code=404
    )
    jsm_connector.validate_connector_settings()


def test_validate_connector_settings_propagates_credential_errors(
    jsm_connector: JiraServiceManagementConnector,
    mock_jira_operations: MagicMock,
    mock_jsm_operations: MagicMock,
) -> None:
    from onyx.connectors.exceptions import CredentialExpiredError

    mock_jira_operations.get_project.side_effect = JiraApiError(
        "Unauthorized", status_code=401
    )
    with pytest.raises(CredentialExpiredError):
        jsm_connector.validate_connector_settings()


def test_load_credentials_builds_both_gateways(
    jira_base_url: str, project_key: str
) -> None:
    from onyx.connectors.jira.source_operations import JiraSourceOperations
    from onyx.connectors.jira_service_management.source_operations import (
        JiraServiceManagementSourceOperations,
    )

    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url, project_key=project_key
    )
    result = connector.load_credentials(
        {"jira_user_email": "user@example.com", "jira_api_token": "token"}
    )
    assert result is None
    assert isinstance(connector.source_operations, JiraSourceOperations)
    assert isinstance(connector.jsm_operations, JiraServiceManagementSourceOperations)
    assert connector.jsm_operations.connector_specific_config == {
        "jira_base_url": jira_base_url,
        "scoped_token": False,
    }
    assert (
        connector.jsm_operations.credentials_provider.get_credentials()
        == connector.source_operations.credentials_provider.get_credentials()
    )


def test_missing_credentials_raises(jira_base_url: str, project_key: str) -> None:
    from onyx.connectors.models import ConnectorMissingCredentialError

    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url, project_key=project_key
    )
    with pytest.raises(ConnectorMissingCredentialError):
        _ = connector.jsm_operations
