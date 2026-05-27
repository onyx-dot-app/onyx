from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.clickup.connector import CLICKUP_API_BASE_URL
from onyx.connectors.clickup.connector import ClickupConnector


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
