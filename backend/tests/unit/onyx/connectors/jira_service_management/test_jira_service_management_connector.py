import copy
from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
)
from onyx.connectors.jira.connector import JiraConnector, JiraConnectorCheckpoint
from onyx.connectors.jira.source_operations import (
    JiraApiError,
    JiraSourceOperations,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    DOCUMENT_ID_PREFIX,
    JiraServiceManagementConnector,
    request_metadata,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    SlimDocument,
)

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
    gateway.get_project.assert_called_once_with(project_key="HELP", fast=True)


def test_validation_rejects_a_software_project() -> None:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway.get_project.return_value = {"key": "HELP", "projectTypeKey": "software"}
    with pytest.raises(ConnectorValidationError, match="not a Jira Service"):
        _connector(gateway).validate_connector_settings()
    gateway.get_project.assert_called_once_with(project_key="HELP", fast=True)


def test_validation_requires_credentials() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=_BASE_URL, project_key="HELP"
    )
    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()


def test_validation_maps_an_unauthorized_error() -> None:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway.get_project.side_effect = JiraApiError("Unauthorized", status_code=401)
    with pytest.raises(CredentialExpiredError):
        _connector(gateway).validate_connector_settings()


def test_internal_comments_are_not_indexed() -> None:
    issue = _request_issue()
    issue["fields"]["comment"] = {
        "comments": [
            {"body": "public reply", "jsdPublic": True},
            {"body": "no flag reply"},
            {"body": "agent only note", "jsdPublic": False},
            {
                "body": "bot noise",
                "jsdPublic": True,
                "author": {"emailAddress": "bot@x.com"},
            },
        ]
    }
    before = copy.deepcopy(issue)
    connector = JiraServiceManagementConnector(
        jira_base_url=_BASE_URL,
        project_key="HELP",
        comment_email_blacklist=["bot@x.com"],
    )
    connector._source_operations = create_autospec(JiraSourceOperations, instance=True)
    documents = [
        item
        for item in connector._issue_to_items(issue, set(), False)
        if isinstance(item, Document)
    ]
    text = documents[0].sections[0].text or ""
    assert "public reply" in text
    assert "no flag reply" in text
    assert "agent only note" not in text
    assert "bot noise" not in text
    assert issue == before


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


_PLAIN_ID = f"{_BASE_URL}/browse/HELP-1"
_NAMESPACED_ID = DOCUMENT_ID_PREFIX + _PLAIN_ID


def _checkpoint(connector: JiraServiceManagementConnector) -> JiraConnectorCheckpoint:
    return connector.build_dummy_checkpoint()


def test_document_ids_differ_from_the_jira_connector() -> None:
    jira = JiraConnector(jira_base_url=_BASE_URL, project_key="HELP")
    jira._source_operations = create_autospec(JiraSourceOperations, instance=True)
    jira_ids = {
        item.id
        for item in jira._issue_to_items(_request_issue(), set(), False)
        if isinstance(item, Document)
    }
    connector = _connector()
    with patch(
        "onyx.connectors.jira.connector._perform_jql_search",
        return_value=iter([_request_issue()]),
    ):
        items = list(
            connector._load_from_checkpoint("jql", _checkpoint(connector), False)
        )
    documents = [item for item in items if isinstance(item, Document)]
    assert jira_ids == {_PLAIN_ID}
    assert [d.id for d in documents] == [_NAMESPACED_ID]
    assert documents[0].sections[0].link == _PLAIN_ID


def test_failures_carry_the_namespaced_id() -> None:
    connector = _connector()
    with (
        patch(
            "onyx.connectors.jira.connector._perform_jql_search",
            return_value=iter([_request_issue()]),
        ),
        patch.object(
            JiraServiceManagementConnector,
            "_issue_to_items",
            side_effect=RuntimeError("boom"),
        ),
    ):
        items = list(
            connector._load_from_checkpoint("jql", _checkpoint(connector), False)
        )
    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == _NAMESPACED_ID
    assert failures[0].failed_document.document_link == _PLAIN_ID


def test_slim_documents_carry_the_namespaced_id() -> None:
    connector = _connector()

    def _finish(checkpoint: JiraConnectorCheckpoint, *_args: Any) -> None:
        checkpoint.has_more = False

    with (
        patch(
            "onyx.connectors.jira.connector._perform_jql_search",
            return_value=iter([_request_issue()]),
        ),
        patch.object(connector, "update_checkpoint_for_next_run", side_effect=_finish),
    ):
        batches = list(connector.retrieve_all_slim_docs())
    slim_ids = [
        item.id for batch in batches for item in batch if isinstance(item, SlimDocument)
    ]
    assert slim_ids == [_NAMESPACED_ID]


def test_reindex_round_trips_a_namespaced_id() -> None:
    connector = _connector()
    failure = ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=_NAMESPACED_ID, document_link=_PLAIN_ID
        ),
        failure_message="failed",
    )
    with patch.object(
        JiraServiceManagementConnector,
        "_fetch_issues_by_key",
        return_value=([_request_issue()], {}),
    ):
        items = list(connector.reindex([failure]))
    assert [i.id for i in items if isinstance(i, Document)] == [_NAMESPACED_ID]
    assert not [i for i in items if isinstance(i, ConnectorFailure)]
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == _NAMESPACED_ID


def test_jql_is_limited_to_the_project() -> None:
    assert 'project = "HELP"' in _connector()._get_jql_query(0, 1_700_000_000)
