from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import ConnectorRunner
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import JiraApiError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

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
    description: Any = "The printer on floor 2 is offline.",
    labels: list[str] | None = None,
    updated: str = "2023-01-01T12:00:00.000+0000",
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "key": key,
        "fields": {
            "summary": summary,
            "updated": updated,
            "created": "2023-01-01T12:00:00.000+0000",
            "description": description,
            "labels": labels or [],
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
    project_key: str | None = "TEST",
    **kwargs: Any,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=BASE, project_key=project_key, **kwargs
    )
    connector._service_desk_base_url = BASE
    connector._session = cast(Any, _Session(responses or [_desk_page()]))
    operations = MagicMock()
    operations.search_issue_ids.side_effect = list(
        search_pages or [JiraIssueIdPage(issue_ids=[], next_page_token=None)]
    )
    operations.bulk_fetch_issues.side_effect = lambda issue_ids, **_: [
        issues[issue_id] for issue_id in issue_ids if issues and issue_id in issues
    ]
    connector._source_operations = operations
    return connector


def _document_ids(
    batches: Iterable[list[Document | HierarchyNode]],
) -> list[str]:
    return [doc.id for batch in batches for doc in batch if isinstance(doc, Document)]


def _slim_ids(
    batches: Iterable[list[SlimDocument | HierarchyNode]],
) -> list[str]:
    return [
        doc.id for batch in batches for doc in batch if isinstance(doc, SlimDocument)
    ]


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


class _Heartbeat(IndexingHeartbeatInterface):
    """Records keep-alives and can request a stop on a chosen check."""

    def __init__(self, stop_after: int | None = None) -> None:
        self._stop_after = stop_after
        self.progress_calls: list[tuple[str, int]] = []
        self.should_stop_calls = 0

    def should_stop(self) -> bool:
        self.should_stop_calls += 1
        return (
            self._stop_after is not None and self.should_stop_calls >= self._stop_after
        )

    def progress(self, tag: str, amount: int) -> None:
        self.progress_calls.append((tag, amount))


def test_load_indexes_every_project_ticket_and_marks_source() -> None:
    connector = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )

    batches = list(connector.load_from_state())

    assert len(batches) == 1
    document = batches[0][0]
    assert isinstance(document, Document)
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

    documents = _document_ids(connector.load_from_state())

    assert documents == [
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

    with pytest.raises(ConnectorValidationError, match="cannot see the configured"):
        connector.validate_connector_settings()


def test_poll_uses_the_updated_window_and_the_same_project_scope() -> None:
    connector = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )

    batches = list(connector.poll_source(1_700_000_000, 1_700_003_600))

    assert len(batches) == 1
    polled = batches[0][0]
    assert isinstance(polled, Document)
    assert polled.source is DocumentSource.JIRA_SERVICE_MANAGEMENT
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

    loaded = _document_ids(load_connector.load_from_state())
    slimmed = _slim_ids(slim_connector.retrieve_all_slim_docs())

    assert slimmed == loaded == [f"{BASE}/browse/TEST-100"]
    assert (
        _operations(slim_connector).search_issue_ids.call_args.kwargs["jql"]
        == _operations(load_connector).search_issue_ids.call_args.kwargs["jql"]
    )


