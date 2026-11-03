import time
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.credential_families import (
    credential_family_for_source,
    is_credential_usable_for_source,
    to_source_credential_json,
    to_stored_credential_json,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    METADATA_REQUEST_STATUS,
    METADATA_REQUEST_TYPE,
    METADATA_SLA_BREACHED,
    JiraServiceManagementConnector,
    extract_jsm_metadata,
    is_internal_comment,
    without_internal_comments,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

BASE_URL = "https://help.example.com"
PROJECT_KEY = "HELP"

REQUEST_TYPE_FIELD = {
    "_links": {},
    "requestType": {"id": "10", "name": "Get IT help"},
    "currentStatus": {"status": "Waiting for support"},
}
SLA_ONGOING = {
    "id": "1",
    "name": "Time to first response",
    "ongoingCycle": {
        "breached": False,
        "remainingTime": {"millis": 3600000, "friendly": "1h"},
    },
}
SLA_BREACHED = {
    "id": "2",
    "name": "Time to resolution",
    "ongoingCycle": {"breached": True, "remainingTime": {"friendly": "-2h"}},
}
SLA_MET = {
    "id": "3",
    "name": "Time to close",
    "completedCycles": [{"breached": False}],
}


def _raw_request(
    key: str,
    summary: str = "Laptop will not boot",
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "summary": summary,
        "updated": "2024-01-01T12:00:00.000+0000",
        "created": "2024-01-01T10:00:00.000+0000",
        "description": "My laptop shows a black screen.",
        "labels": [],
        "reporter": {"displayName": "Customer", "emailAddress": "c@example.com"},
        "assignee": {"displayName": "Agent", "emailAddress": "a@example.com"},
        "priority": {"name": "High"},
        "status": {"name": "In Progress"},
        "project": {"key": PROJECT_KEY, "name": "Help Desk"},
        "issuetype": {"name": "Service Request"},
        "comment": {"comments": []},
    }
    fields.update(extra_fields or {})
    return {"id": key.split("-")[-1], "key": key, "fields": fields}


@pytest.fixture
def mock_source_operations() -> MagicMock:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway._is_cloud.return_value = False
    return gateway


@pytest.fixture
def connector(
    mock_source_operations: MagicMock,
) -> Generator[JiraServiceManagementConnector, None, None]:
    jsm = JiraServiceManagementConnector(
        jira_base_url=f"{BASE_URL}/", project_key=PROJECT_KEY
    )
    jsm._source_operations = mock_source_operations
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield jsm


# --- metadata extraction -------------------------------------------------


def test_extract_jsm_metadata_reads_request_type_and_slas() -> None:
    issue = _raw_request(
        "HELP-1",
        extra_fields={
            "customfield_10010": REQUEST_TYPE_FIELD,
            "customfield_10020": SLA_ONGOING,
            "customfield_10021": SLA_BREACHED,
            "customfield_10022": SLA_MET,
        },
    )

    metadata = extract_jsm_metadata(issue)

    assert metadata[METADATA_REQUEST_TYPE] == "Get IT help"
    assert metadata[METADATA_REQUEST_STATUS] == "Waiting for support"
    assert metadata["sla_time_to_first_response"] == "ongoing (1h remaining)"
    assert metadata["sla_time_to_resolution"] == "breached"
    assert metadata["sla_time_to_close"] == "met"
    assert metadata[METADATA_SLA_BREACHED] == ["Time to resolution"]


def test_extract_jsm_metadata_ignores_non_jsm_issue() -> None:
    """Plain Jira issues (no JSM custom fields) yield no extra metadata."""
    issue = _raw_request("HELP-2", extra_fields={"customfield_1": {"value": "x"}})

    assert extract_jsm_metadata(issue) == {}


def test_extract_jsm_metadata_handles_missing_and_malformed_fields() -> None:
    assert extract_jsm_metadata({"key": "HELP-3"}) == {}
    assert extract_jsm_metadata({"key": "HELP-3", "fields": None}) == {}
    issue = _raw_request(
        "HELP-3",
        extra_fields={
            # request type without a name or status
            "customfield_1": {"requestType": {}},
            # completed SLA whose last cycle breached
            "customfield_2": {
                "name": "Time to resolution",
                "completedCycles": [{"breached": False}, {"breached": True}],
            },
            # SLA with no cycles yet
            "customfield_3": {"name": "Time to approve", "completedCycles": []},
        },
    )

    metadata = extract_jsm_metadata(issue)

    assert METADATA_REQUEST_TYPE not in metadata
    assert METADATA_REQUEST_STATUS not in metadata
    assert metadata["sla_time_to_resolution"] == "breached"
    assert metadata["sla_time_to_approve"] == "unknown"
    assert metadata[METADATA_SLA_BREACHED] == ["Time to resolution"]


# --- connector construction ----------------------------------------------


def test_connector_requires_project_key() -> None:
    with pytest.raises(ConnectorValidationError):
        JiraServiceManagementConnector(jira_base_url=BASE_URL, project_key="  ")


def test_connector_is_jira_connector_scoped_to_project(
    connector: JiraServiceManagementConnector,
) -> None:
    assert isinstance(connector, JiraConnector)
    assert connector.jira_base == BASE_URL
    assert connector.jira_project == PROJECT_KEY
    assert connector.jql_query is None
    query = connector._get_jql_query(0, time.time())
    assert query.startswith(f'project = "{PROJECT_KEY}" AND ')


def test_registry_maps_source_to_connector() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.class_name == JiraServiceManagementConnector.__name__
    assert mapping.config_class is JiraServiceManagementConnectorConfig


# --- config ----------------------------------------------------------------


def test_config_requires_non_blank_project_key() -> None:
    config = JiraServiceManagementConnectorConfig.model_validate(
        {"jira_base_url": BASE_URL, "project_key": " HELP "}
    )
    assert config.project_key == PROJECT_KEY

    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig.model_validate(
            {"jira_base_url": BASE_URL, "project_key": "   "}
        )
    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig.model_validate({"jira_base_url": BASE_URL})


# --- credentials -----------------------------------------------------------


def test_jsm_shares_the_atlassian_credential_family() -> None:
    assert credential_family_for_source(
        DocumentSource.JIRA_SERVICE_MANAGEMENT
    ) == credential_family_for_source(DocumentSource.JIRA)

    jira_json = {"jira_user_email": "u@example.com", "jira_api_token": "tok"}
    stored = to_stored_credential_json(DocumentSource.JIRA, jira_json, None)

    assert is_credential_usable_for_source(
        DocumentSource.JIRA, stored, DocumentSource.JIRA_SERVICE_MANAGEMENT
    )
    assert (
        to_source_credential_json(DocumentSource.JIRA_SERVICE_MANAGEMENT, stored)
        == jira_json
    )


# --- indexing --------------------------------------------------------------


def test_load_from_checkpoint_yields_jsm_documents(
    connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    mock_source_operations.search_issues.side_effect = [
        [
            _raw_request(
                "HELP-1",
                extra_fields={
                    "customfield_10010": REQUEST_TYPE_FIELD,
                    "customfield_10021": SLA_BREACHED,
                },
            ),
            _raw_request("HELP-2", summary="VPN access"),
        ],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())
    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert [d.id for d in documents] == [
        f"{BASE_URL}/browse/HELP-1",
        f"{BASE_URL}/browse/HELP-2",
    ]
    assert all(d.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for d in documents)
    first, second = documents
    assert first.semantic_identifier == "HELP-1: Laptop will not boot"
    assert first.metadata[METADATA_REQUEST_TYPE] == "Get IT help"
    assert first.metadata[METADATA_SLA_BREACHED] == ["Time to resolution"]
    # Standard Jira metadata is kept.
    assert first.metadata["key"] == "HELP-1"
    assert first.metadata["status"] == "In Progress"
    assert METADATA_REQUEST_TYPE not in second.metadata

    jql = mock_source_operations.search_issues.call_args_list[0].kwargs["jql"]
    assert jql.startswith(f'project = "{PROJECT_KEY}" AND ')


def test_plain_jira_connector_still_emits_jira_source(
    mock_source_operations: MagicMock,
) -> None:
    """The extension points must not change the Jira connector's output."""
    jira = JiraConnector(jira_base_url=BASE_URL, project_key=PROJECT_KEY)
    jira._source_operations = mock_source_operations
    mock_source_operations.search_issues.side_effect = [
        [
            _raw_request(
                "HELP-1", extra_fields={"customfield_10010": REQUEST_TYPE_FIELD}
            )
        ],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(jira, 0, time.time())
    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert len(documents) == 1
    assert documents[0].source == DocumentSource.JIRA
    assert METADATA_REQUEST_TYPE not in documents[0].metadata


# --- validation ------------------------------------------------------------


def test_validate_accepts_service_desk_project(
    connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    mock_source_operations.get_project.return_value = {
        "key": PROJECT_KEY,
        "projectTypeKey": "service_desk",
    }

    connector.validate_connector_settings()

    mock_source_operations.get_project.assert_called_once_with(project_key=PROJECT_KEY)


def test_validate_rejects_non_service_desk_project(
    connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    mock_source_operations.get_project.return_value = {
        "key": PROJECT_KEY,
        "projectTypeKey": "software",
    }

    with pytest.raises(ConnectorValidationError, match="not a Jira Service"):
        connector.validate_connector_settings()


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (401, CredentialExpiredError),
        (403, InsufficientPermissionsError),
        (404, ConnectorValidationError),
    ],
)
def test_validate_maps_api_errors(
    connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
    status_code: int,
    expected: type[Exception],
) -> None:
    mock_source_operations.get_project.side_effect = JiraApiError(
        "boom", status_code=status_code
    )

    with pytest.raises(expected):
        connector.validate_connector_settings()


def test_validate_without_credentials() -> None:
    jsm = JiraServiceManagementConnector(jira_base_url=BASE_URL, project_key="HELP")

    with pytest.raises(ConnectorMissingCredentialError):
        jsm.validate_connector_settings()


def test_extract_jsm_metadata_reads_status_without_request_type() -> None:
    """Moved requests can carry ``currentStatus`` without ``requestType``."""
    issue = _raw_request(
        "HELP-4",
        extra_fields={"customfield_1": {"currentStatus": {"status": "Resolved"}}},
    )

    metadata = extract_jsm_metadata(issue)

    assert metadata[METADATA_REQUEST_STATUS] == "Resolved"
    assert METADATA_REQUEST_TYPE not in metadata


def _comment(body: str, **extra: Any) -> dict[str, Any]:
    return {"body": body, "author": {"emailAddress": "agent@example.com"}, **extra}


@pytest.mark.parametrize(
    "comment,internal",
    [
        (_comment("public", jsdPublic=True), False),
        (_comment("note", jsdPublic=False), True),
        (
            _comment(
                "note",
                properties=[{"key": "sd.public.comment", "value": {"internal": True}}],
            ),
            True,
        ),
        (
            _comment(
                "public",
                properties=[{"key": "sd.public.comment", "value": {"internal": False}}],
            ),
            False,
        ),
        # Unknown visibility fails closed.
        (_comment("no visibility info"), True),
        (_comment("odd flag", jsdPublic="yes"), True),
        (
            _comment("malformed", properties=[{"key": "sd.public.comment"}]),
            True,
        ),
        (
            _comment(
                "conflict",
                jsdPublic=True,
                properties=[{"key": "sd.public.comment", "value": {"internal": True}}],
            ),
            True,
        ),
    ],
)
def test_is_internal_comment(comment: dict[str, Any], internal: bool) -> None:
    assert is_internal_comment(comment) is internal


def test_without_internal_comments_keeps_issue_untouched_when_all_public() -> None:
    issue = _raw_request("HELP-5")
    issue["fields"]["comment"]["comments"] = [_comment("hi", jsdPublic=True)]

    assert without_internal_comments(issue) is issue
    assert without_internal_comments({"key": "HELP-5"}) == {"key": "HELP-5"}


def test_internal_notes_are_not_indexed(
    connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    issue = _raw_request("HELP-6")
    issue["fields"]["comment"]["comments"] = [
        _comment("Customer reply: still broken", jsdPublic=True),
        _comment("INTERNAL: customer is on the risk list", jsdPublic=False),
        _comment("UNKNOWN: visibility not reported"),
    ]
    mock_source_operations.search_issues.side_effect = [[issue], []]

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())
    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert len(documents) == 1
    text = documents[0].sections[0].text or ""
    assert "Customer reply: still broken" in text
    assert "INTERNAL" not in text
    assert "UNKNOWN" not in text
    # The raw issue is not mutated.
    assert len(issue["fields"]["comment"]["comments"]) == 3
