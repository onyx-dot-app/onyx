import json
import unittest
from collections.abc import Iterator
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    JSMResourceNotFoundError,
    _format_sla_metrics,
    _parse_jsm_datetime,
    _render_request_field_values,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


def _mock_response(
    status_code: int,
    json_body: dict[str, Any] | list[Any],
    url: str = "https://acme.atlassian.net",
) -> requests.Response:
    """Return a real requests.Response with the supplied status code and encoded JSON body."""
    resp = requests.Response()
    resp.status_code = status_code
    resp.url = url
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body).encode("utf-8")
    return resp


class TestJiraServiceManagementConnector(unittest.TestCase):
    def test_registry_mapping_and_config(self) -> None:
        self.assertIn(DocumentSource.JIRA_SERVICE_MANAGEMENT, CONNECTOR_CLASS_MAP)
        mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
        self.assertEqual(
            mapping.module_path,
            "onyx.connectors.jira_service_management.connector",
        )
        self.assertEqual(mapping.class_name, "JiraServiceManagementConnector")
        self.assertEqual(
            mapping.config_class,
            JiraServiceManagementConnectorConfig,
        )

        config = JiraServiceManagementConnectorConfig(
            service_desk_ids=["10", "20"],
            project_key="ITSM",
            include_internal_comments=False,
            batch_size=25,
        )
        self.assertEqual(config.service_desk_ids, ["10", "20"])
        self.assertEqual(config.project_key, "ITSM")
        self.assertFalse(config.include_internal_comments)
        self.assertEqual(config.batch_size, 25)

    def test_https_validation_and_credential_loading(self) -> None:
        connector = JiraServiceManagementConnector()

        # Reject unencrypted HTTP URL
        with self.assertRaises(ConnectorValidationError):
            connector.load_credentials(
                {
                    "jsm_base_url": "http://insecure-jira.example.com",
                    "jsm_user_email": "admin@example.com",
                    "jsm_api_token": "token123",
                }
            )

        # Allow HTTPS
        connector.load_credentials(
            {
                "jsm_base_url": "https://secure-jira.example.com/",
                "jsm_user_email": "admin@example.com",
                "jsm_api_token": "token123",
            }
        )
        self.assertEqual(connector.base_url, "https://secure-jira.example.com")
        self.assertEqual(connector.user_email, "admin@example.com")
        self.assertEqual(connector.api_token, "token123")

        # Allow localhost HTTP for local testing
        connector.load_credentials(
            {
                "jsm_base_url": "http://localhost:8080",
                "jsm_bearer_token": "pat_abc",
            }
        )
        self.assertEqual(connector.base_url, "http://localhost:8080")
        self.assertEqual(connector.bearer_token, "pat_abc")

    def test_missing_credentials_raises(self) -> None:
        connector = JiraServiceManagementConnector()
        with self.assertRaises(ConnectorMissingCredentialError):
            connector.load_credentials({})

        with self.assertRaises(ConnectorMissingCredentialError):
            connector.load_credentials({"jsm_base_url": "https://acme.atlassian.net"})

    def test_parse_jsm_datetime_formats(self) -> None:
        self.assertIsNone(_parse_jsm_datetime(None))
        self.assertIsNone(_parse_jsm_datetime(""))

        # dict with epochMillis
        dt1 = _parse_jsm_datetime({"epochMillis": 1704067200000})
        self.assertIsNotNone(dt1)
        assert dt1 is not None
        self.assertEqual(dt1.year, 2024)
        self.assertEqual(dt1.tzinfo, timezone.utc)

        # ISO string ending in Z
        dt2 = _parse_jsm_datetime("2024-01-01T12:00:00.000Z")
        self.assertIsNotNone(dt2)
        assert dt2 is not None
        self.assertEqual(dt2.hour, 12)
        self.assertEqual(dt2.tzinfo, timezone.utc)

        # ISO string with 4-digit offset (+0200)
        dt3 = _parse_jsm_datetime("2024-01-01T14:00:00.000+0200")
        self.assertIsNotNone(dt3)
        assert dt3 is not None
        self.assertEqual(dt3.utcoffset(), timezone.utc.utcoffset(None))

    def test_field_rendering_and_sla_formatting_helpers(self) -> None:
        field_values = [
            {"fieldId": "summary", "label": "Summary", "value": "Server outage"},
            {
                "fieldId": "description",
                "label": "Description",
                "renderedValue": {"html": "<p>Critical database down</p>"},
            },
            {
                "fieldId": "custom_component",
                "label": "Component",
                "value": {"name": "Postgres Cluster"},
            },
            {
                "fieldId": "impacted_teams",
                "label": "Impacted Teams",
                "value": [{"name": "Checkout"}, {"name": "Billing"}],
            },
        ]
        summary, field_lines = _render_request_field_values(field_values, "DEFAULT")
        self.assertEqual(summary, "Server outage")
        self.assertIn("Description: <p>Critical database down</p>", field_lines)
        self.assertIn("Component: Postgres Cluster", field_lines)
        self.assertIn("Impacted Teams: Checkout, Billing", field_lines)

        slas = [
            {
                "name": "Time to first response",
                "ongoingCycle": {"breached": False},
            },
            {
                "name": "Time to resolution",
                "completedCycles": [{"breached": True}],
            },
        ]
        sla_lines = _format_sla_metrics(slas)
        self.assertEqual(
            sla_lines,
            [
                "Time to first response: ongoing (breached=False)",
                "Time to resolution: completed (breached=True)",
            ],
        )

    @patch("onyx.connectors.jira_service_management.connector.requests.Session.get")
    def test_paginate_respects_is_last_page_boolean(self, mock_get: MagicMock) -> None:
        connector = JiraServiceManagementConnector()
        connector.load_credentials(
            {
                "jsm_base_url": "https://acme.atlassian.net",
                "jsm_bearer_token": "pat-token",
            }
        )

        # Even if page has fewer items than _JSM_PAGE_LIMIT, continue if isLastPage is false
        calls = []

        def side_effect(_url: str, **kwargs: Any) -> requests.Response:
            start = kwargs.get("params", {}).get("start", 0)
            calls.append(start)
            if start == 0:
                # Page 1: returns 2 items, but isLastPage is explicitly False
                return _mock_response(
                    200,
                    {"values": [{"id": 1}, {"id": 2}], "isLastPage": False},
                )
            # Page 2: returns 1 item, isLastPage is True
            return _mock_response(
                200,
                {"values": [{"id": 3}], "isLastPage": True},
            )

        mock_get.side_effect = side_effect
        items = list(connector._paginate("servicedesk"))
        self.assertEqual(len(items), 3)
        self.assertEqual(calls, [0, 2])


