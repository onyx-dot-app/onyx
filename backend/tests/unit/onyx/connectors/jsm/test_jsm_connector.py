"""Unit tests for the Jira Service Management connector.

All HTTP is mocked (``responses`` for the JSM REST surface, ``MagicMock`` for
the ``jira`` client), so the suite runs with no live Atlassian instance.
"""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
import responses
from jira import JIRA

from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jsm.client import build_jsm_session
from onyx.connectors.jsm.connector import (
    JiraServiceManagementConnector,
    JsmConnectorCheckpoint,
)
from onyx.connectors.jsm.connector_utils import process_jsm_issue
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

_JSM_BASE = "https://jsm.example.com"

_ISSUE_ID = "10001"
_ISSUE_KEY = "HELP-1"

_SERVICE_DESKS_PAYLOAD: dict[str, Any] = {
    "values": [{"id": "10", "projectName": "Help Desk", "projectId": "100"}],
    "isLastPage": True,
    "_links": {},
}

_ADF_DESCRIPTION: dict[str, Any] = {
    "type": "doc",
    "version": 1,
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "My laptop will not start."}],
        }
    ],
}


def _issue_payload(
    key: str = _ISSUE_KEY,
    issue_id: str = _ISSUE_ID,
    summary: str = "Laptop will not start",
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "key": key,
        "fields": {
            "summary": summary,
            "description": _ADF_DESCRIPTION,
            "created": "2026-09-01T10:00:00.000+0000",
            "updated": "2026-09-02T10:00:00.000+0000",
            "status": {"name": "Open"},
            "priority": {"name": "High"},
            "issuetype": {"name": "Service Request"},
            "project": {"key": "HELP", "name": "Help Desk"},
            "reporter": {
                "displayName": "Ada Reporter",
                "emailAddress": "ada@example.com",
            },
            "assignee": {
                "displayName": "Grace Assignee",
                "emailAddress": "grace@example.com",
            },
            "comment": {
                "comments": [
                    {"body": "Have you tried a different charger?"},
                    {"body": "Yes, still dead."},
                ]
            },
        },
    }


def _request_type_payload() -> dict[str, Any]:
    # GET request/{id}/requesttype returns a single object with a top-level name.
    return {"id": "25", "name": "Request a laptop", "description": ""}


def _participants_payload() -> dict[str, Any]:
    return {
        "values": [
            {"displayName": "Sam Participant", "emailAddress": "sam@example.com"}
        ],
        "isLastPage": True,
    }


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock.search_issues = MagicMock()
    return mock


@pytest.fixture
def connector(mock_jira_client: MagicMock) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jsm_base_url=_JSM_BASE,
        service_desk_id="10",
    )
    connector._jira_client = mock_jira_client
    return connector


def _mock_search_issues(
    connector: JiraServiceManagementConnector,
    raw_issues: list[dict[str, Any]],
) -> None:
    issues: list[MagicMock] = []
    for raw in raw_issues:
        issue = MagicMock()
        issue.raw = raw
        issues.append(issue)
    connector._jira_client.search_issues.return_value = issues


class TestProcessJsmIssue:
    def test_builds_document_with_jsm_metadata(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/request/{_ISSUE_ID}/requesttype",
                json=_request_type_payload(),
            )
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/request/{_ISSUE_ID}/participant",
                json=_participants_payload(),
            )
            document = process_jsm_issue(_JSM_BASE, _issue_payload(), session=session)

        assert document is not None
        assert document.source == DocumentSource.JSM
        assert document.id == f"{_JSM_BASE}/browse/{_ISSUE_KEY}"
        assert document.semantic_identifier == f"{_ISSUE_KEY}: Laptop will not start"
        assert "My laptop will not start." in document.sections[0].text
        assert (
            "Comment: Have you tried a different charger?" in document.sections[0].text
        )
        assert document.metadata is not None
        assert document.metadata["request_type"] == "Request a laptop"
        assert document.metadata["participants"] == ["Sam Participant"]
        assert document.metadata["status"] == "Open"
        assert document.primary_owners is not None
        assert {owner.get_semantic_name() for owner in document.primary_owners} == {
            "Ada Reporter",
            "Grace Assignee",
        }

    def test_oversized_issue_is_skipped(self) -> None:
        issue = _issue_payload()
        issue["fields"]["description"] = "x" * (200 * 1024)
        document = process_jsm_issue(_JSM_BASE, issue, session=None)
        assert document is None

    def test_plain_text_description_is_kept(self) -> None:
        issue = _issue_payload()
        issue["fields"]["description"] = "Plain description"
        document = process_jsm_issue(_JSM_BASE, issue, session=None)
        assert document is not None
        assert "Plain description" in document.sections[0].text

    def test_jsm_enrichment_failure_does_not_block_indexing(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/request/{_ISSUE_ID}/requesttype",
                status=404,
            )
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/request/{_ISSUE_ID}/participant",
                status=500,
            )
            document = process_jsm_issue(_JSM_BASE, _issue_payload(), session=session)

        assert document is not None
        assert document.metadata is not None
        assert "request_type" not in document.metadata
        assert "participants" not in document.metadata


