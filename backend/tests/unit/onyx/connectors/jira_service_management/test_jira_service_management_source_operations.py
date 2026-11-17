from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
)
from onyx.connectors.source_operations import get_source_operations_class

CREDENTIALS = {"jira_user_email": "user@example.com", "jira_api_token": "token"}


def _make_ops() -> JiraServiceManagementSourceOperations:
    return JiraServiceManagementSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, DocumentSource.JIRA_SERVICE_MANAGEMENT.value, CREDENTIALS
        ),
        connector_specific_config={
            "jira_base_url": "https://jsm.example.com",
            "scoped_token": False,
        },
    )


def _mock_response(payload: Any) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_gateway_registered_for_source() -> None:
    assert (
        get_source_operations_class(DocumentSource.JIRA_SERVICE_MANAGEMENT)
        is JiraServiceManagementSourceOperations
    )
    assert JiraServiceManagementSourceOperations.source == (
        DocumentSource.JIRA_SERVICE_MANAGEMENT
    )


def test_list_service_desks_parses_values() -> None:
    ops = _make_ops()
    client = MagicMock()
    client._session.get.return_value = _mock_response(
        {
            "values": [
                {"id": "1", "projectKey": "SD", "projectName": "Service Desk"},
                {"id": "2", "projectKey": "IT"},
                {"projectKey": "broken"},
            ]
        }
    )
    with patch.object(JiraServiceManagementSourceOperations, "_client", return_value=client):
        desks = ops.list_service_desks()

    assert [(d.id, d.project_key, d.project_name) for d in desks] == [
        ("1", "SD", "Service Desk"),
        ("2", "IT", None),
    ]
    url = client._session.get.call_args.args[0]
    assert url == "https://jsm.example.com/rest/servicedeskapi/servicedesk"


def test_get_request_uses_issue_key_in_path() -> None:
    ops = _make_ops()
    client = MagicMock()
    client._session.get.return_value = _mock_response(
        {"issueKey": "SD-1", "requestType": {"name": "Password reset"}}
    )
    with patch.object(JiraServiceManagementSourceOperations, "_client", return_value=client):
        request = ops.get_request(issue_key="SD-1")

    assert request.issue_key == "SD-1"
    assert request.request_type_name == "Password reset"
    url = client._session.get.call_args.args[0]
    assert url == "https://jsm.example.com/rest/servicedeskapi/request/SD-1"


def test_get_request_comments_paginates_until_last_page() -> None:
    ops = _make_ops()
    client = MagicMock()
    page1 = {
        "values": [{"id": "1", "public": True}, {"id": "2", "public": False}],
        "isLastPage": False,
    }
    page2 = {"values": [{"id": "3", "public": True}], "isLastPage": True}
    client._session.get.side_effect = [_mock_response(page1), _mock_response(page2)]
    with patch.object(JiraServiceManagementSourceOperations, "_client", return_value=client):
        comments = ops.get_request_comments(issue_key="SD-1")

    assert [c.id for c in comments] == ["1", "2", "3"]
    assert [c.public for c in comments] == [True, False, True]
    calls = client._session.get.call_args_list
    assert calls[0].kwargs["params"] == {"start": 0, "limit": 100}
    assert calls[1].kwargs["params"] == {"start": 2, "limit": 100}
    assert all(
        call.args[0] == "https://jsm.example.com/rest/servicedeskapi/request/SD-1/comment"
        for call in calls
    )


def test_get_request_comments_stops_on_short_page_without_flag() -> None:
    """Server / Data Center has no ``isLastPage``; a short page ends the walk."""
    ops = _make_ops()
    client = MagicMock()
    client._session.get.return_value = _mock_response(
        {"values": [{"id": "1", "public": True}], "size": 1}
    )
    with patch.object(JiraServiceManagementSourceOperations, "_client", return_value=client):
        comments = ops.get_request_comments(issue_key="SD-1")

    assert len(comments) == 1
    assert client._session.get.call_count == 1


def test_get_request_slas_parses_values() -> None:
    ops = _make_ops()
    client = MagicMock()
    client._session.get.return_value = _mock_response(
        {"values": [{"name": "TTR", "ongoingCycle": {"breached": True}}]}
    )
    with patch.object(JiraServiceManagementSourceOperations, "_client", return_value=client):
        slas = ops.get_request_slas(issue_key="SD-1")

    assert len(slas) == 1
    assert slas[0].name == "TTR"
    assert slas[0].breached is True
    url = client._session.get.call_args.args[0]
    assert url == "https://jsm.example.com/rest/servicedeskapi/request/SD-1/sla"


def test_api_error_raises_jira_api_error() -> None:
    import requests

    from onyx.connectors.jira.source_operations import JiraApiError

    ops = _make_ops()
    client = MagicMock()
    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    response.status_code = 403
    response.text = '{"errorMessages": ["no access"]}'
    response.request = MagicMock(method="GET")
    response.url = "https://jsm.example.com/rest/servicedeskapi/servicedesk"
    client._session.get.return_value = response
    with patch.object(JiraServiceManagementSourceOperations, "_client", return_value=client):
        with pytest.raises(JiraApiError) as exc_info:
            ops.list_service_desks()
    assert exc_info.value.status_code == 403
