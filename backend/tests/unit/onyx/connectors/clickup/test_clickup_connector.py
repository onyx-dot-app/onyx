from typing import Any
from unittest.mock import MagicMock, patch

from onyx.connectors.clickup.connector import CLICKUP_API_BASE_URL, ClickupConnector


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


def test_build_document_handles_missing_optional_fields() -> None:
    connector = ClickupConnector(api_token="test-token", retrieve_task_comments=False)

    task = {
        "id": "task-1",
        "name": "A task with no folder/project and a hidden creator email",
        "date_updated": "1700000000000",
        "date_created": "1699000000000",
        "url": "https://app.clickup.com/t/task-1",
        "description": "some description",
        "creator": {"username": "alice"},
        "assignees": [],
        "folder": None,
        "project": None,
        "list": {"name": "Backlog"},
        "space": {"id": "space-1"},
        "status": {"status": "open"},
        "tags": [],
        "priority": None,
    }

    document = connector._build_document_from_task(task)

    assert document.id == "task-1"
    assert document.primary_owners is not None
    assert document.primary_owners[0].display_name == "alice"
    assert document.primary_owners[0].email is None
    assert document.metadata["folder"] == ""
    assert document.metadata["project"] == ""


def test_get_all_tasks_filtered_skips_malformed_task_without_crashing() -> None:
    connector = ClickupConnector(
        api_token="test-token", team_id="123", retrieve_task_comments=False
    )
    bad_task = {"id": "bad-task"}
    good_task = {
        "id": "good-task",
        "name": "Fine task",
        "date_updated": "1700000000000",
        "date_created": "1699000000000",
        "url": "https://app.clickup.com/t/good-task",
        "description": "",
        "creator": {"username": "bob", "email": "bob@example.com"},
        "assignees": [],
        "folder": {"name": "F"},
        "project": {"name": "P"},
        "list": {"name": "L"},
        "space": {"id": "space-1"},
        "status": {"status": "open"},
        "tags": [],
        "priority": None,
    }
    response = _mock_response({"tasks": [bad_task, good_task], "last_page": True})

    with patch("onyx.connectors.clickup.connector.requests.get") as mock_get:
        mock_get.return_value = response
        batches = list(connector._get_all_tasks_filtered())

    docs = [doc for batch in batches for doc in batch]
    assert len(docs) == 1
    assert docs[0].id == "good-task"