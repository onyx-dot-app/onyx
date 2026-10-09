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
from onyx.utils.variable_functionality import global_version
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
    return {"values": [{"name": "Request a laptop"}], "isLastPage": True}


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
    # rest_api_version "2" (data center) keeps the mocked search_issues path;
    # the connector routes cloud clients through the enhanced search instead.
    mock._options = {"rest_api_version": "2"}
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

        search_issues_calls: list[dict[str, Any]] = []

        def search_issues_side_effect(
            jql_str: str,
            startAt: int,
            maxResults: int,  # noqa: ARG001
        ) -> list[MagicMock]:
            search_issues_calls.append({"jql_str": jql_str, "startAt": startAt})
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

        start, end = 1000, 2000
        outputs = load_everything_from_checkpoint_connector(connector, start, end)

        # Two batches: the first fills the page, the second is the tail.
        assert len(outputs) == 2
        documents = [
            item for out in outputs for item in out.items if isinstance(item, Document)
        ]
        assert len(documents) == 51
        final_checkpoint = outputs[-1].next_checkpoint
        assert final_checkpoint.has_more is False

        # every poll carries the start/end window it was handed (not an
        # unscoped epoch..tomorrow query) and pages by offset
        expected_time_jql = (
            f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
        )
        assert len(search_issues_calls) == 2
        for call in search_issues_calls:
            assert call["jql_str"] == expected_time_jql
        assert [call["startAt"] for call in search_issues_calls] == [0, 50]

    def test_checkpoint_bounds_are_passed_to_jql(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        """start/end must reach the JQL verbatim; a connector that ignores
        them would reindex the epoch..tomorrow window on every poll."""
        _mock_search_issues(connector, [])

        start, end = 1759000000.0, 1759100000.0
        list(
            connector.load_from_checkpoint(
                start, end, JsmConnectorCheckpoint(has_more=True)
            )
        )

        jql = connector._jira_client.search_issues.call_args.kwargs["jql_str"]
        assert jql == (
            f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
        )

    def test_checkpoint_round_trips_through_json(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        checkpoint = connector.build_dummy_checkpoint()
        checkpoint.oversized_issue_keys = ["HELP-9"]
        checkpoint.all_issue_ids = [["10001", "10002"]]
        checkpoint.cursor = "token-1"
        checkpoint.ids_done = False
        validated = connector.validate_checkpoint_json(checkpoint.model_dump_json())
        assert validated == checkpoint

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
        plain_ids = [doc.id for batch in plain for doc in batch]
        perm_sync_ids = [doc.id for batch in perm_sync for doc in batch]
        assert plain_ids == perm_sync_ids
        # without EE, permission resolution is a no-op on both paths
        assert all(
            doc.external_access is None for batch in perm_sync for doc in batch
        )

    def test_slim_path_skips_oversized_issues(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        """Tickets the full path drops for size must not show up as slim
        documents either, or permission sync treats them as indexed."""
        oversized = _issue_payload(key="HELP-BIG", issue_id="10003")
        oversized["fields"]["description"] = "x" * (200 * 1024)
        _mock_search_issues(
            connector,
            [_issue_payload(), oversized],
        )

        batches = list(connector.retrieve_all_slim_docs())
        slim_docs = [doc for batch in batches for doc in batch]

        assert [doc.id for doc in slim_docs] == [f"{_JSM_BASE}/browse/{_ISSUE_KEY}"]


class TestJsmConnectorServiceDeskScope:
    def test_service_desk_narrows_jql_to_its_project(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        """Selecting a desk must scope every search to that desk's project,
        not index every project the credential can access."""
        connector._jsm_session = build_jsm_session({"jira_api_token": "token"})
        connector._desk_project_key = "HELP"

        _mock_search_issues(connector, [_issue_payload()])
        list(
            connector.load_from_checkpoint(0, 10, JsmConnectorCheckpoint(has_more=True))
        )

        jql = connector._jira_client.search_issues.call_args.kwargs["jql_str"]
        assert jql.startswith("project = HELP AND updated >= ")

    def test_service_desk_resolution_is_cached(
        self, connector: JiraServiceManagementConnector
    ) -> None:
        connector._jsm_session = build_jsm_session({"jira_api_token": "token"})
        connector._desk_project_key = "HELP"

        _mock_search_issues(connector, [_issue_payload(), _issue_payload()])
        list(
            connector.load_from_checkpoint(0, 10, JsmConnectorCheckpoint(has_more=True))
        )
        list(
            connector.load_from_checkpoint(0, 10, JsmConnectorCheckpoint(has_more=True))
        )

        # both polls ran; the desk->project lookup is cached on the instance
        assert connector._jira_client.search_issues.call_count == 2
        for call in connector._jira_client.search_issues.call_args_list:
            assert call.kwargs["jql_str"].startswith("project = HELP AND ")


class TestJsmConnectorPermSync:
    def test_perm_sync_populates_external_access(
        self,
        connector: JiraServiceManagementConnector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """load_from_checkpoint_with_perm_sync must attach the Jira project's
        external_access to every document, like the Jira connector does."""
        from onyx.access.models import ExternalAccess

        was_ee = global_version.is_ee_version()
        global_version.set_ee()
        try:
            monkeypatch.setattr(
                "ee.onyx.external_permissions.jira.page_access."
                "get_project_permissions",
                lambda jira_client, jira_project, add_prefix=False: ExternalAccess(
                    external_user_emails=set(),
                    external_user_group_ids={"jira-administrators"},
                    is_public=False,
                ),
            )
            from onyx.utils.variable_functionality import fetch_versioned_implementation

            fetch_versioned_implementation.cache_clear()

            _mock_search_issues(connector, [_issue_payload()])
            outputs = list(
                connector.load_from_checkpoint_with_perm_sync(
                    0, 10, JsmConnectorCheckpoint(has_more=True)
                )
            )

            documents = [item for item in outputs if isinstance(item, Document)]
            assert len(documents) == 1
            external_access = documents[0].external_access
            assert external_access is not None
            assert external_access.external_user_group_ids == {"jira-administrators"}
        finally:
            if not was_ee:
                global_version.unset_ee()
            fetch_versioned_implementation.cache_clear()


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
