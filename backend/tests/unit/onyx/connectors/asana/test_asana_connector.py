"""Tests for Asana connector configuration parsing."""

from typing import Any
from typing import NamedTuple
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.asana.asana_api import AsanaAPI
from onyx.connectors.asana.connector import AsanaConnector


class _AsanaTestSetup(NamedTuple):
    api: AsanaAPI
    stories_api: MagicMock


@pytest.mark.parametrize(
    "project_ids,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        (" 123 ", ["123"]),
        (" 123 , , 456 , ", ["123", "456"]),
    ],
)
def test_asana_connector_project_ids_normalization(
    project_ids: str | None, expected: list[str] | None
) -> None:
    connector = AsanaConnector(
        asana_workspace_id=" 1153293530468850 ",
        asana_project_ids=project_ids,
        asana_team_id=" 1210918501948021 ",
    )

    assert connector.workspace_id == "1153293530468850"
    assert connector.project_ids_to_index == expected
    assert connector.asana_team_id == "1210918501948021"


@pytest.mark.parametrize(
    "team_id,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        (" 1210918501948021 ", "1210918501948021"),
    ],
)
def test_asana_connector_team_id_normalization(
    team_id: str | None, expected: str | None
) -> None:
    connector = AsanaConnector(
        asana_workspace_id="1153293530468850",
        asana_project_ids=None,
        asana_team_id=team_id,
    )

    assert connector.asana_team_id == expected


def _make_task_data(gid: str, name: str | None = None) -> dict[str, Any]:
    """Minimal Asana task payload covering the fields the connector reads."""
    return {
        "gid": gid,
        "name": name or f"task-{gid}",
        "notes": "",
        "created_by": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "due_on": None,
        "completed_at": None,
        "modified_at": "2026-01-01T00:00:00+00:00",
        "permalink_url": f"https://app.asana.com/0/{gid}",
    }


def _build_api_with_mocks(
    project_to_tasks: dict[str, list[dict[str, Any]]],
) -> _AsanaTestSetup:
    """Construct an AsanaAPI with all SDK clients replaced by mocks.

    `project_to_tasks` defines, in iteration order, the tasks each project
    listing returns from `tasks_api.get_tasks_for_project`. Returns the api
    plus the stories-api mock so tests can introspect call counts without
    fighting `ty` type inference on the original SDK attributes.
    """
    with patch("onyx.connectors.asana.asana_api.asana"):
        api = AsanaAPI(api_token="token", workspace_gid="ws", team_gid=None)

    project_api = MagicMock()
    tasks_api = MagicMock()
    stories_api = MagicMock()
    users_api = MagicMock()

    api.project_api = project_api
    api.tasks_api = tasks_api
    api.stories_api = stories_api
    api.users_api = users_api

    project_api.get_projects.return_value = iter(
        [{"gid": gid} for gid in project_to_tasks]
    )
    project_api.get_project.return_value = {
        "name": "p",
        "team": {"gid": "T1"},
        "archived": False,
        "privacy_setting": "public",
    }
    tasks_api.get_tasks_for_project.side_effect = [
        iter(tasks) for tasks in project_to_tasks.values()
    ]
    stories_api.get_stories_for_task.return_value = iter([])

    return _AsanaTestSetup(api=api, stories_api=stories_api)


def test_get_tasks_dedupes_task_appearing_in_multiple_projects() -> None:
    """An Asana task in N projects is yielded once per poll, and the expensive
    `_fetch_and_add_comments` call only fires for unique tasks."""
    setup = _build_api_with_mocks(
        {
            "P1": [_make_task_data("X"), _make_task_data("Y")],
            "P2": [_make_task_data("X"), _make_task_data("Z")],
        }
    )

    yielded = list(
        setup.api.get_tasks(project_gids=None, start_date="2026-01-01T00:00:00+00:00")
    )

    assert [t.id for t in yielded] == ["X", "Y", "Z"]
    assert setup.api.task_count == 3
    # Comments fetched only for unique tasks; the duplicate X is skipped before
    # `_fetch_and_add_comments` runs.
    assert setup.stories_api.get_stories_for_task.call_count == 3
    fetched_gids = [
        call.args[0] for call in setup.stories_api.get_stories_for_task.call_args_list
    ]
    assert sorted(fetched_gids) == ["X", "Y", "Z"]


def test_get_tasks_no_duplicates_unchanged() -> None:
    """When projects don't share tasks, every task is yielded and counters
    reflect zero duplicates."""
    setup = _build_api_with_mocks(
        {
            "P1": [_make_task_data("A"), _make_task_data("B")],
            "P2": [_make_task_data("C")],
        }
    )

    yielded = list(
        setup.api.get_tasks(project_gids=None, start_date="2026-01-01T00:00:00+00:00")
    )

    assert [t.id for t in yielded] == ["A", "B", "C"]
    assert setup.api.task_count == 3
    assert setup.stories_api.get_stories_for_task.call_count == 3
