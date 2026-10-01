from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture
def jsm_domain() -> str:
    return "acme.atlassian.net"


@pytest.fixture
def service_desk_id() -> str:
    return "1"


@pytest.fixture
def user_email() -> str:
    return "test@example.com"


@pytest.fixture
def api_token() -> str:
    return "token123"


@pytest.fixture
def mock_jsm_session() -> MagicMock:
    """Mock requests.Session carrying the `base_url` attribute
    build_jsm_session attaches."""
    mock = MagicMock(spec=requests.Session)
    mock.base_url = "https://acme.atlassian.net"
    return mock


@pytest.fixture
def connector(
    jsm_domain: str,
    service_desk_id: str,
    user_email: str,
    api_token: str,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jsm_domain=jsm_domain,
        service_desk_id=service_desk_id,
    )
    connector.load_credentials(
        {
            "jira_user_email": user_email,
            "jira_api_token": api_token,
        }
    )
    return connector


def make_raw_request(
    issue_key: str = "IT-1",
    summary: str = "Printer on fire",
    created_iso: str = "2026-05-06T10:00:00.000+0000",
    status_date_iso: str = "2026-05-06T11:00:00.000+0000",
    resolution_iso: str | None = None,
    status: str = "In Progress",
    reporter: dict | None = None,
    participants: list[dict] | None = None,
    organizations: list[dict] | None = None,
    web_link: str = "/servicedesk/customer/portal/1/IT-1",
    priority: str | None = "P2",
) -> dict:
    """Build a raw JSM `/request` payload value shaped like the real API:
    https://developer.atlassian.com/cloud/jira/service-desk/rest/api-group-request/
    """
    return {
        "issueKey": issue_key,
        "summary": summary,
        "description": f"Description of {issue_key}",
        "createdDate": {"iso8601": created_iso},
        "currentStatus": {"status": status, "statusDate": {"iso8601": status_date_iso}},
        "resolutionDate": {"iso8601": resolution_iso} if resolution_iso else None,
        "serviceDeskId": 1,
        "requestType": {"id": "11", "name": "Get IT help", "description": "IT help"},
        "priority": priority,
        "reporter": reporter
        or {
            "accountId": "acc-1",
            "displayName": "Alice",
            "emailAddress": "alice@example.com",
        },
        "participants": participants or [],
        "organizations": {"values": organizations or []},
        "_links": {"web": web_link, "jira": "/browse/IT-1"},
    }


def make_page(values: list[dict], is_last_page: bool) -> dict:
    return {"values": values, "isLastPage": is_last_page, "start": 0, "limit": 50}