DESK = {"id": "10", "projectKey": "ITSM", "projectName": "IT Service Desk"}
FIELDS = [
    {"id": "summary", "name": "Summary"},
    {"id": "description", "name": "Description"},
    {
        "id": "customfield_10001",
        "name": "Request Type",
        "schema": {"custom": "com.atlassian.servicedesk:vp-origin"},
    },
    {
        "id": "customfield_10002",
        "name": "Time to resolution",
        "schema": {"custom": "com.atlassian.servicedesk:sd-sla-field"},
    },
    {"id": "customfield_10003", "name": "Impact"},
]
START = datetime(2026, 10, 25, 12, tzinfo=timezone.utc).timestamp()
END = START + 3600


def issue(number: int = 1, *, customer_request: bool = True) -> dict[str, Any]:
    return {
        "id": str(number),
        "key": f"ITSM-{number}",
        "fields": {
            "project": {"key": "ITSM"},
            "created": "2026-10-01T10:00:00Z",
            "updated": "2026-10-25T12:30:00Z",
            "summary": "New summary",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "New description"}],
                    }
                ],
            },
            "customfield_10001": {"requestType": {"id": "5"}}
            if customer_request
            else None,
            "customfield_10002": None,
            "customfield_10003": "Updated custom field",
            "status": {"name": "Open", "statusCategory": {"name": "In Progress"}},
        },
    }


@pytest.fixture
def connector() -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(project_key="ITSM")
    connector.load_credentials(
        {
            "jsm_base_url": "https://acme.atlassian.net",
            "jsm_user_email": "agent@example.com",
            "jsm_api_token": "test-token",
        }
    )
    return connector


