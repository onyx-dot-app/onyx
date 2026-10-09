from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from jira import JIRA
from jira.exceptions import JIRAError

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira.source_operations import (
    _JIRA_BULK_FETCH_LIMIT,
    JiraApiError,
    JiraSourceOperations,
    is_cloud_credential,
    is_cloud_gateway,
)


def _make_raw_issue(issue_id: str) -> dict[str, Any]:
    return {
        "id": issue_id,
        "key": f"TEST-{issue_id}",
        "fields": {"summary": f"Issue {issue_id}"},
    }


def _mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock._options = {"server": "https://jira.example.com"}
    mock._session = MagicMock()
    mock._get_url = MagicMock(
        return_value="https://jira.example.com/rest/api/3/issue/bulkfetch"
    )
    return mock


def _gateway(
    client: MagicMock | None = None,
    credentials: dict[str, Any] | None = None,
) -> JiraSourceOperations:
    gateway = JiraSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None,
            DocumentSource.JIRA.value,
            credentials
            if credentials is not None
            else {"jira_user_email": "user@example.com", "jira_api_token": "token"},
        ),
        connector_specific_config={"jira_base_url": "https://jira.example.com"},
    )
    gateway._cached_client = client
    return gateway


def test_bulk_fetch_success() -> None:
    """Happy path: all issues fetched in one request."""
    client = _mock_jira_client()
    raw = [_make_raw_issue("1"), _make_raw_issue("2"), _make_raw_issue("3")]
    resp = MagicMock()
    resp.json.return_value = {"issues": raw}
    client._session.post.return_value = resp

    result = _gateway(client).bulk_fetch_issues(issue_ids=["1", "2", "3"])
    assert result == raw
    client._session.post.assert_called_once()


def test_bulk_fetch_splits_on_json_error() -> None:
    """When the full batch fails with JSONDecodeError, sub-batches succeed."""
    client = _mock_jira_client()

    call_count = 0

    def _post_side_effect(url: str, json: dict[str, Any]) -> MagicMock:  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        ids = json["issueIdsOrKeys"]
        if len(ids) > 2:
            resp = MagicMock()
            resp.json.side_effect = requests.exceptions.JSONDecodeError(
                "Expecting ',' delimiter", "doc", 2294125
            )
            return resp

        resp = MagicMock()
        resp.json.return_value = {"issues": [_make_raw_issue(i) for i in ids]}
        return resp

    client._session.post.side_effect = _post_side_effect

    result = _gateway(client).bulk_fetch_issues(issue_ids=["1", "2", "3", "4"])
    assert {r["id"] for r in result} == {"1", "2", "3", "4"}
    assert call_count > 1


def test_bulk_fetch_raises_on_single_unfetchable_issue() -> None:
    """A single issue that always fails JSON decode raises after splitting."""
    client = _mock_jira_client()

    def _post_side_effect(url: str, json: dict[str, Any]) -> MagicMock:  # noqa: ARG001
        ids = json["issueIdsOrKeys"]
        if "bad" in ids:
            resp = MagicMock()
            resp.json.side_effect = requests.exceptions.JSONDecodeError(
                "Expecting ',' delimiter", "doc", 100
            )
            return resp

        resp = MagicMock()
        resp.json.return_value = {"issues": [_make_raw_issue(i) for i in ids]}
        return resp

    client._session.post.side_effect = _post_side_effect

    with pytest.raises(requests.exceptions.JSONDecodeError):
        _gateway(client).bulk_fetch_issues(issue_ids=["1", "bad", "2"])


def test_bulk_fetch_non_json_error_propagates() -> None:
    """Non-JSONDecodeError exceptions still propagate."""
    client = _mock_jira_client()

    resp = MagicMock()
    resp.json.side_effect = ValueError("something else broke")
    client._session.post.return_value = resp

    with pytest.raises(ValueError):
        _gateway(client).bulk_fetch_issues(issue_ids=["1"])