class TestJsmConnectorCheckpointing:
    def test_loads_all_pages(self, connector: JiraServiceManagementConnector) -> None:
        page_one = [
            _issue_payload(issue_id=str(10000 + i), key=f"HELP-{i}") for i in range(50)
        ]
        page_two = [_issue_payload(issue_id="10100", key="HELP-100")]

        def search_issues_side_effect(
            jql_str: str,  # noqa: ARG001
            startAt: int,
            maxResults: int,  # noqa: ARG001
        ) -> list[MagicMock]:
            if startAt == 0:
                raw_issues = page_one
            else:
                raw_issues = page_two
            mocked = []
            for raw in raw_issues:
                issue = MagicMock()
                issue.raw = raw
                mocked.append(issue)
            return mocked

        connector._jira_client.search_issues.side_effect = search_issues_side_effect

        outputs = load_everything_from_checkpoint_connector(connector, 0, 10)

        # Two batches: the first fills the page, the second is the tail.
        assert len(outputs) == 2
        documents = [
            item for out in outputs for item in out.items if isinstance(item, Document)
        ]
        assert len(documents) == 51
        final_checkpoint = outputs[-1].next_checkpoint
        assert final_checkpoint.has_more is False

    def test_checkpoint_round_trips_through_json(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        checkpoint = connector.build_dummy_checkpoint()
        validated = connector.validate_checkpoint_json(checkpoint.model_dump_json())
        assert validated == JsmConnectorCheckpoint(has_more=True)

    def test_failure_yields_connector_failure_not_raise(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        _mock_search_issues(connector, [_issue_payload()])
        bad_session = MagicMock()
        connector._jsm_session = bad_session

        # Make the document processor blow up by having the jira client raise
        # inside processing (simulated via an unserializable issue).
        raw = _issue_payload()
        raw["fields"] = None  # type: ignore[assignment]
        _mock_search_issues(connector, [raw])

        outputs = load_everything_from_checkpoint_connector(connector, 0, 10)
        assert len(outputs) == 1
        assert all(not isinstance(item, Document) for item in outputs[0].items)
        assert outputs[0].items, "Expected a ConnectorFailure to be yielded"


class TestJsmConnectorValidation:
    def test_missing_credentials_raise(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        connector._jira_client = None
        with pytest.raises(ConnectorMissingCredentialError):
            connector.validate_connector_settings()

    def test_validate_lists_service_desks(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        connector._jsm_session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                json=_SERVICE_DESKS_PAYLOAD,
            )
            _mock_search_issues(connector, [])
            connector.validate_connector_settings()

    def test_unknown_service_desk_raises(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        connector.service_desk_id = "999"
        connector._jsm_session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                json=_SERVICE_DESKS_PAYLOAD,
            )
            with pytest.raises(ConnectorValidationError, match="999"):
                connector.validate_connector_settings()

    def test_expired_credential_raises(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        connector._jsm_session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                status=401,
            )
            with pytest.raises(CredentialExpiredError):
                connector.validate_connector_settings()

    def test_forbidden_credential_raises(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        connector._jsm_session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                status=403,
            )
            with pytest.raises(InsufficientPermissionsError):
                connector.validate_connector_settings()


class TestJsmConnectorSlim:
    def test_slim_documents_use_browse_urls(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        _mock_search_issues(
            connector,
            [_issue_payload(), _issue_payload(key="HELP-2", issue_id="10002")],
        )

        batches = list(connector.retrieve_all_slim_docs())
        slim_docs = [doc for batch in batches for doc in batch]

        assert [doc.id for doc in slim_docs] == [
            f"{_JSM_BASE}/browse/{_ISSUE_KEY}",
            f"{_JSM_BASE}/browse/HELP-2",
        ]

    def test_perm_sync_slim_path_matches_plain_path(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        _mock_search_issues(connector, [_issue_payload()])

        plain = list(connector.retrieve_all_slim_docs())
        perm_sync = list(connector.retrieve_all_slim_docs_perm_sync())
        assert plain == perm_sync


def test_checkpoint_output_wrapper_streaming() -> None:
    """The generator-based checkpoint contract streams documents then the
    checkpoint as the StopIteration value."""
    checkpoint = JsmConnectorCheckpoint(has_more=False)
    document = Document(
        id="doc",
        sections=[],
        source=DocumentSource.JSM,
        semantic_identifier="doc",
        title="doc",
        doc_updated_at=None,
        metadata={},
    )

    def _generator() -> Any:
        yield document
        return checkpoint

    consumed: list[Any] = []
    for doc, _hierarchy, failure, next_checkpoint in CheckpointOutputWrapper[Any]()(
        _generator()
    ):
        consumed.extend(x for x in (doc, failure, next_checkpoint) if x is not None)

    assert document in consumed
    assert checkpoint in consumed
    assert json.dumps(checkpoint.model_dump(mode="json")) is not None