@pytest.fixture
def responses(connector: JiraServiceManagementConnector) -> Iterator[MagicMock]:
    def get(path: str, params: Any = None, *, jira_api: bool = False) -> dict[str, Any]:
        assert params is None or isinstance(params, dict)
        if path == "servicedesk":
            return {"values": [deepcopy(DESK)], "isLastPage": True}
        if path == "servicedesk/10/queue":
            return {"values": []}
        if path == "field":
            assert jira_api
            return {"values": deepcopy(FIELDS)}
        if path.startswith("request/") and path.endswith("/comment"):
            return {
                "values": [
                    {"id": "public-1", "body": "Public comment", "public": True},
                    {"id": "internal-1", "body": "Internal secret", "public": False},
                ],
                "isLastPage": True,
            }
        raise AssertionError(f"Unexpected API path: {path}")

    with patch.object(connector, "_api_get", side_effect=get) as mock:
        yield mock


def documents(batches: Any) -> list[Document]:
    return [doc for batch in batches for doc in batch]


def test_secure_defaults_and_explicit_opt_in() -> None:
    assert JiraServiceManagementConnectorConfig().include_internal_comments is False
    assert JiraServiceManagementConnector().include_internal_comments is False
    assert (
        JiraServiceManagementConnector(
            include_internal_comments=True
        ).include_internal_comments
        is True
    )


@pytest.mark.parametrize("visibility", [None, "true", "false", 1, 0, {}, []])
@pytest.mark.parametrize("opt_in", [False, True])
def test_unknown_comment_visibility_never_reaches_documents(
    connector: JiraServiceManagementConnector, visibility: Any, opt_in: bool
) -> None:
    connector.include_internal_comments = opt_in
    comment = {
        "body": "must not leak",
        "public": visibility,
        "author": {"emailAddress": "hidden@example.com"},
    }
    with patch.object(connector, "_paginate", return_value=iter([comment])):
        assert connector._fetch_request_comments("ITSM-1") == []
    doc = connector._convert_request_to_document(
        {"issueKey": "ITSM-1"}, DESK, [comment], []
    )
    assert "must not leak" not in "\n".join(s.text or "" for s in doc.sections)
    assert doc.secondary_owners is None


def test_missing_visibility_and_explicit_internal_opt_in(
    connector: JiraServiceManagementConnector,
) -> None:
    comments = [
        {"body": "unknown"},
        {"body": "public", "public": True},
        {"body": "internal", "public": False},
    ]
    with patch.object(
        connector, "_paginate", side_effect=lambda *_args: iter(comments)
    ):
        assert [c["body"] for c in connector._fetch_request_comments("ITSM-1")] == [
            "public"
        ]
        connector.include_internal_comments = True
        assert [c["body"] for c in connector._fetch_request_comments("ITSM-1")] == [
            "public",
            "internal",
        ]


@pytest.mark.parametrize(
    "credentials",
    [
        {},
        {"jsm_user_email": "agent@example.com"},
        {"jsm_api_token": "token"},
        {"jsm_bearer_token": "   "},
        {"jsm_user_email": "  ", "jsm_api_token": " "},
        {"jsm_bearer_token": "token", "jsm_user_email": "agent@example.com"},
        {"jsm_bearer_token": "token", "jsm_api_token": "partial"},
        {"jsm_bearer_token": 123},
    ],
)
def test_reject_partial_or_blank_authentication(credentials: dict[str, Any]) -> None:
    with pytest.raises((ConnectorValidationError, ConnectorMissingCredentialError)):
        JiraServiceManagementConnector().load_credentials(
            {"jsm_base_url": "https://acme.atlassian.net", **credentials}
        )


@pytest.mark.parametrize(
    "credentials",
    [
        {"jsm_user_email": " agent@example.com ", "jsm_api_token": " token "},
        {"jsm_bearer_token": " token "},
    ],
)
def test_valid_authentication_is_trimmed(credentials: dict[str, Any]) -> None:
    c = JiraServiceManagementConnector()
    c.load_credentials({"jsm_base_url": "https://acme.atlassian.net", **credentials})
    assert (c.bearer_token or c.api_token) == "token"


