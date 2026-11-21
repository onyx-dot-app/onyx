from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    request_metadata,
)
from onyx.connectors.models import Document

_BASE_URL = "https://example.atlassian.net"


def _connector(gateway: MagicMock | None = None) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=_BASE_URL, project_key="HELP"
    )
    connector._source_operations = gateway or create_autospec(
        JiraSourceOperations, instance=True
    )
    return connector


def _request_issue() -> dict[str, Any]:
    return {
        "id": "10001",
        "key": "HELP-1",
        "fields": {
            "summary": "Laptop will not boot",
            "updated": "2023-01-01T12:00:00.000+0000",
            "created": "2023-01-01T12:00:00.000+0000",
            "description": "It is broken",
            "labels": [],
            "project": {"key": "HELP", "name": "Help Desk"},
            "issuetype": {"name": "Service Request"},
            "status": {"name": "Waiting for support"},
            "comment": {"comments": []},
            "customfield_10010": {
                "requestType": {"name": "Get IT help"},
                "currentStatus": {"status": "Waiting for support"},
                "_links": {"web": f"{_BASE_URL}/servicedesk/customer/portal/1/HELP-1"},
            },
        },
    }


def test_config_requires_a_project_key() -> None:
    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig.model_validate(
            {"jira_base_url": _BASE_URL, "project_key": "  "}
        )
    config = JiraServiceManagementConnectorConfig.model_validate(
        {"jira_base_url": _BASE_URL, "project_key": " HELP "}
    )
    assert config.project_key == "HELP"


def test_connector_requires_a_project_key() -> None:
    with pytest.raises(ValueError):
        JiraServiceManagementConnector(jira_base_url=_BASE_URL, project_key=" ")


def test_validation_accepts_a_service_desk_project() -> None:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway.get_project.return_value = {"key": "HELP", "projectTypeKey": "service_desk"}
    _connector(gateway).validate_connector_settings()


def test_validation_rejects_a_software_project() -> None:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway.get_project.return_value = {"key": "HELP", "projectTypeKey": "software"}
    with pytest.raises(ConnectorValidationError, match="not a Jira Service"):
        _connector(gateway).validate_connector_settings()


def test_request_metadata_reads_the_portal_field() -> None:
    assert request_metadata(_request_issue()) == {
        "request_type": "Get IT help",
        "request_status": "Waiting for support",
        "portal_link": f"{_BASE_URL}/servicedesk/customer/portal/1/HELP-1",
    }


def test_request_metadata_is_empty_for_a_plain_issue() -> None:
    issue = _request_issue()
    del issue["fields"]["customfield_10010"]
    assert request_metadata(issue) == {}


def test_documents_carry_the_service_management_source() -> None:
    items = list(_connector()._issue_to_items(_request_issue(), set(), False))
    documents = [item for item in items if isinstance(item, Document)]
    assert len(documents) == 1
    assert documents[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert documents[0].metadata["request_type"] == "Get IT help"
    assert documents[0].semantic_identifier == "HELP-1: Laptop will not boot"


def test_jql_is_limited_to_the_project() -> None:
    assert 'project = "HELP"' in _connector()._get_jql_query(0, 1_700_000_000)
