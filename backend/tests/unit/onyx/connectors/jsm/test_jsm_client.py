"""Tests for the JSM REST helpers (client.py): URL building, session auth,
error mapping, and pagination."""

from typing import Any

import pytest
import requests
import responses

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jsm.client import (
    build_jsm_session,
    fetch_participants,
    fetch_request_type_for_issue,
    fetch_service_desk,
    fetch_service_desks,
    jsm_get,
)

_JSM_BASE = "https://jsm.example.com"


def test_jsm_url_strips_trailing_slash() -> None:
    session = build_jsm_session({"jira_api_token": "token"})
    with responses.RequestsMock() as rsps:
        rsps.get(
            f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
            json={"values": [], "isLastPage": True},
        )
        payload = jsm_get(session, f"{_JSM_BASE}/", "servicedesk")
    assert payload["values"] == []


class TestBuildJsmSession:
    def test_cloud_credentials_use_basic_auth(self) -> None:
        session = build_jsm_session(
            {"jira_user_email": "user@example.com", "jira_api_token": "token"}
        )
        assert session.auth == ("user@example.com", "token")
        assert "Authorization" not in session.headers

    def test_data_center_token_uses_bearer_auth(self) -> None:
        session = build_jsm_session({"jira_api_token": "pat-token"})
        assert session.auth is None
        assert session.headers["Authorization"] == "Bearer pat-token"

    def test_experimental_api_header_is_sent(self) -> None:
        session = build_jsm_session({"jira_api_token": "pat-token"})
        assert session.headers["X-ExperimentalApi"] == "opt-in"


class TestFetchServiceDesks:
    def test_single_page(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                json={
                    "values": [{"id": "10", "projectName": "Help Desk"}],
                    "isLastPage": True,
                },
            )
            desks = fetch_service_desks(session, _JSM_BASE)
        assert [desk["id"] for desk in desks] == ["10"]

    def test_paginates_until_last_page(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        pages: list[list[dict[str, Any]]] = [
            [{"id": str(i)} for i in range(50)],
            [{"id": "50"}],
        ]
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                json={
                    "values": pages[0],
                    "isLastPage": False,
                    "_links": {"next": "next"},
                },
            )
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                json={"values": pages[1], "isLastPage": True},
            )
            desks = fetch_service_desks(session, _JSM_BASE)
        assert [desk["id"] for desk in desks] == [str(i) for i in range(51)]


class TestErrorMapping:
    def test_401_maps_to_credential_expired(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                status=401,
            )
            with pytest.raises(CredentialExpiredError):
                jsm_get(session, _JSM_BASE, "servicedesk")

    def test_403_maps_to_insufficient_permissions(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                status=403,
            )
            with pytest.raises(InsufficientPermissionsError):
                jsm_get(session, _JSM_BASE, "servicedesk")

    def test_404_maps_to_connector_validation_error(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                status=404,
            )
            with pytest.raises(ConnectorValidationError, match="servicedesk"):
                jsm_get(session, _JSM_BASE, "servicedesk")

    def test_network_error_reraises(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk",
                body=requests.ConnectionError("no route"),
            )
            with pytest.raises(requests.ConnectionError):
                jsm_get(session, _JSM_BASE, "servicedesk")


class TestFetchServiceDesk:
    def test_404_returns_none(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk/42",
                status=404,
            )
            assert fetch_service_desk(session, _JSM_BASE, "42") is None

    def test_401_reraises_credential_expired(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk/42",
                status=401,
            )
            with pytest.raises(CredentialExpiredError):
                fetch_service_desk(session, _JSM_BASE, "42")

    def test_403_reraises_insufficient_permissions(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk/42",
                status=403,
            )
            with pytest.raises(InsufficientPermissionsError):
                fetch_service_desk(session, _JSM_BASE, "42")

    def test_found_returns_payload(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/servicedesk/42",
                json={"id": "42", "projectName": "Support"},
            )
            desk = fetch_service_desk(session, _JSM_BASE, "42")
        assert desk == {"id": "42", "projectName": "Support"}


class TestBestEffortEnrichment:
    def test_request_type_missing_name_returns_none(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/request/10001/requesttype",
                json={"id": "25", "name": ""},
            )
            assert fetch_request_type_for_issue(session, _JSM_BASE, "10001") is None

    def test_participants_error_returns_empty_list(self) -> None:
        session = build_jsm_session({"jira_api_token": "token"})
        with responses.RequestsMock() as rsps:
            rsps.get(
                f"{_JSM_BASE}/rest/servicedeskapi/request/10001/participant",
                status=500,
            )
            assert fetch_participants(session, _JSM_BASE, "10001") == []
