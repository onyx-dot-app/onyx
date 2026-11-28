"""Unit tests for the Jira Service Management connector.

No network access and no real credentials: the HTTP session is replaced
with a fake that serves canned paginated JSM responses.
"""

from datetime import datetime, timezone
from typing import Any

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_management.client import JsmApiClient, JsmApiError
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
    jira_service_management_planning_rule,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    process_jsm_request,
)
from onyx.connectors.jira_service_management.models import JsmRequest


def _api_request(**overrides: Any) -> dict[str, Any]:
    req: dict[str, Any] = {
        "issueId": 1001,
        "issueKey": "SD-42",
        "requestTypeId": 7,
        "serviceDeskId": 3,
        "createdDate": "2023-06-21T09:27:05.000+0000",
        "reporter": {"displayName": "Ada", "emailAddress": "ada@example.com"},
        "requestFieldValues": [
            {"fieldId": 1, "name": "Summary", "value": "Printer broken"},
            {"fieldId": 2, "name": "Description", "value": "It jams."},
            {"fieldId": 3, "name": "Priority", "value": 2},
        ],
        "currentStatus": {
            "status": "Open",
            "statusCategory": "new",
            "statusDate": "2023-06-22T10:00:00.000+0000",
        },
    }
    req.update(overrides)
    return req


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeSession:
    """Serves canned paginated JSM pages and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        # timeout is accepted for signature compatibility; the fake never waits.
        _ = timeout
        params = dict(params or {})
        self.calls.append((url, params))
        if url.endswith("/rest/servicedeskapi/servicedesk"):
            return FakeResponse(
                200,
                {
                    "isLastPage": True,
                    "values": [
                        {"id": 1, "projectKey": "SD", "projectName": "Desk One"},
                        {"id": 2, "projectKey": "IT", "projectName": "Desk Two"},
                    ],
                },
            )
        if "/servicedesk/1/request" in url:
            return FakeResponse(
                200,
                {
                    "isLastPage": True,
                    "values": [
                        {"issueKey": "SD-1", "issueId": 11},
                        {"issueKey": "SD-2", "issueId": 12},
                    ],
                },
            )
        if "/servicedesk/2/request" in url:
            return FakeResponse(
                200,
                {"isLastPage": True, "values": [{"issueKey": "IT-9", "issueId": 19}]},
            )
        if "/comment" in url:
            return FakeResponse(
                200, {"isLastPage": True, "values": [{"id": 1, "body": "hello"}]}
            )
        return FakeResponse(404, {"error": "not found"})


def _client_with_fake_session() -> tuple[JsmApiClient, FakeSession]:
    client = JsmApiClient(
        base_url="https://example.atlassian.net",
        email="a@b.c",
        token="tok",
    )
    fake = FakeSession()
    client.session = fake  # type: ignore[assignment]
    return client, fake


# ---------------------------------------------------------------- models


def test_jsm_request_alias_population() -> None:
    req = JsmRequest(**_api_request())
    assert req.issue_key == "SD-42"
    assert req.created_date == "2023-06-21T09:27:05.000+0000"
    assert req.request_field_values is not None
    assert len(req.request_field_values) == 3


def test_jsm_request_non_string_value_kept_as_any() -> None:
    req = JsmRequest(**_api_request())
    assert req.request_field_values is not None
    assert req.request_field_values[2].value == 2


def test_jsm_request_sparse_defaults_to_none() -> None:
    req = JsmRequest(issueKey="SD-1")
    assert req.issue_id is None
    assert req.reporter is None
    assert req.request_field_values is None


# ---------------------------------------------------------------- client


def test_list_service_desks() -> None:
    client, _ = _client_with_fake_session()
    desks = list(client.list_service_desks())
    assert len(desks) == 2
    assert desks[0]["projectKey"] == "SD"


def test_list_requests_without_desk_enumerates_desks() -> None:
    client, fake = _client_with_fake_session()
    keys = [r["issueKey"] for r in client.list_requests(service_desk_id=None)]
    assert keys == ["SD-1", "SD-2", "IT-9"]
    # The JSM API has no all-desks request endpoint; the client must never
    # call the bogus /rest/servicedeskapi/servicedesk/request URL.
    assert not any(url.endswith("/servicedesk/request") for url, _ in fake.calls)


def test_list_requests_with_desk() -> None:
    client, _ = _client_with_fake_session()
    keys = [r["issueKey"] for r in client.list_requests(service_desk_id="1")]
    assert keys == ["SD-1", "SD-2"]


def test_list_comments_passes_public_true() -> None:
    client, fake = _client_with_fake_session()
    comments = list(client.list_comments("SD-1", public_only=True))
    assert len(comments) == 1
    assert comments[0]["body"] == "hello"
    assert fake.calls[-1][1].get("public") == "true"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_check_response_preserves_status_code(status: int) -> None:
    client, _ = _client_with_fake_session()
    with pytest.raises(JsmApiError) as exc_info:
        client._check_response(FakeResponse(status, {}))
    assert exc_info.value.status_code == status


# ---------------------------------------------------------------- document shaping


def test_process_jsm_request_builds_document() -> None:
    req = JsmRequest(**_api_request())
    comments = [
        {
            "author": {"displayName": "Bob", "emailAddress": "bob@x.com"},
            "body": "Looking into it",
            "public": True,
        },
        {
            "author": {"displayName": "Mallory", "emailAddress": "bad@x.com"},
            "body": "secret",
            "public": False,
        },
        {"author": {"displayName": "Empty"}, "body": "   ", "public": True},
    ]
    doc = process_jsm_request(
        "https://example.atlassian.net",
        req,
        comments,
        comment_email_blacklist=["bad@x.com"],
    )
    assert doc is not None
    assert doc.id == "https://example.atlassian.net/browse/SD-42"
    assert doc.title == "SD-42 Printer broken"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    text = doc.sections[0].text
    assert "It jams." in text
    assert "Looking into it" in text
    assert "secret" not in text
    assert text.count("Comment by") == 1
    assert doc.primary_owners == ["Ada"]
    # The reporter metadata is the name, not the whole dict, and no value
    # may be None (the Document metadata validator would stringify it).
    assert doc.metadata.get("reporter") == "Ada"
    assert all(v is not None for v in doc.metadata.values())
    assert doc.doc_created_at is not None and doc.doc_created_at.year == 2023
    assert doc.doc_updated_at is not None and doc.doc_updated_at.day == 22


def test_process_jsm_request_coerces_non_string_values() -> None:
    req = JsmRequest(
        **_api_request(
            requestFieldValues=[{"fieldId": 2, "name": "Description", "value": 42}]
        )
    )
    doc = process_jsm_request("https://example.atlassian.net", req, [])
    assert doc is not None
    assert "42" in doc.sections[0].text


def test_process_jsm_request_returns_none_over_1mb() -> None:
    req = JsmRequest(
        **_api_request(
            requestFieldValues=[
                {"fieldId": 2, "name": "Description", "value": "x" * 1_000_001}
            ]
        )
    )
    assert process_jsm_request("https://example.atlassian.net", req, []) is None


# ---------------------------------------------------------------- connector


def _connector(**kwargs: Any) -> JiraServiceManagementConnector:
    return JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net", **kwargs
    )


def test_in_window_compares_string_dates_to_epoch_floats() -> None:
    conn = _connector()
    req = JsmRequest(**_api_request())
    start = datetime(2023, 6, 21, 0, 0, tzinfo=timezone.utc).timestamp()
    end = datetime(2023, 6, 21, 23, 59, tzinfo=timezone.utc).timestamp()
    assert conn._in_window(req, start, end) is True
    start2 = datetime(2023, 7, 1, tzinfo=timezone.utc).timestamp()
    end2 = datetime(2023, 7, 2, tzinfo=timezone.utc).timestamp()
    assert conn._in_window(req, start2, end2) is False


def test_project_key_resolves_desk() -> None:
    conn = _connector(project_key="IT")
    client, _ = _client_with_fake_session()
    conn.client = client
    assert [d["issueKey"] for d in conn._iter_request_dicts()] == ["IT-9"]


def test_service_desk_id_wins_over_project_key() -> None:
    conn = _connector(service_desk_id="1", project_key="IT")
    client, _ = _client_with_fake_session()
    conn.client = client
    assert [d["issueKey"] for d in conn._iter_request_dicts()] == ["SD-1", "SD-2"]


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, CredentialExpiredError),
        (403, InsufficientPermissionsError),
        (404, ConnectorValidationError),
    ],
)
def test_validate_connector_settings_maps_errors(
    status: int, expected: type[Exception]
) -> None:
    conn = _connector()
    client, _ = _client_with_fake_session()
    conn.client = client

    def _boom() -> Any:
        raise JsmApiError(status, "nope")

    client.list_service_desks = _boom  # type: ignore[method-assign]
    with pytest.raises(expected):
        conn.validate_connector_settings()


def test_load_credentials_missing_raises() -> None:
    from onyx.connectors.models import ConnectorMissingCredentialError

    conn = _connector()
    with pytest.raises(ConnectorMissingCredentialError):
        conn.load_credentials({})


def test_planning_rule_ignores_project_key_when_desk_set() -> None:
    old = JiraServiceManagementConnectorConfig(
        jira_base_url="https://example.atlassian.net", service_desk_id="3"
    )
    new = JiraServiceManagementConnectorConfig(
        jira_base_url="https://example.atlassian.net", service_desk_id="3"
    )
    override = jira_service_management_planning_rule(old, new)
    assert override is not None
    assert override.scope_directions.get("project_key") is not None
    assert override.scope_directions["project_key"].value == "none"


def test_planning_rule_returns_none_when_desk_newly_set() -> None:
    old = JiraServiceManagementConnectorConfig(
        jira_base_url="https://example.atlassian.net"
    )
    new = JiraServiceManagementConnectorConfig(
        jira_base_url="https://example.atlassian.net", service_desk_id="3"
    )
    assert jira_service_management_planning_rule(old, new) is None


def test_load_from_state_yields_documents() -> None:
    conn = _connector(service_desk_id="1")
    client, _ = _client_with_fake_session()
    conn.client = client
    docs = list(conn.load_from_state())
    assert len(docs) == 2
    assert all(d.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for d in docs)