def test_bulk_fetch_with_fields() -> None:
    """Fields parameter is forwarded correctly."""
    client = _mock_jira_client()
    raw = [_make_raw_issue("1")]
    resp = MagicMock()
    resp.json.return_value = {"issues": raw}
    client._session.post.return_value = resp

    _gateway(client).bulk_fetch_issues(issue_ids=["1"], fields="summary,description")

    call_payload = client._session.post.call_args[1]["json"]
    assert call_payload["fields"] == ["summary", "description"]


def test_bulk_fetch_recursive_splitting_raises_on_bad_issue() -> None:
    """With a 6-issue batch where one is bad, recursion isolates it and raises."""
    client = _mock_jira_client()
    bad_id = "BAD"

    def _post_side_effect(url: str, json: dict[str, Any]) -> MagicMock:  # noqa: ARG001
        ids = json["issueIdsOrKeys"]
        if bad_id in ids:
            resp = MagicMock()
            resp.json.side_effect = requests.exceptions.JSONDecodeError(
                "truncated", "doc", 999
            )
            return resp

        resp = MagicMock()
        resp.json.return_value = {"issues": [_make_raw_issue(i) for i in ids]}
        return resp

    client._session.post.side_effect = _post_side_effect

    with pytest.raises(requests.exceptions.JSONDecodeError):
        _gateway(client).bulk_fetch_issues(issue_ids=["1", "2", bad_id, "3", "4", "5"])


def test_bulk_fetch_respects_api_batch_limit() -> None:
    """Requests to the bulkfetch endpoint never exceed _JIRA_BULK_FETCH_LIMIT IDs."""
    client = _mock_jira_client()
    total_issues = _JIRA_BULK_FETCH_LIMIT * 3 + 7
    all_ids = [str(i) for i in range(total_issues)]

    batch_sizes: list[int] = []

    def _post_side_effect(url: str, json: dict[str, Any]) -> MagicMock:  # noqa: ARG001
        ids = json["issueIdsOrKeys"]
        batch_sizes.append(len(ids))
        resp = MagicMock()
        resp.json.return_value = {"issues": [_make_raw_issue(i) for i in ids]}
        return resp

    client._session.post.side_effect = _post_side_effect

    result = _gateway(client).bulk_fetch_issues(issue_ids=all_ids)

    assert len(result) == total_issues
    # keeping this hardcoded because it's the documented limit
    # https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
    assert all(size <= 100 for size in batch_sizes)
    assert len(batch_sizes) == 4


def test_sdk_errors_become_jira_api_errors() -> None:
    client = _mock_jira_client()
    client.project.side_effect = JIRAError(
        status_code=404, text='{"errorMessages":["No project could be found"]}'
    )

    with pytest.raises(JiraApiError) as exc_info:
        _gateway(client).get_project(project_key="NOPE")

    assert exc_info.value.status_code == 404
    assert "No project could be found" in (exc_info.value.text or "")


def test_http_errors_become_jira_api_errors() -> None:
    client = _mock_jira_client()
    response = requests.Response()
    response.status_code = 400
    response._content = b'{"errorMessages":["Error in the JQL Query"]}'
    client._session.get.return_value.raise_for_status.side_effect = requests.HTTPError(
        response=response
    )

    with pytest.raises(JiraApiError) as exc_info:
        _gateway(client).search_issue_ids(jql="project = AS")

    assert exc_info.value.status_code == 400
    assert "Error in the JQL Query" in (exc_info.value.text or "")


@pytest.mark.parametrize(
    "credentials,expected_cloud",
    [
        ({"jira_user_email": "user@example.com", "jira_api_token": "t"}, True),
        ({"jira_api_token": "t"}, False),
    ],
    ids=["email-is-cloud", "token-only-is-server"],
)
def test_credential_selects_the_api_family(
    credentials: dict[str, Any], expected_cloud: bool
) -> None:
    assert is_cloud_credential(credentials) is expected_cloud
    assert is_cloud_gateway(_gateway(credentials=credentials)) is expected_cloud
