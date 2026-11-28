"""Tests for the Jira Service Management connector.

Two layers, mirroring repo convention:
- pure-offline unit tests with a stubbed JSM client (run anywhere);
- a live smoke test that skips unless JSM_* env vars are set.
"""

import os
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document

_REQUEST = {
    "issueId": "10001",
    "issueKey": "SD-42",
    "serviceDeskId": "7",
    "requestTypeId": "17",
    "createdDate": {"iso8601": "2026-01-05T09:00:00+0000"},
    "currentStatus": {
        "status": "Waiting for support",
        "statusDate": {"iso8601": "2026-01-06T10:30:00+0000"},
    },
    "reporter": {"displayName": "Jane Customer"},
    "requestFieldValues": {
        "summary": {"value": "VPN access broken"},
        "description": {"value": "Cannot reach internal tools via VPN."},
    },
}

_COMMENT = {
    "body": "We reproduced it, fix deploying today.",
    "createdDate": {"iso8601": "2026-01-06T11:00:00+0000"},
    "author": {"displayName": "Agent A"},
}


class _StubJsmClient:
    """Offline stand-in for JsmApiClient (records its configuration)."""

    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.desks: list[dict[str, Any]] = [{"id": "7", "projectKey": "SD"}]
        self.requests: list[dict[str, Any]] = [_REQUEST]
        self.comments: list[dict[str, Any]] = [_COMMENT]

    def list_service_desks(self, _page_size: int) -> list[dict[str, Any]]:
        return self.desks

    def list_requests(
        self, _service_desk_id: str, _page_size: int
    ) -> list[dict[str, Any]]:
        return self.requests

    def list_request_comments(
        self, _issue_id_or_key: str, _page_size: int, _public_only: bool = True
    ) -> list[dict[str, Any]]:
        return self.comments


@pytest.fixture
def connector(monkeypatch: pytest.MonkeyPatch) -> JiraServiceManagementConnector:
    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector.JsmApiClient",
        _StubJsmClient,
    )
    return JiraServiceManagementConnector(batch_size=5)


def _credentials() -> dict[str, str]:
    return {
        "jira_service_management_base_url": "https://example.atlassian.net",
        "jira_service_management_email": "agent@example.com",
        "jira_service_management_api_token": "fake-token",
    }


def test_missing_credentials_raises() -> None:
    c = JiraServiceManagementConnector()
    with pytest.raises(ConnectorMissingCredentialError) as exc_info:
        list(c.load_from_state())
    assert "Jira Service Management" in str(exc_info.value)

    with pytest.raises(ConnectorMissingCredentialError):
        c.load_credentials({})  # all keys absent


def test_load_credentials_builds_client(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.load_credentials(_credentials())
    client = connector.jsm_client
    assert client is not None
    assert client.base_url == "https://example.atlassian.net"
    assert client.email == "agent@example.com"
    assert client.api_token == "fake-token"


def test_request_becomes_document(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.load_credentials(_credentials())
    docs: list[Document] = []
    for batch in connector.load_from_state():
        docs.extend(batch)

    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == "jira_service_management__SD-42"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.semantic_identifier == "SD-42: VPN access broken"
    assert doc.title == "VPN access broken"
    assert doc.doc_created_at is not None
    assert doc.doc_updated_at is not None
    assert doc.metadata["status"] == "Waiting for support"
    assert doc.metadata["reporter"] == "Jane Customer"
    assert doc.metadata["service_desk_id"] == "7"
    section = doc.sections[0]
    assert section.link == "https://example.atlassian.net/browse/SD-42"
    assert "VPN access broken" in section.text
    assert "Cannot reach internal tools" in section.text
    assert "We reproduced it" in section.text


def test_scoped_desk_only_indexes_that_desk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubJsmClient("https://x.atlassian.net", "e", "t")
    captured: list[str] = []

    def list_requests(service_desk_id: str, _page_size: int):
        captured.append(service_desk_id)
        return stub.requests

    stub.list_requests = list_requests  # type: ignore[method-assign]
    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector.JsmApiClient",
        lambda **_kwargs: stub,
    )
    connector = JiraServiceManagementConnector(service_desk_id="3")
    connector.load_credentials(_credentials())
    [doc for batch in connector.load_from_state() for doc in batch]
    assert captured == ["3"]


def test_poll_filters_by_time_window(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.load_credentials(_credentials())
    # Document's updated time is 2026-01-06T10:30Z.
    before = connector.poll_source(0, 1)  # window before the doc
    assert [d for b in before for d in b] == []
    around = connector.poll_source(1_600_000_000, 1_800_000_000)
    assert len([d for b in around for d in b]) == 1


def test_empty_request_skipped(
    connector: JiraServiceManagementConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_text(**_kwargs: Any) -> _StubJsmClient:
        stub = _StubJsmClient(**_kwargs)
        stub.requests = [{"issueKey": "SD-9", "requestFieldValues": {}}]
        stub.comments = []
        return stub

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector.JsmApiClient",
        no_text,
    )
    connector.load_credentials(_credentials())
    assert [d for b in connector.load_from_state() for d in b] == []


# ---- live smoke test (skipped without real credentials) ----


@pytest.fixture
def live_credentials() -> dict[str, Any]:
    creds = {
        "jira_service_management_base_url": os.environ.get("JSM_BASE_URL"),
        "jira_service_management_email": os.environ.get("JSM_EMAIL"),
        "jira_service_management_api_token": os.environ.get("JSM_API_TOKEN"),
    }
    if not all(creds.values()):
        pytest.skip("JSM_BASE_URL / JSM_EMAIL / JSM_API_TOKEN must be set")
    return creds


def test_live_connector_fetches_documents(
    live_credentials: dict[str, Any],
) -> None:
    connector = JiraServiceManagementConnector(batch_size=20)
    connector.load_credentials(live_credentials)
    docs = [d for batch in connector.load_from_state() for d in batch]
    assert docs, "Expected at least one JSM request"
    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.sections and doc.sections[0].link.startswith(
            live_credentials["jira_service_management_base_url"].rstrip("/")
        )