def test_runner_polls_only_the_window_and_matches_pruning_membership() -> None:
    issues = {
        "100": _issue("100", "TEST-100"),
        "101": _issue("101", "TEST-101", updated="2024-01-01T12:00:00.000+0000"),
        "102": _issue("102", "TEST-102", labels=["skip-me"]),
    }

    def by_window(jql: str, **_: Any) -> JiraIssueIdPage:
        ids = ["100", "102"] if "updated >=" in jql else ["100", "101", "102"]
        return JiraIssueIdPage(issue_ids=ids, next_page_token=None)

    index_connector = _connector(
        [_desk_page()], issues=issues, search_pages=[], labels_to_skip=["skip-me"]
    )
    _operations(index_connector).search_issue_ids.side_effect = by_window
    runner = ConnectorRunner(
        index_connector,
        batch_size=100,
        include_permissions=False,
        time_range=(
            datetime(2023, 1, 1, tzinfo=timezone.utc),
            datetime(2023, 1, 2, tzinfo=timezone.utc),
        ),
    )
    indexed: list[str] = []
    for docs, _nodes, failure, _checkpoint in runner.run(
        index_connector.build_dummy_checkpoint()
    ):
        assert failure is None
        indexed.extend(doc.id for doc in docs or [])

    load_connector = _connector(
        [_desk_page()], issues=issues, search_pages=[], labels_to_skip=["skip-me"]
    )
    _operations(load_connector).search_issue_ids.side_effect = by_window
    loaded = _document_ids(load_connector.load_from_state())
    slim_connector = _connector(
        [_desk_page()], issues=issues, search_pages=[], labels_to_skip=["skip-me"]
    )
    _operations(slim_connector).search_issue_ids.side_effect = by_window
    slimmed = _slim_ids(slim_connector.retrieve_all_slim_docs())

    assert indexed == [f"{BASE}/browse/TEST-100"]
    assert (
        set(loaded)
        == set(slimmed)
        == {
            f"{BASE}/browse/TEST-100",
            f"{BASE}/browse/TEST-101",
        }
    )
    assert set(indexed).issubset(loaded)
    poll_jql = _operations(index_connector).search_issue_ids.call_args.kwargs["jql"]
    assert "updated >= 1672531200000" in poll_jql
    assert "updated <= 1672617600000" in poll_jql


def test_poll_follows_the_search_cursor() -> None:
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

    polled = _document_ids(connector.poll_source(1_700_000_000, 1_700_003_600))

    assert polled == [
        f"{BASE}/browse/TEST-100",
        f"{BASE}/browse/TEST-101",
    ]
    assert (
        _operations(connector)
        .search_issue_ids.call_args_list[1]
        .kwargs["next_page_token"]
        == "next"
    )


def test_slim_reports_progress_and_stops_cleanly() -> None:
    heartbeat = _Heartbeat()
    connector = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )

    assert _slim_ids(connector.retrieve_all_slim_docs(callback=heartbeat)) == [
        f"{BASE}/browse/TEST-100"
    ]
    assert heartbeat.progress_calls
    assert heartbeat.should_stop_calls >= 1

    stopping = _Heartbeat(stop_after=1)
    stopped_connector = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )
    with pytest.raises(RuntimeError, match="stopped by heartbeat"):
        list(stopped_connector.retrieve_all_slim_docs(callback=stopping))
    assert stopping.should_stop_calls == 1


def test_pruning_helper_forwards_the_heartbeat_to_the_slim_path() -> None:
    issue_ids = [str(1000 + i) for i in range(201)]
    # Every issue is skipped, so the connector fetches all three batches without
    # yielding one. That is the path where only its own callback can stop it.
    issues = {
        issue_id: _issue(issue_id, f"TEST-{issue_id}", labels=["skip-me"])
        for issue_id in issue_ids
    }
    heartbeat = _Heartbeat(stop_after=2)
    connector = _connector(
        [_desk_page()],
        issues=issues,
        search_pages=[JiraIssueIdPage(issue_ids=issue_ids, next_page_token=None)],
        labels_to_skip=["skip-me"],
    )

    with pytest.raises(RuntimeError, match="stopped by heartbeat"):
        extract_ids_from_runnable_connector(connector, callback=heartbeat)

    assert heartbeat.should_stop_calls == 2
    assert _operations(connector).bulk_fetch_issues.call_count == 1