@pytest.mark.parametrize(
    "url",
    [
        "https:///",
        "https://user:secret@acme.atlassian.net",
        "ftp://localhost",
        "http://remote.example.com",
        "https://acme.atlassian.net?secret=1",
    ],
)
def test_invalid_or_credential_bearing_urls_are_rejected(url: str) -> None:
    with pytest.raises(ConnectorValidationError):
        JiraServiceManagementConnector().load_credentials(
            {"jsm_base_url": url, "jsm_bearer_token": "token"}
        )


def test_agent_probe_is_required_before_full_or_slim_listing(
    connector: JiraServiceManagementConnector, responses: MagicMock
) -> None:
    def restricted(path: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if path == "servicedesk":
            return {"values": [DESK], "isLastPage": True}
        raise InsufficientPermissionsError("Customer cannot access agent queues")

    responses.side_effect = restricted
    with patch.object(connector, "_iter_issues") as search:
        for run in [
            connector.load_from_state,
            connector.retrieve_all_slim_docs,
            connector.validate_connector_settings,
        ]:
            with pytest.raises(InsufficientPermissionsError):
                result = run()
                if result is not None:
                    list(result)
        search.assert_not_called()


@pytest.mark.usefixtures("responses")
def test_missing_configured_desk_fails_instead_of_partial_pruning(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.service_desk_ids = ["10", "20"]
    with pytest.raises(InsufficientPermissionsError):
        list(connector.retrieve_all_slim_docs())


@pytest.mark.parametrize(
    "status,error",
    [
        (401, CredentialExpiredError),
        (403, InsufficientPermissionsError),
        (404, JSMResourceNotFoundError),
        (429, RateLimitedValidationError),
        (500, UnexpectedValidationError),
        (302, UnexpectedValidationError),
    ],
)
def test_api_errors_do_not_become_empty_data(
    connector: JiraServiceManagementConnector, status: int, error: type[Exception]
) -> None:
    with patch.object(
        connector._session, "get", return_value=_mock_response(status, {})
    ):
        with pytest.raises(error):
            connector._fetch_request_comments("ITSM-1")


@pytest.mark.parametrize(
    "page",
    [
        {},
        {"values": []},
        {"values": [], "isLastPage": False},
        {"values": ["invalid"], "isLastPage": True},
    ],
)
def test_incomplete_pages_fail_closed(
    connector: JiraServiceManagementConnector, page: dict[str, Any]
) -> None:
    with patch.object(connector, "_api_get", return_value=page):
        with pytest.raises(UnexpectedValidationError):
            list(connector._paginate("servicedesk"))


def test_full_and_slim_use_identical_project_scope_including_non_requests(
    connector: JiraServiceManagementConnector, responses: MagicMock
) -> None:
    rows = [issue(1), issue(2, customer_request=False)]
    with patch.object(
        connector,
        "_iter_issues",
        side_effect=lambda *_args, **_kwargs: iter(deepcopy(rows)),
    ) as search:
        full = documents(connector.load_from_state())
        slim = documents(connector.retrieve_all_slim_docs())
    assert (
        [d.id for d in full]
        == [d.id for d in slim]
        == ["JSM_REQUEST_ITSM-1", "JSM_REQUEST_ITSM-2"]
    )
    assert all(
        call.args[0] == 'project = "ITSM" ORDER BY key ASC'
        for call in search.call_args_list
    )
    text = "\n".join(s.text or "" for d in full for s in d.sections)
    assert "New description" in text and "Updated custom field" in text
    assert "Internal secret" not in text
    assert not any(
        c.args[0] == "request/ITSM-2/comment" for c in responses.call_args_list
    )


@pytest.mark.usefixtures("responses")
def test_out_of_scope_response_blocks_full_and_pruning(
    connector: JiraServiceManagementConnector,
) -> None:
    row = issue()
    row["fields"]["project"]["key"] = "OTHER"
    for run in [connector.load_from_state, connector.retrieve_all_slim_docs]:
        with patch.object(connector, "_iter_issues", return_value=iter([row])):
            with pytest.raises(UnexpectedValidationError):
                list(run())


@pytest.mark.usefixtures("responses")
def test_field_only_edits_use_jira_update_cursor(
    connector: JiraServiceManagementConnector,
) -> None:
    row = issue()
    with patch.object(
        connector,
        "_iter_issues",
        side_effect=lambda *_args, **_kwargs: iter(
            [] if "running()" in _args[0] else [row]
        ),
    ) as search:
        docs = documents(connector.poll_source(START, END))
    assert len(docs) == 1
    assert docs[0].doc_updated_at == datetime(2026, 10, 25, 12, 30, tzinfo=timezone.utc)
    assert (
        f"updated >= {int(START * 1000)} AND updated <= {int(END * 1000)}"
        in search.call_args_list[-1].args[0]
    )
    assert "New summary" in docs[0].semantic_identifier


@pytest.mark.usefixtures("responses")
def test_clock_only_breach_refreshes_old_issue_and_advances_dedup_timestamp(
    connector: JiraServiceManagementConnector,
) -> None:
    row = issue()
    row["fields"]["updated"] = "2026-10-01T10:00:00Z"
    row["fields"]["customfield_10002"] = {"ongoingCycle": {"breached": True}}
    with patch.object(
        connector,
        "_iter_issues",
        side_effect=lambda jql, **_kwargs: iter([row] if "running()" in jql else []),
    ) as search:
        docs = documents(connector.poll_source(START, END))
    assert len(docs) == 1
    assert docs[0].doc_updated_at == datetime.fromtimestamp(END, tz=timezone.utc)
    assert docs[0].metadata["jira_updated_at"] == "2026-10-01T10:00:00Z"
    assert "breached=True" in "\n".join(s.text or "" for s in docs[0].sections)
    jql = search.call_args_list[0].args[0]
    assert "cf[10002] = running()" in jql and "cf[10002] = paused()" in jql


@pytest.mark.usefixtures("responses")
def test_sla_completing_during_refresh_still_advances_timestamp(
    connector: JiraServiceManagementConnector,
) -> None:
    row = issue()
    row["fields"]["updated"] = "2026-10-01T10:00:00Z"
    row["fields"]["customfield_10002"] = {"completedCycles": [{"breached": True}]}
    with patch.object(
        connector,
        "_iter_issues",
        side_effect=lambda jql, **_kwargs: iter([row] if "running()" in jql else []),
    ):
        docs = documents(connector.poll_source(START, END))
    assert docs[0].doc_updated_at == datetime.fromtimestamp(END, tz=timezone.utc)


@pytest.mark.usefixtures("responses")
def test_refresh_limit_fails_before_yielding_any_documents(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.max_active_sla_requests = 1
    with patch.object(
        connector, "_iter_issues", return_value=iter([issue(1), issue(2)])
    ):
        with pytest.raises(ConnectorValidationError, match="limit exceeded"):
            next(connector.poll_source(START, END))


@pytest.mark.usefixtures("responses")
def test_updated_and_sla_refresh_overlap_is_deduplicated(
    connector: JiraServiceManagementConnector,
) -> None:
    with patch.object(
        connector, "_iter_issues", side_effect=lambda *_args, **_kwargs: iter([issue()])
    ):
        assert len(documents(connector.poll_source(START, END))) == 1


def test_cloud_gateway_uses_enhanced_search_cursors_and_validates_bulk_ids(
    connector: JiraServiceManagementConnector,
) -> None:
    gateway = MagicMock(spec=JiraSourceOperations)
    connector._jira = gateway
    gateway.search_issue_ids.side_effect = [
        JiraIssueIdPage(issue_ids=["1"], next_page_token="page2"),
        JiraIssueIdPage(issue_ids=["2"], next_page_token=None),
    ]
    gateway.bulk_fetch_issues.side_effect = [[issue(1)], [issue(2)]]
    assert len(list(connector._iter_issues('project = "ITSM"'))) == 2
    assert gateway.search_issue_ids.call_args.kwargs["next_page_token"] == "page2"
    gateway.search_issue_ids.side_effect = None
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1", "2"], next_page_token=None
    )
    gateway.bulk_fetch_issues.side_effect = None
    gateway.bulk_fetch_issues.return_value = [issue(1)]
    with pytest.raises(UnexpectedValidationError, match="omitted"):
        list(connector._iter_issues('project = "ITSM"'))


def test_dc_gateway_continues_after_short_pages(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.bearer_token = "dc-token"
    gateway = MagicMock(spec=JiraSourceOperations)
    connector._jira = gateway
    gateway.search_issues.side_effect = [[issue(1)], [issue(2)], []]
    assert len(list(connector._iter_issues('project = "ITSM"'))) == 2
    assert [c.kwargs["start_at"] for c in gateway.search_issues.call_args_list] == [
        0,
        1,
        2,
    ]


def test_gateway_permission_failure_propagates(
    connector: JiraServiceManagementConnector,
) -> None:
    gateway = MagicMock(spec=JiraSourceOperations)
    connector._jira = gateway
    gateway.search_issue_ids.side_effect = JiraApiError("forbidden", status_code=403)
    with pytest.raises(InsufficientPermissionsError):
        list(connector._iter_issues('project = "ITSM"'))


@pytest.mark.usefixtures("responses")
def test_slim_cancellation_raises_instead_of_returning_partial_ids(
    connector: JiraServiceManagementConnector,
) -> None:
    callback = MagicMock()
    callback.should_stop.return_value = True
    with pytest.raises(RuntimeError, match="pruning is unsafe"):
        list(connector.retrieve_all_slim_docs(callback=callback))


@pytest.mark.usefixtures("responses")
@pytest.mark.parametrize("updated", ["2026-10-01T10:00:00Z", "2026-10-25T14:00:00Z"])
def test_poll_rechecks_source_update_bounds_after_search(
    connector: JiraServiceManagementConnector,
    updated: str,
) -> None:
    row = issue()
    row["fields"]["updated"] = updated
    with patch.object(
        connector,
        "_iter_issues",
        side_effect=lambda jql, **_kwargs: iter([] if "running()" in jql else [row]),
    ):
        assert documents(connector.poll_source(START, END)) == []


@pytest.mark.usefixtures("responses")
def test_desk_only_scope_is_supported(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.project_key = None
    connector.service_desk_ids = ["10"]
    with patch.object(
        connector, "_iter_issues", side_effect=lambda *_args, **_kwargs: iter([issue()])
    ):
        assert [d.id for d in documents(connector.load_from_state())] == [
            "JSM_REQUEST_ITSM-1"
        ]


def test_repeated_cloud_cursor_fails(connector: JiraServiceManagementConnector) -> None:
    gateway = MagicMock(spec=JiraSourceOperations)
    connector._jira = gateway
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=[], next_page_token="loop"
    )
    with pytest.raises(UnexpectedValidationError, match="cursor"):
        list(connector._iter_issues('project = "ITSM"'))


def test_repeated_jsm_page_fails(connector: JiraServiceManagementConnector) -> None:
    with patch.object(
        connector,
        "_api_get",
        return_value={"values": [{"id": "1"}], "isLastPage": False},
    ):
        with pytest.raises(UnexpectedValidationError, match="repeated"):
            list(connector._paginate("servicedesk"))


@pytest.mark.usefixtures("responses")
def test_updated_payload_wins_over_earlier_sla_refresh(
    connector: JiraServiceManagementConnector,
) -> None:
    before, after = issue(), issue()
    before["fields"]["summary"] = "Earlier summary"
    after["fields"]["summary"] = "Latest summary"
    with patch.object(
        connector,
        "_iter_issues",
        side_effect=lambda jql, **_kwargs: iter(
            [before] if "running()" in jql else [after]
        ),
    ):
        docs = documents(connector.poll_source(START, END))
    assert len(docs) == 1
    assert "Latest summary" in docs[0].semantic_identifier


@pytest.mark.usefixtures("responses")
def test_initial_epoch_poll_does_not_duplicate_full_load_with_active_scan(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.max_active_sla_requests = 1
    with patch.object(
        connector, "_iter_issues", return_value=iter([issue(1), issue(2)])
    ) as search:
        assert len(documents(connector.poll_source(0, END))) == 2
    assert "running()" not in search.call_args.args[0]


@pytest.mark.usefixtures("responses")
def test_adf_and_custom_field_value_rendering(
    connector: JiraServiceManagementConnector,
) -> None:
    test_issue = {
        "id": "100",
        "key": "ITSM-100",
        "fields": {
            "project": {"key": "ITSM"},
            "created": "2026-10-01T10:00:00Z",
            "updated": "2026-10-25T12:30:00Z",
            "summary": "Outage Incident",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Incident description text"}
                        ],
                    }
                ],
            },
            "customfield_10001": {"requestType": {"id": "5"}},
            "customfield_10002": None,
            "customfield_10010": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Root cause: network switch failure.",
                            }
                        ],
                    }
                ],
            },
            "customfield_10011": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "First paragraph text."}],
                    },
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Second paragraph text"},
                            {"type": "text", "text": "with multiple parts."},
                        ],
                    },
                ],
            },
            "customfield_10012": "Plain string value unchanged",
            "customfield_10013": {"name": "Hardware", "id": "101"},
            "customfield_10014": 42,
            "customfield_10015": True,
            "customfield_10016": None,
            "status": {
                "name": "Investigating",
                "statusCategory": {"name": "In Progress"},
            },
        },
    }
    names = {
        "summary": "Summary",
        "description": "Description",
        "customfield_10010": "Root Cause",
        "customfield_10011": "Impact Details",
        "customfield_10012": "Source Channel",
        "customfield_10013": "Component",
        "customfield_10014": "Affected Hosts",
        "customfield_10015": "Customer Impacting",
        "customfield_10016": "Resolution Notes",
    }
    request_types = {"customfield_10001"}
    sla_fields = {"customfield_10002"}

    req, comments, slas = connector._issue_content(
        test_issue, names, request_types, sla_fields
    )

    fields_by_id = {f["fieldId"]: f for f in req["requestFieldValues"]}

    # 1. ADF custom text becomes readable string
    assert (
        fields_by_id["customfield_10010"]["value"]
        == "Root cause: network switch failure."
    )

    # 2. Nested ADF paragraphs correctly extracted
    assert (
        fields_by_id["customfield_10011"]["value"]
        == "First paragraph text. Second paragraph text with multiple parts."
    )

    # 3. Ordinary strings remain unchanged
    assert fields_by_id["customfield_10012"]["value"] == "Plain string value unchanged"

    # 4. Non-ADF structured values preserve existing types/values
    assert fields_by_id["customfield_10013"]["value"] == {
        "name": "Hardware",
        "id": "101",
    }
    assert fields_by_id["customfield_10014"]["value"] == 42
    assert fields_by_id["customfield_10015"]["value"] is True
    assert fields_by_id["customfield_10016"]["value"] is None

    # 5. Description ADF conversion preserved
    assert fields_by_id["description"]["value"] == "Incident description text"

    # Verify rendering through _render_request_field_values into indexed text lines
    summary, field_lines = _render_request_field_values(
        req["requestFieldValues"], default_summary=test_issue["key"]
    )
    assert summary == "Outage Incident"
    assert "Root Cause: Root cause: network switch failure." in field_lines
    assert (
        "Impact Details: First paragraph text. Second paragraph text with multiple parts."
        in field_lines
    )
    assert "Source Channel: Plain string value unchanged" in field_lines
    assert "Component: Hardware" in field_lines
    assert "Affected Hosts: 42" in field_lines
    assert "Customer Impacting: True" in field_lines
    for line in field_lines:
        assert "{'type': 'doc'" not in line

    # Direct helper test: ADF dictionary passed directly to _render_request_field_values
    direct_fields = [
        {
            "fieldId": "customfield_direct",
            "label": "Direct ADF",
            "value": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Direct ADF value rendered"}
                        ],
                    }
                ],
            },
        }
    ]
    _, direct_lines = _render_request_field_values(direct_fields, "DEFAULT")
    assert "Direct ADF: Direct ADF value rendered" in direct_lines
