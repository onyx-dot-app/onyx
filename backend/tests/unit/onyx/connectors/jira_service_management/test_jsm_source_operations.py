"""The Jira Service Management gateway's HTTP calls, with a mocked session."""

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_management import source_operations
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
    JsmApiError,
)

_BASE = "https://example.atlassian.net"


def _response(
    status: int, body: Any = None, headers: dict[str, str] | None = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response.url = _BASE
    response._content = b"" if body is None else json.dumps(body).encode()
    return response


def _gateway(
    credentials: dict[str, str],
) -> Iterator[JiraServiceManagementSourceOperations]:
    with patch.object(source_operations, "validate_base_url"):
        yield JiraServiceManagementSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.JIRA_SERVICE_MANAGEMENT.value, credentials
            ),
            connector_specific_config={"jira_base_url": _BASE},
        )


@pytest.fixture
def cloud() -> Iterator[JiraServiceManagementSourceOperations]:
    yield from _gateway(
        {"jira_user_email": "ada@example.com", "jira_api_token": "token"}
    )


@pytest.fixture
def server() -> Iterator[JiraServiceManagementSourceOperations]:
    yield from _gateway({"jira_api_token": "pat"})


def test_cloud_lists_every_request_with_basic_auth(
    cloud: JiraServiceManagementSourceOperations,
) -> None:
    get = MagicMock(
        return_value=_response(
            200,
            {"isLastPage": True, "size": 0, "values": []},
        )
    )
    with patch.object(requests.Session, "get", get):
        page = cloud.list_requests(service_desk_id="10")

    assert page.values == []
    assert page.is_last_page is True
    assert get.call_args.kwargs["allow_redirects"] is False
    # The patched Session.get is not bound, so the URL is the first argument.
    assert get.call_args.args[0] == f"{_BASE}/rest/servicedeskapi/request"
    assert "token" not in get.call_args.args[0]
    session, _root, is_cloud = cloud._client()
    assert is_cloud is True
    assert session.auth == ("ada@example.com", "token")
    params = get.call_args.kwargs["params"]
    assert params["serviceDeskId"] == "10"
    assert params["requestOwnership"] == "ALL_REQUESTS"
    assert params["requestStatus"] == "ALL_REQUESTS"


def test_cloud_session_uses_basic_auth_and_server_uses_bearer(
    cloud: JiraServiceManagementSourceOperations,
    server: JiraServiceManagementSourceOperations,
) -> None:
    myself = {"displayName": "Ada"}
    with patch.object(requests.Session, "get", return_value=_response(200, myself)):
        assert cloud.get_myself().display_name == "Ada"
    cloud_session, _root, is_cloud = cloud._client()
    assert is_cloud is True
    assert cloud_session.auth == ("ada@example.com", "token")

    with patch.object(requests.Session, "get", return_value=_response(200, myself)):
        server.get_myself()
    server_session, _root, is_cloud = server._client()
    assert is_cloud is False
    assert server_session.headers["Authorization"] == "Bearer pat"


def test_cloud_search_sends_the_token_and_server_search_sends_the_offset(
    cloud: JiraServiceManagementSourceOperations,
    server: JiraServiceManagementSourceOperations,
) -> None:
    cloud_get = MagicMock(
        return_value=_response(
            200,
            {
                "issues": [{"id": "1", "key": "IT-1"}],
                "isLast": False,
                "nextPageToken": "next",
            },
        )
    )
    with patch.object(requests.Session, "get", cloud_get):
        page = cloud.search_issues(jql='project = "IT"', next_page_token="cursor")
    assert page.uses_token is True
    assert page.next_page_token == "next"
    assert page.is_last is False
    assert cloud_get.call_args.args[0].endswith("/rest/api/3/search/jql")
    assert cloud_get.call_args.kwargs["params"]["nextPageToken"] == "cursor"

    server_get = MagicMock(
        return_value=_response(200, {"issues": [{"id": "1", "key": "IT-1"}]})
    )
    with patch.object(requests.Session, "get", server_get):
        page = server.search_issues(jql='project = "IT"', start_at=45, limit=50)
    assert page.uses_token is False
    assert page.is_last is True
    assert server_get.call_args.args[0].endswith("/rest/api/2/search")
    assert server_get.call_args.kwargs["params"]["startAt"] == 45