def test_load_poll_and_slim_have_the_same_membership() -> None:
    issues = {
        "100": _issue("100", "TEST-100"),
        "101": _issue("101", "TEST-101"),
        "102": _issue("102", "TEST-102", labels=["skip-me"]),
    }
    issue_ids = ["100", "101", "102"]

    def all_issues(jql: str, **_: Any) -> JiraIssueIdPage:
        assert 'project in ("TEST")' in jql
        return JiraIssueIdPage(issue_ids=issue_ids, next_page_token=None)

    load_connector = _connector(
        [_desk_page()], issues=issues, search_pages=[], labels_to_skip=["skip-me"]
    )
    poll_connector = _connector(
        [_desk_page()], issues=issues, search_pages=[], labels_to_skip=["skip-me"]
    )
    slim_connector = _connector(
        [_desk_page()], issues=issues, search_pages=[], labels_to_skip=["skip-me"]
    )
    for connector in (load_connector, poll_connector, slim_connector):
        _operations(connector).search_issue_ids.side_effect = all_issues

    loaded = _document_ids(load_connector.load_from_state())
    polled = _document_ids(poll_connector.poll_source(0, 1_700_100_000))
    slimmed = _slim_ids(slim_connector.retrieve_all_slim_docs())

    expected = {f"{BASE}/browse/TEST-100", f"{BASE}/browse/TEST-101"}
    assert set(loaded) == set(polled) == set(slimmed) == expected


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
    pruned = _slim_ids(prune_connector.retrieve_all_slim_docs())

    assert indexed == pruned == [f"{BASE}/browse/TEST-100"]


def test_slim_omits_the_tickets_that_indexing_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.connectors.jira.connector.JIRA_CONNECTOR_MAX_TICKET_SIZE", 50
    )
    issues = {
        "100": _issue("100", "TEST-100"),
        "101": _issue("101", "TEST-101", labels=["skip-me"]),
        "102": _issue("102", "TEST-102", description="x" * 200),
    }
    load_connector = _connector(
        [_desk_page()],
        issues=issues,
        search_pages=[
            JiraIssueIdPage(issue_ids=["100", "101", "102"], next_page_token=None)
        ],
        labels_to_skip=["skip-me"],
    )
    slim_connector = _connector(
        [_desk_page()],
        issues=issues,
        search_pages=[
            JiraIssueIdPage(issue_ids=["100", "101", "102"], next_page_token=None)
        ],
        labels_to_skip=["skip-me"],
    )

    loaded = _document_ids(load_connector.load_from_state())
    slimmed = _slim_ids(slim_connector.retrieve_all_slim_docs())

    assert loaded == slimmed == [f"{BASE}/browse/TEST-100"]


def test_slim_skips_a_label_before_parsing_malformed_content() -> None:
    """An excluded ticket must not abort the slim listing while parsing."""
    issues = {
        "100": _issue(
            "100",
            "TEST-100",
            labels=["skip-me"],
            description={"type": "doc", "content": None},
        )
    }
    connector = _connector(
        [_desk_page()],
        issues=issues,
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
        labels_to_skip=["skip-me"],
    )

    assert _slim_ids(connector.retrieve_all_slim_docs()) == []


def test_every_configured_desk_must_resolve() -> None:
    connector = _connector([_desk_page()], service_desk_ids=["1", "9"])

    with pytest.raises(ConnectorValidationError, match="9"):
        connector.validate_connector_settings()


def test_blank_service_desk_ids_mean_everything() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=BASE, service_desk_ids=["", " "]
    )
    assert connector.service_desk_ids is None

    indexing = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
        project_key=None,
        service_desk_ids=[""],
    )
    assert _document_ids(indexing.load_from_state()) == [f"{BASE}/browse/TEST-100"]


