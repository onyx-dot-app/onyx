from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.utils import JIRA_SERVER_API_VERSION
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _mock_jira_client(jira_base_url: str) -> MagicMock:
    client = MagicMock(spec=JIRA)
    client._options = {
        "server": jira_base_url,
        "rest_api_version": JIRA_SERVER_API_VERSION,
    }
    client._session = MagicMock()
    client.search_issues = MagicMock()
    return client


def _mock_issue(key: str = "SUP-1") -> MagicMock:
    issue = MagicMock(spec=Issue)
    issue.key = key
    issue.raw = {"fields": {"description": "Need VPN access for onboarding."}}
    issue.fields = SimpleNamespace(
        summary="VPN access request",
        updated="2025-01-01T12:00:00.000+0000",
        description="Need VPN access for onboarding.",
        labels=[],
        comment=SimpleNamespace(comments=[]),
        reporter=None,
        assignee=None,
        priority=None,
        status=SimpleNamespace(name="Waiting for support"),
        resolution=None,
        created="2025-01-01T11:00:00.000+0000",
        duedate=None,
        issuetype=SimpleNamespace(name="Service Request"),
        parent=None,
        project=SimpleNamespace(key="SUP", name="Support Desk"),
        resolutiondate=None,
    )
    return issue


def test_service_management_load_uses_existing_jira_search_path() -> None:
    jira_base_url = "https://jira.example.com"
    client = _mock_jira_client(jira_base_url)
    client._session.get.return_value = _mock_response({"id": "12", "projectKey": "SUP"})
    client.search_issues.return_value = [_mock_issue()]

    connector = JiraConnector(
        jira_base_url=jira_base_url,
        project_key="SUP",
        jira_service_management=True,
    )
    connector._jira_client = client

    outputs = load_everything_from_checkpoint_connector(connector, 0, 1)

    assert len(outputs) == 1
    assert outputs[0].next_checkpoint.has_more is False
    assert outputs[0].next_checkpoint.offset == 1
    assert len(outputs[0].items) == 1

    document = outputs[0].items[0]
    assert isinstance(document, Document)
    assert document.id == "https://jira.example.com/browse/SUP-1"
    assert document.metadata["project"] == "SUP"
    assert "service_desk_id" not in document.metadata
    assert "Jira Service Management request fields:" not in document.sections[0].text

    client._session.get.assert_called_once()
    service_desk_call = client._session.get.call_args
    assert (
        service_desk_call.args[0]
        == "https://jira.example.com/rest/servicedeskapi/servicedesk/projectKey:SUP"
    )

    client.search_issues.assert_called_once()
    search_call = client.search_issues.call_args
    assert 'project = "SUP"' in search_call.kwargs["jql_str"]
    assert search_call.kwargs["startAt"] == 0
    assert search_call.kwargs["maxResults"] == 50


def test_service_management_permission_sync_is_unsupported() -> None:
    connector = JiraConnector(
        jira_base_url="https://jira.example.com",
        project_key="SUP",
        jira_service_management=True,
    )

    with pytest.raises(ConnectorValidationError, match="permission sync"):
        connector.load_from_checkpoint_with_perm_sync(
            0,
            1,
            connector.build_dummy_checkpoint(),
        )

    with pytest.raises(ConnectorValidationError, match="permission sync"):
        list(connector.retrieve_all_slim_docs_perm_sync())


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({}, "requires a Jira project key"),
        ({"project_key": "SUP", "jql_query": "project = SUP"}, "custom JQL"),
    ],
)
def test_service_management_rejects_unsupported_configuration(
    config: dict[str, str],
    message: str,
) -> None:
    jira_base_url = "https://jira.example.com"
    client = _mock_jira_client(jira_base_url)
    connector = JiraConnector(
        jira_base_url=jira_base_url,
        jira_service_management=True,
        **config,
    )
    connector._jira_client = client

    with pytest.raises(ConnectorValidationError, match=message):
        connector.validate_connector_settings()

    client._session.get.assert_not_called()