def test_a_missing_request_is_none_and_a_real_one_is_returned(
    cloud: JiraServiceManagementSourceOperations,
) -> None:
    get = MagicMock(
        side_effect=[
            _response(404, {"errorMessages": ["missing"]}),
            _response(
                200, {"issueId": "5", "issueKey": "IT-5", "requestFieldValues": []}
            ),
        ]
    )
    with patch.object(requests.Session, "get", get):
        assert cloud.get_request(issue_key="IT-4") is None
        found = cloud.get_request(issue_key="IT-5")
    assert found is not None
    assert found.issue_key == "IT-5"


def test_service_desk_lookup_pages_until_the_project_matches(
    cloud: JiraServiceManagementSourceOperations,
) -> None:
    first = {
        "isLastPage": False,
        "size": 1,
        "values": [
            {
                "id": "1",
                "projectId": "1",
                "projectKey": "HR",
                "projectName": "HR",
            }
        ],
    }
    second = {
        "isLastPage": True,
        "size": 1,
        "values": [
            {
                "id": "2",
                "projectId": "2",
                "projectKey": "IT",
                "projectName": "IT Help",
            }
        ],
    }
    get = MagicMock(side_effect=[_response(200, first), _response(200, second)])
    with patch.object(requests.Session, "get", get):
        desk = cloud.find_service_desk(project_key="it")
    assert desk.project_key == "IT"
    assert get.call_args_list[1].kwargs["params"]["start"] == 1


def test_a_missing_service_desk_names_the_project(
    cloud: JiraServiceManagementSourceOperations,
) -> None:
    get = MagicMock(return_value=_response(200, {"isLastPage": True, "values": []}))
    with (
        patch.object(requests.Session, "get", get),
        pytest.raises(ConnectorValidationError, match="IT"),
    ):
        cloud.find_service_desk(project_key="IT")


@pytest.mark.parametrize(
    "response, error",
    [
        (_response(401), CredentialInvalidError),
        (_response(403, {"errorMessages": ["no"]}), InsufficientPermissionsError),
        (
            _response(302, headers={"Location": "https://elsewhere.example/rest"}),
            ConnectorValidationError,
        ),
        (_response(500, {"errorMessages": ["down"]}), JsmApiError),
    ],
    ids=["401", "403", "redirect", "500"],
)
def test_each_status_maps_to_its_error(
    cloud: JiraServiceManagementSourceOperations,
    response: requests.Response,
    error: type[Exception],
) -> None:
    with (
        patch.object(requests.Session, "get", return_value=response),
        pytest.raises(error),
    ):
        cloud.get_myself()


def test_issue_timestamps_come_from_the_jira_issue(
    cloud: JiraServiceManagementSourceOperations,
) -> None:
    get = MagicMock(
        return_value=_response(
            200,
            {
                "key": "IT_HELP-1",
                "fields": {
                    "updated": "2024-06-01T12:00:00.000+0000",
                    "created": "2024-01-01T00:00:00.000+0000",
                },
            },
        )
    )
    with patch.object(requests.Session, "get", get):
        times = cloud.get_issue_timestamps(issue_key="IT_HELP-1")
    assert times.updated == "2024-06-01T12:00:00.000+0000"
    assert get.call_args.args[0].endswith("/rest/api/3/issue/IT_HELP-1")
    assert get.call_args.kwargs["params"]["fields"] == "updated,created"


def test_an_unsafe_issue_key_is_not_requested(
    cloud: JiraServiceManagementSourceOperations,
) -> None:
    with pytest.raises(ConnectorValidationError):
        cloud.get_request(issue_key="../admin")