def test_desk_discovery_follows_pages_and_honors_explicit_desk() -> None:
    connector = _connector(
        [
            _Response(
                200,
                {
                    "values": [{"id": "1", "projectKey": "AAA"}],
                    "isLastPage": False,
                },
            ),
            _Response(
                200,
                {
                    "values": [{"id": "2", "projectKey": "BBB"}],
                    "isLastPage": True,
                },
            ),
        ],
        issues={"200": _issue("200", "BBB-200", project_key="BBB")},
        search_pages=[JiraIssueIdPage(issue_ids=["200"], next_page_token=None)],
        project_key=None,
        service_desk_ids=["2"],
    )

    assert _document_ids(connector.load_from_state()) == [f"{BASE}/browse/BBB-200"]
    session = cast(Any, connector._session)
    assert session.calls[1]["params"]["start"] == 1
    assert (
        _operations(connector).search_issue_ids.call_args.kwargs["jql"]
        == 'project in ("BBB")'
    )


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"values": "not-a-list", "isLastPage": True}, "invalid page"),
        (
            {"values": [], "isLastPage": False},
            "empty page without a completion marker",
        ),
        (
            {
                "values": [
                    {"id": "1", "projectKey": "TEST"},
                    {"id": "1", "projectKey": "TEST"},
                ],
                "isLastPage": True,
            },
            "repeated a service desk",
        ),
        (
            {"values": [{"projectKey": "TEST"}], "isLastPage": True},
            "without an id",
        ),
    ],
)
def test_desk_discovery_rejects_malformed_pages(
    payload: dict[str, Any], match: str
) -> None:
    connector = _connector([_Response(200, payload)], project_key=None)

    with pytest.raises(UnexpectedValidationError, match=match):
        list(connector.load_from_state())


def test_desk_discovery_requires_a_project_key() -> None:
    connector = _connector(
        [_Response(200, {"values": [{"id": "1"}], "isLastPage": True})],
        project_key=None,
        service_desk_ids=["1"],
    )

    with pytest.raises(UnexpectedValidationError, match="without a project key"):
        list(connector.load_from_state())


def test_desk_discovery_rejects_an_empty_scope() -> None:
    connector = _connector(
        [_Response(200, {"values": [], "isLastPage": True})], project_key=None
    )

    with pytest.raises(ConnectorValidationError, match="service desk is visible"):
        list(connector.load_from_state())


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (403, InsufficientPermissionsError),
        (429, RateLimitedValidationError),
    ],
)
def test_desk_discovery_maps_http_errors(status: int, error: type[Exception]) -> None:
    connector = _connector([_Response(status)], project_key=None)

    with pytest.raises(error):
        list(connector.load_from_state())


VALIDATION_STATUS_ERRORS = [
    (401, CredentialExpiredError),
    (403, InsufficientPermissionsError),
    (404, ConnectorValidationError),
    (429, RateLimitedValidationError),
]


@pytest.mark.parametrize(("status", "error_type"), VALIDATION_STATUS_ERRORS)
def test_validation_maps_search_errors(
    status: int, error_type: type[Exception]
) -> None:
    connector = _connector([_desk_page()])
    _operations(connector).search_issue_ids.side_effect = JiraApiError(
        "search failed", status_code=status, method="GET"
    )

    with pytest.raises(error_type):
        connector.validate_connector_settings()


@pytest.mark.parametrize(("status", "error_type"), VALIDATION_STATUS_ERRORS)
def test_validation_maps_bulk_fetch_errors(
    status: int, error_type: type[Exception]
) -> None:
    connector = _connector(
        [_desk_page()],
        search_pages=[JiraIssueIdPage(issue_ids=["100"], next_page_token=None)],
    )
    _operations(connector).bulk_fetch_issues.side_effect = JiraApiError(
        "bulk fetch failed", status_code=status, method="POST"
    )

    with pytest.raises(error_type):
        connector.validate_connector_settings()


def test_validation_checks_bulk_fetch_when_the_scope_is_empty() -> None:
    connector = _connector(
        [_desk_page()],
        issues={"100": _issue("100", "TEST-100")},
        search_pages=[
            JiraIssueIdPage(issue_ids=[], next_page_token=None),
            JiraIssueIdPage(issue_ids=["100"], next_page_token=None),
        ],
    )

    connector.validate_connector_settings()

    searches = _operations(connector).search_issue_ids.call_args_list
    assert searches[1].kwargs["jql"] == "created >= 1970-01-01"
    bulk = _operations(connector).bulk_fetch_issues.call_args
    assert bulk.kwargs["issue_ids"] == ["100"]


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
