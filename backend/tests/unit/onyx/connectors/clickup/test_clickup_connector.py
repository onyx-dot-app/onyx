from typing import Any
from unittest.mock import MagicMock, patch

import requests

from onyx.connectors.clickup.connector import CLICKUP_API_BASE_URL, ClickupConnector
from onyx.connectors.models import TextSection

def _mock_response(json_response: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = json_response
    return response


def test_get_all_tasks_filtered_uses_relative_endpoint() -> None:
    connector = ClickupConnector(api_token="test-token", team_id="123")
    response = _mock_response({"tasks": []})

    with patch("onyx.connectors.clickup.connector.requests.get") as mock_get:
        mock_get.return_value = response

        list(connector._get_all_tasks_filtered())

    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == f"{CLICKUP_API_BASE_URL}/team/123/task"

def _mock_task(task_id: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "name": f"Task {task_id}",
        "url": f"https://clickup.com{task_id}",
        "description": "some description",
        "date_created": "1700000000000",
        "date_updated": "1700000000000",
        "creator": {"username": "alice", "email": "alice@example.com"},
        "assignees": [],
        "status": {"status": "open"},
        "list": {"name": "My List"},
        "project": {"name": "My Project"},
        "folder": {"name": "My Folder"},
        "space": {"id": "space-1"},
        "tags": [],
    }


def test_task_comment_fetch_failure_does_not_abort_indexing() -> None:
    connector = ClickupConnector(api_token="test-token", team_id="123")
    tasks_response = _mock_response(
        {"tasks": [_mock_task("task-1"), _mock_task("task-2")], "last_page": True}
    )

    def _mock_comments(task_id: str) -> list[TextSection]:
        if task_id == "task-1":
            raise requests.exceptions.RequestException("boom")
        return [TextSection(text="Valid Comment")]

    with patch("onyx.connectors.clickup.connector.requests.get") as mock_get, patch.object(
        ClickupConnector,
        "_get_task_comments",
        side_effect=_mock_comments,
    ):
        mock_get.return_value = tasks_response
        batches = list(connector._get_all_tasks_filtered())

    documents = [doc for batch in batches for doc in batch]
    assert [doc.id for doc in documents] == ["task-1", "task-2"]
    
    # task-1 fails comments, so it only has 1 description section
    assert len(documents[0].sections) == 1
    # task-2 succeeds, so it retains description + comment section (total 2)
    assert len(documents[1].sections) == 2


def test_get_task_comments_uses_relative_endpoint() -> None:
    connector = ClickupConnector(api_token="test-token")
    response = _mock_response(
        {
            "comments": [
                {
                    "id": "comment-1",
                    "comment_text": "Looks good",
                }
            ]
        }
    )

    with patch("onyx.connectors.clickup.connector.requests.get") as mock_get:
        mock_get.return_value = response

        sections = connector._get_task_comments("task-1")

    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == f"{CLICKUP_API_BASE_URL}/task/task-1/comment"
    assert sections[0].text == "Looks good"
