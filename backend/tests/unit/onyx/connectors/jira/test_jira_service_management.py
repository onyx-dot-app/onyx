import time
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira.service_management_connector import (
    DOC_ID_PREFIX,
    JiraServiceManagementConnector,
    extract_request_type,
    extract_sla_state,
)
from onyx.connectors.models import Document, SlimDocument, TextSection
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

_REQUEST_TYPE_FIELD_ID = "customfield_10010"
_SLA_FIELD_ID = "customfield_10030"

_JIRA_FIELDS = [
    {
        "id": _REQUEST_TYPE_FIELD_ID,
        "name": "Request Type",
        "custom": True,
        "schema": {
            "type": "sd-customerrequesttype",
            "custom": "com.atlassian.servicedesk:vp-origin",
        },
    },
    {
        "id": _SLA_FIELD_ID,
        "name": "Time to resolution",
        "custom": True,
        "schema": {"type": "sla", "custom": "com.atlassian.servicedesk:sd-sla-field"},
    },
    {"id": "summary", "name": "Summary", "custom": False, "schema": {"type": "string"}},
]


def _make_request(
    key: str = "SUP-1",
    summary: str = "Laptop broken",
    request_type: dict[str, Any] | None = None,
    sla: dict[str, Any] | None = None,
) -> MagicMock:
    issue = MagicMock(spec=Issue)
    issue.key = key
    issue.fields = MagicMock()
    issue.fields.summary = summary
    issue.fields.description = "My laptop does not start"
    issue.fields.updated = "2023-01-02T12:00:00.000+0000"
    issue.fields.created = "2023-01-01T12:00:00.000+0000"
    issue.fields.labels = []
    issue.fields.comment.comments = []
    issue.fields.reporter = MagicMock()
    issue.fields.reporter.displayName = "Reporting User"
    issue.fields.reporter.emailAddress = "reporter@example.com"
    issue.fields.assignee = None
    issue.fields.priority = None
    issue.fields.status = None
    issue.fields.resolution = None
    issue.fields.duedate = None
    issue.fields.resolutiondate = None
    issue.fields.parent = None
    issue.fields.issuetype = MagicMock()
    issue.fields.issuetype.name = "Service Request"
    issue.fields.project = MagicMock()
    issue.fields.project.key = "SUP"
    issue.fields.project.name = "Support Desk"
    setattr(issue.fields, _REQUEST_TYPE_FIELD_ID, request_type)
    setattr(issue.fields, _SLA_FIELD_ID, sla)
    issue.raw = {"fields": {"description": issue.fields.description}}
    return issue


def _make_project(key: str, project_type: str) -> MagicMock:
    project = MagicMock()
    project.key = key
    project.projectTypeKey = project_type
    return project


@pytest.fixture
def jsm_connector(
    jira_base_url: str, mock_jira_client: MagicMock
) -> Generator[JiraServiceManagementConnector, None, None]:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key="SUP",
    )
    connector._jira_client = mock_jira_client
    mock_jira_client._options = {"rest_api_version": "2"}
    mock_jira_client.client_info.return_value = jira_base_url
    mock_jira_client.fields.return_value = _JIRA_FIELDS
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector


