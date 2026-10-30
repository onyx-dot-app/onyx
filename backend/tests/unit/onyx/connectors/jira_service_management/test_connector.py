from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import ConnectorRunner
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    UnexpectedValidationError,
)
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError

BASE = "https://example.atlassian.net"


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _Session:
    """Hands out the queued responses and records the requested pages."""

    def __init__(self, responses: list[_Response]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.auth: Any = None
        self.headers: dict[str, str] = {}

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
        allow_redirects: bool = False,
    ) -> _Response:
        del timeout, allow_redirects
        self.calls.append({"url": url, "params": params})
        if not self._responses:
            raise AssertionError(f"Unexpected request: {url} {params}")
        return self._responses.pop(0)


def _issue(
    issue_id: str,
    key: str,
    project_key: str = "TEST",
    summary: str = "Printer is down",
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "key": key,
        "fields": {
            "summary": summary,
            "updated": "2023-01-01T12:00:00.000+0000",
            "created": "2023-01-01T12:00:00.000+0000",
            "description": "The printer on floor 2 is offline.",
            "labels": [],
            "reporter": {
                "displayName": "Test Creator",
                "emailAddress": "creator@example.com",
            },
            "assignee": {
                "displayName": "Test Assignee",
                "emailAddress": "assignee@example.com",
            },
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            "resolution": None,
            "project": {"key": project_key, "name": "Test Project"},
            "issuetype": {"name": "Service request"},
            "parent": None,
            "comment": {"comments": []},
        },
    }


def _connector(
    responses: list[_Response] | None = None,
    issues: dict[str, dict[str, Any]] | None = None,
    search_pages: list[JiraIssueIdPage] | None = None,
    **kwargs: Any,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=BASE, project_key="TEST", **kwargs
    )
    connector._service_desk_base_url = BASE
    connector._session = _Session(responses or [_desk_page()])
    operations = MagicMock()
    operations.search_issue_ids.side_effect = list(
        search_pages or [JiraIssueIdPage(issue_ids=[], next_page_token=None)]
    )
    operations.bulk_fetch_issues.side_effect = lambda issue_ids, **_: [
        issues[issue_id] for issue_id in issue_ids if issues and issue_id in issues
    ]
    connector._source_operations = operations
    return connector


def _operations(connector: JiraServiceManagementConnector) -> Any:
    assert connector._source_operations is not None
    return cast(Any, connector._source_operations)


def _desk_page(is_last: bool = True) -> _Response:
    return _Response(
        200,
        {
            "values": [{"id": "1", "projectKey": "TEST", "projectName": "Support"}],
            "isLastPage": is_last,
        },
    )


def test_load_indexes_every_project_ticket_and_marks_source() -> None:
    connector = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )

    batches = list(connector.load_from_state())

    assert len(batches) == 1
    document = batches[0][0]
    assert document.source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.id == f"{BASE}/browse/TEST-100"
    assert document.metadata["jsm_service_desk_id"] == "1"
    assert "Printer is down" in document.semantic_identifier
    assert _operations(connector).bulk_fetch_issues.call_args.kwargs["raise_on_missing"]


def test_load_follows_the_search_cursor() -> None:
    connector = _connector(
        [_desk_page()],
        issues={
            "100": _issue("100", "TEST-100"),
            "101": _issue("101", "TEST-101"),
        },
        search_pages=[
            JiraIssueIdPage(issue_ids=["100"], next_page_token="next"),
            JiraIssueIdPage(issue_ids=["101"], next_page_token=None),
        ],
    )

    documents = [doc for batch in connector.load_from_state() for doc in batch]

    assert [doc.id for doc in documents] == [
        f"{BASE}/browse/TEST-100",
        f"{BASE}/browse/TEST-101",
    ]
    assert (
        _operations(connector)
        .search_issue_ids.call_args_list[1]
        .kwargs["next_page_token"]
        == "next"
    )


def test_validation_checks_desk_jira_search_and_issue_fetch() -> None:
    connector = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )

    connector.validate_connector_settings()

    call = _operations(connector).search_issue_ids.call_args
    assert call.kwargs["jql"] == 'project in ("TEST")'
    assert call.kwargs["max_results"] == 1
    assert call.kwargs["fast"] is True
    bulk = _operations(connector).bulk_fetch_issues.call_args
    assert bulk.kwargs["issue_ids"] == ["100"]
    assert bulk.kwargs["fast"] is True


