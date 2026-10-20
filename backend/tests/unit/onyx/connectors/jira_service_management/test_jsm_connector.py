import time
from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    FIELD_ORGANIZATIONS,
    FIELD_REQUEST_PORTAL_URL,
    FIELD_REQUEST_STATUS,
    FIELD_REQUEST_TYPE,
    FIELD_SLA_BREACHED,
    FIELD_SLA_ONGOING,
    JiraServiceManagementConnector,
    extract_jsm_metadata,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

BASE_URL = "https://acme.atlassian.net"


def _jsm_issue(key: str = "SD-1", with_jsm_fields: bool = True) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "summary": "VPN is down",
        "updated": "2024-05-01T12:00:00.000+0000",
        "created": "2024-05-01T10:00:00.000+0000",
        "description": "Cannot connect to the VPN since this morning.",
        "labels": [],
        "reporter": {"displayName": "Customer", "emailAddress": "c@x.com"},
        "assignee": {"displayName": "Agent", "emailAddress": "a@acme.com"},
        "priority": {"name": "High"},
        "status": {"name": "Waiting for support"},
        "resolution": None,
        "project": {"key": "SD", "name": "Service Desk"},
        "issuetype": {"name": "IT Help"},
        "parent": None,
        "comment": {"comments": []},
    }
    if with_jsm_fields:
        fields["customfield_10010"] = {
            "_links": {"web": f"{BASE_URL}/servicedesk/customer/portal/1/{key}"},
            "requestType": {"id": "7", "name": "Get IT help"},
            "currentStatus": {"status": "Waiting for support"},
        }
        fields["customfield_10030"] = {
            "id": "1",
            "name": "Time to first response",
            "ongoingCycle": {"breached": True, "paused": False},
        }
        fields["customfield_10031"] = {
            "id": "2",
            "name": "Time to resolution",
            "completedCycles": [{"breached": False}],
        }
        fields["customfield_10002"] = [
            {"id": "1", "name": "Globex", "_links": {"self": "x"}},
            {"id": "2", "name": "Acme", "_links": {"self": "y"}},
        ]
    return {"id": key.split("-")[-1], "key": key, "fields": fields}


@pytest.fixture
def source_operations() -> MagicMock:
    ops = create_autospec(JiraSourceOperations, instance=True)
    ops._is_cloud.return_value = False
    return ops


@pytest.fixture
def connector(source_operations: MagicMock) -> JiraServiceManagementConnector:
    c = JiraServiceManagementConnector(jira_base_url=BASE_URL + "/", project_key="SD")
    c._source_operations = source_operations
    return c


def test_extract_jsm_metadata() -> None:
    metadata = extract_jsm_metadata(_jsm_issue())
    assert metadata[FIELD_REQUEST_TYPE] == "Get IT help"
    assert metadata[FIELD_REQUEST_STATUS] == "Waiting for support"
    assert str(metadata[FIELD_REQUEST_PORTAL_URL]).endswith("/portal/1/SD-1")
    assert metadata[FIELD_ORGANIZATIONS] == ["Acme", "Globex"]
    assert metadata[FIELD_SLA_BREACHED] == ["Time to first response"]
    assert metadata[FIELD_SLA_ONGOING] == ["Time to first response"]


def test_extract_jsm_metadata_without_jsm_fields() -> None:
    assert extract_jsm_metadata(_jsm_issue(with_jsm_fields=False)) == {}
    assert extract_jsm_metadata({"key": "SD-1"}) == {}


def test_project_key_is_required() -> None:
    with pytest.raises(ConnectorValidationError):
        JiraServiceManagementConnector(jira_base_url=BASE_URL, project_key="  ")


def test_jql_is_scoped_to_service_project(
    connector: JiraServiceManagementConnector,
) -> None:
    jql = connector._get_jql_query(0, 100)
    assert jql.startswith('project = "SD" AND ')
    assert connector.jql_query is None


def test_is_a_jira_connector_with_its_own_source(
    connector: JiraServiceManagementConnector,
) -> None:
    assert isinstance(connector, JiraConnector)
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    # Jira itself is unchanged.
    assert JiraConnector.document_source == DocumentSource.JIRA


def test_indexing_yields_jsm_documents(
    connector: JiraServiceManagementConnector, source_operations: MagicMock
) -> None:
    source_operations.search_issues.side_effect = [
        [_jsm_issue("SD-1"), _jsm_issue("SD-2", with_jsm_fields=False)],
        [],
    ]
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())
    docs = [item for out in outputs for item in out.items if isinstance(item, Document)]
    assert [d.id for d in docs] == [
        f"{BASE_URL}/browse/SD-1",
        f"{BASE_URL}/browse/SD-2",
    ]
    assert all(d.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for d in docs)
    assert docs[0].metadata[FIELD_REQUEST_TYPE] == "Get IT help"
    assert docs[0].metadata["project"] == "SD"
    assert FIELD_REQUEST_TYPE not in docs[1].metadata
    assert "VPN" in (docs[0].sections[0].text or "")


def test_load_credentials_uses_jsm_source() -> None:
    c = JiraServiceManagementConnector(jira_base_url=BASE_URL, project_key="SD")
    with (
        patch(
            "onyx.connectors.jira.connector.OnyxStaticCredentialsProvider"
        ) as provider,
        patch("onyx.connectors.jira.connector.JiraSourceOperations"),
    ):
        c.load_credentials({"jira_api_token": "t", "jira_user_email": "e@x.com"})
    assert provider.call_args.args[1] == DocumentSource.JIRA_SERVICE_MANAGEMENT.value


def test_validate_accepts_service_desk_project(
    connector: JiraServiceManagementConnector, source_operations: MagicMock
) -> None:
    source_operations.get_project.return_value = {
        "key": "SD",
        "projectTypeKey": "service_desk",
    }
    connector.validate_connector_settings()
    source_operations.get_project.assert_called_once_with(project_key="SD")


def test_validate_rejects_software_project(
    connector: JiraServiceManagementConnector, source_operations: MagicMock
) -> None:
    source_operations.get_project.return_value = {
        "key": "SD",
        "projectTypeKey": "software",
    }
    with pytest.raises(ConnectorValidationError, match="service_desk"):
        connector.validate_connector_settings()


def test_validate_rejects_missing_project_type(
    connector: JiraServiceManagementConnector, source_operations: MagicMock
) -> None:
    source_operations.get_project.return_value = {"key": "SD"}
    with pytest.raises(ConnectorValidationError, match="service_desk"):
        connector.validate_connector_settings()


def test_validate_requires_credentials() -> None:
    c = JiraServiceManagementConnector(jira_base_url=BASE_URL, project_key="SD")
    with pytest.raises(ConnectorMissingCredentialError):
        c.validate_connector_settings()


def test_registered_with_config() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.class_name == "JiraServiceManagementConnector"
    assert mapping.config_class is JiraServiceManagementConnectorConfig
    config = JiraServiceManagementConnectorConfig(
        jira_base_url=BASE_URL, project_key="SD"
    )
    assert config.project_key == "SD"
    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig(jira_base_url=BASE_URL)  # ty: ignore[missing-argument]