def test_documents_use_service_management_source_and_ids(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    request = _make_request(
        request_type={"requestType": {"id": "17", "name": "Get IT help"}},
        sla={"ongoingCycle": {"breached": True}},
    )
    cast(MagicMock, jsm_connector.jira_client.search_issues).side_effect = [
        [request],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(jsm_connector, 0, time.time())

    documents = [item for output in outputs for item in output.items]
    assert len(documents) == 1
    document = documents[0]
    assert isinstance(document, Document)
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.id == f"{DOC_ID_PREFIX}https://jira.example.com/browse/SUP-1"
    # links still point at the Jira UI
    section = document.sections[0]
    assert isinstance(section, TextSection)
    assert section.link == "https://jira.example.com/browse/SUP-1"
    assert document.metadata["request_type"] == "Get IT help"
    assert document.metadata["sla_time_to_resolution"] == "breached"
    assert document.metadata["key"] == "SUP-1"


def test_documents_without_service_management_fields(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """A request with no request type and no SLA data still gets indexed."""
    cast(MagicMock, jsm_connector.jira_client.search_issues).side_effect = [
        [_make_request()],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(jsm_connector, 0, time.time())

    documents = [item for output in outputs for item in output.items]
    assert len(documents) == 1
    document = documents[0]
    assert isinstance(document, Document)
    assert "request_type" not in document.metadata
    assert "sla_time_to_resolution" not in document.metadata


def test_slim_documents_use_prefixed_ids(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    with (
        patch(
            "onyx.connectors.jira.connector._perform_jql_search",
            return_value=[_make_request()],
        ),
        patch.object(
            JiraServiceManagementConnector,
            "update_checkpoint_for_next_run",
            side_effect=lambda checkpoint, *_args, **_kwargs: setattr(
                checkpoint, "has_more", False
            ),
        ),
    ):
        batches = list(jsm_connector.retrieve_all_slim_docs(0, time.time()))

    slim_docs = [
        doc for batch in batches for doc in batch if isinstance(doc, SlimDocument)
    ]
    assert [doc.id for doc in slim_docs] == [
        f"{DOC_ID_PREFIX}https://jira.example.com/browse/SUP-1"
    ]


def test_jql_scopes_to_service_desk_projects(
    jira_base_url: str, mock_jira_client: MagicMock
) -> None:
    connector = JiraServiceManagementConnector(jira_base_url=jira_base_url)
    connector._jira_client = mock_jira_client
    cast(MagicMock, mock_jira_client.projects).return_value = [
        _make_project("SUP", "service_desk"),
        _make_project("ENG", "software"),
    ]
    start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

    jql = connector._get_jql_query(start, end)

    assert jql.startswith('project in ("SUP") AND ')
    assert "ENG" not in jql
    assert f"updated >= {int(start * 1000)}" in jql


def test_jql_without_visible_service_desk_projects_fails(
    jira_base_url: str, mock_jira_client: MagicMock
) -> None:
    connector = JiraServiceManagementConnector(jira_base_url=jira_base_url)
    connector._jira_client = mock_jira_client
    cast(MagicMock, mock_jira_client.projects).return_value = [
        _make_project("ENG", "software")
    ]

    with pytest.raises(ConnectorValidationError):
        connector._get_jql_query(0, time.time())


def test_jql_keeps_configured_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jql = jsm_connector._get_jql_query(0, time.time())

    assert jql.startswith('project = "SUP" AND ')
    cast(MagicMock, jsm_connector.jira_client.projects).assert_not_called()


def test_validate_rejects_non_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    cast(MagicMock, jsm_connector.jira_client.project).return_value = _make_project(
        "SUP", "software"
    )

    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        jsm_connector.validate_connector_settings()


def test_validate_accepts_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    cast(MagicMock, jsm_connector.jira_client.project).return_value = _make_project(
        "SUP", "service_desk"
    )

    jsm_connector.validate_connector_settings()


def test_checkpoint_is_reused_from_jira_connector(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert isinstance(jsm_connector.build_dummy_checkpoint(), JiraConnectorCheckpoint)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ({"requestType": {"name": "Get IT help"}}, "Get IT help"),
        ({"name": "Report a bug"}, "Report a bug"),
        ({"value": "Ask a question"}, "Ask a question"),
        ({"requestType": {}}, None),
    ],
)
def test_extract_request_type(value: Any, expected: str | None) -> None:
    assert extract_request_type(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ({}, None),
        ({"ongoingCycle": {"breached": False}}, "ongoing"),
        ({"ongoingCycle": {"breached": True}}, "breached"),
        ({"completedCycles": [{"breached": False}]}, "met"),
        (
            {"completedCycles": [{"breached": False}, {"breached": True}]},
            "breached",
        ),
    ],
)
def test_extract_sla_state(value: Any, expected: str | None) -> None:
    assert extract_sla_state(value) == expected