def test_validation_rejects_a_configured_desk_that_is_not_visible() -> None:
    connector = _connector(service_desk_ids=["9"])

    with pytest.raises(ConnectorValidationError, match="No Jira Service Management"):
        connector.validate_connector_settings()


def test_poll_uses_the_updated_window_and_the_same_project_scope() -> None:
    connector = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )

    batches = list(connector.poll_source(1_700_000_000, 1_700_003_600))

    assert len(batches) == 1
    assert batches[0][0].source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    jql = _operations(connector).search_issue_ids.call_args.kwargs["jql"]
    assert 'project in ("TEST")' in jql
    assert "updated >= 1700000000000" in jql
    assert "updated <= 1700003600000" in jql


def test_slim_uses_the_same_scope_and_ids_as_load() -> None:
    issues = {"100": _issue("100", "TEST-100")}
    load_connector = _connector(
        [_desk_page()],
        issues=issues,
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )
    slim_connector = _connector(
        [_desk_page()],
        issues=issues,
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )

    loaded = [doc.id for batch in load_connector.load_from_state() for doc in batch]
    slimmed = [
        doc.id for batch in slim_connector.retrieve_all_slim_docs() for doc in batch
    ]

    assert slimmed == loaded == [f"{BASE}/browse/TEST-100"]
    assert (
        _operations(slim_connector).search_issue_ids.call_args.kwargs["jql"]
        == _operations(load_connector).search_issue_ids.call_args.kwargs["jql"]
    )


def test_runner_and_pruning_use_the_same_membership() -> None:
    issues = {"100": _issue("100", "TEST-100")}
    index_connector = _connector(
        [_desk_page()],
        issues=issues,
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )
    runner = ConnectorRunner(
        index_connector,
        batch_size=100,
        include_permissions=False,
        time_range=(
            datetime.fromtimestamp(0, tz=timezone.utc),
            datetime.fromtimestamp(1_700_100_000, tz=timezone.utc),
        ),
    )

    indexed: list[str] = []
    for docs, _nodes, failure, _checkpoint in runner.run(
        index_connector.build_dummy_checkpoint()
    ):
        assert failure is None
        indexed.extend(doc.id for doc in docs or [])

    prune_connector = _connector(
        [_desk_page()],
        issues=issues,
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )
    pruned = [
        doc.id for batch in prune_connector.retrieve_all_slim_docs() for doc in batch
    ]

    assert indexed == pruned == [f"{BASE}/browse/TEST-100"]


def test_a_missing_bulk_issue_is_an_error() -> None:
    connector = _connector(
        [_desk_page()],
        issues={},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )

    with pytest.raises(UnexpectedValidationError, match="no ticket for 1 of 1"):
        list(connector.load_from_state())


def test_a_repeated_search_cursor_is_an_error() -> None:
    connector = _connector(
        [_desk_page()],
        search_pages=[
            JiraIssueIdPage(issue_ids=["100"], next_page_token="same"),
            JiraIssueIdPage(issue_ids=["101"], next_page_token="same"),
        ],
    )

    with pytest.raises(UnexpectedValidationError, match="repeated its search cursor"):
        list(connector.load_from_state())


def test_401_is_reported_as_an_expired_credential() -> None:
    connector = _connector([_Response(401)])

    with pytest.raises(CredentialExpiredError):
        list(connector.load_from_state())


def test_cloud_credentials_use_basic_auth_and_the_site_url() -> None:
    connector = JiraServiceManagementConnector(jira_base_url=BASE)

    connector.load_credentials(
        {"jira_user_email": "user@example.com", "jira_api_token": "token"}
    )

    assert connector._session.auth == ("user@example.com", "token")
    assert connector._service_desk_base_url == BASE


def test_a_scoped_token_uses_the_atlassian_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector.scoped_url",
        lambda _, product: f"https://api.atlassian.com/ex/{product}/cloud",
    )
    connector = JiraServiceManagementConnector(jira_base_url=BASE, scoped_token=True)

    connector.load_credentials(
        {"jira_user_email": "user@example.com", "jira_api_token": "token"}
    )

    assert connector._service_desk_base_url == (
        "https://api.atlassian.com/ex/jira/cloud"
    )


def test_data_center_credentials_are_rejected() -> None:
    connector = JiraServiceManagementConnector(jira_base_url=BASE)

    with pytest.raises(ConnectorValidationError, match="Cloud credential"):
        connector.load_credentials({"jira_api_token": "token"})


def test_a_missing_api_token_is_a_missing_credential() -> None:
    connector = JiraServiceManagementConnector(jira_base_url=BASE)

    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({"jira_user_email": "user@example.com"})
