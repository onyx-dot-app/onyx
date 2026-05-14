"""Tests for Asana connector configuration parsing."""

from collections.abc import Iterator
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
    *,
    team_gid: str | None = None,
    project_metadata: dict[str, dict[str, Any]] | None = None,
) -> _AsanaTestSetup:
    """Construct an AsanaAPI with all SDK clients replaced by mocks.

    `project_to_tasks` maps each project gid to the tasks `get_tasks_for_project`
    will return when asked for that project. `project_metadata` lets a test
    override per-project metadata returned by `get_project` (the default is a
    public, team-bound, unarchived project). `team_gid` configures the API's
    team filter.

    Returns the api plus the stories-api mock so tests can introspect call
    counts without fighting `ty` type inference on the original SDK attributes.
    """
    with patch("onyx.connectors.asana.asana_api.asana"):
        api = AsanaAPI(api_token="token", workspace_gid="ws", team_gid=team_gid)

    project_api = MagicMock()
    tasks_api = MagicMock()
    stories_api = MagicMock()
    users_api = MagicMock()

    api.project_api = project_api
    api.tasks_api = tasks_api
    api.stories_api = stories_api
    api.users_api = users_api

    default_metadata: dict[str, Any] = {
        "name": "p",
        "team": {"gid": "T1"},
        "archived": False,
        "privacy_setting": "public",
    }
    metadata_overrides = project_metadata or {}

    project_api.get_projects.return_value = iter(
        [{"gid": gid} for gid in project_to_tasks]
    )

    def _get_project(gid: str, **_kwargs: Any) -> dict[str, Any]:
        return {**default_metadata, **metadata_overrides.get(gid, {})}

    project_api.get_project.side_effect = _get_project

    def _get_tasks_for_project(
        gid: str, *_args: Any, **_kwargs: Any
    ) -> Iterator[dict[str, Any]]:
        return iter(project_to_tasks.get(gid, []))

    tasks_api.get_tasks_for_project.side_effect = _get_tasks_for_project
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


def test_get_tasks_processes_teamless_project_when_no_team_filter() -> None:
    """A workspace-level project (team=None) must still be indexed when no
    team filter is configured. The earlier `if not team_gid: return` skip
    silently dropped these and produced 0/0 syncs in production."""
    setup = _build_api_with_mocks(
        {"P1": [_make_task_data("A")]},
        team_gid=None,
        project_metadata={"P1": {"team": None}},
    )

    yielded = list(
        setup.api.get_tasks(project_gids=None, start_date="2026-01-01T00:00:00+00:00")
    )

    assert [t.id for t in yielded] == ["A"]


def test_get_tasks_processes_teamless_projects_when_explicitly_allowlisted() -> None:
    """Customer's exact scenario from the Slack thread: three projects are
    explicitly listed in `asana_project_ids`, every one of them returns
    team=None from Asana, and the connector also has a `team_gid` configured.
    Before the fix, every project was dropped at the `no team` skip and the
    sync reported success with 0 documents."""
    setup = _build_api_with_mocks(
        {
            "P1": [_make_task_data("A")],
            "P2": [_make_task_data("B")],
            "P3": [_make_task_data("C")],
        },
        team_gid="T_CONFIGURED",
        project_metadata={
            "P1": {"team": None},
            "P2": {"team": None},
            "P3": {"team": None},
        },
    )

    yielded = list(
        setup.api.get_tasks(
            project_gids=["P1", "P2", "P3"],
            start_date="2026-01-01T00:00:00+00:00",
        )
    )

    assert [t.id for t in yielded] == ["A", "B", "C"]


def test_get_tasks_skips_private_project_in_wrong_team() -> None:
    """When a team filter is configured and the user did not allowlist a
    private project that belongs to a different team, the connector must
    still skip it — the team filter is the user's scope-narrowing tool."""
    setup = _build_api_with_mocks(
        {
            "P_IN": [_make_task_data("A")],
            "P_OUT": [_make_task_data("B")],
        },
        team_gid="T_CONFIGURED",
        project_metadata={
            "P_IN": {"team": {"gid": "T_CONFIGURED"}, "privacy_setting": "private"},
            "P_OUT": {"team": {"gid": "T_OTHER"}, "privacy_setting": "private"},
        },
    )

    yielded = list(
        setup.api.get_tasks(project_gids=None, start_date="2026-01-01T00:00:00+00:00")
    )

    assert [t.id for t in yielded] == ["A"]


def test_get_tasks_processes_private_wrong_team_project_when_allowlisted() -> None:
    """An explicit allowlist overrides the team filter even for private
    projects — the user knows what they want."""
    setup = _build_api_with_mocks(
        {"P_OUT": [_make_task_data("B")]},
        team_gid="T_CONFIGURED",
        project_metadata={
            "P_OUT": {"team": {"gid": "T_OTHER"}, "privacy_setting": "private"},
        },
    )

    yielded = list(
        setup.api.get_tasks(
            project_gids=["P_OUT"], start_date="2026-01-01T00:00:00+00:00"
        )
    )

    assert [t.id for t in yielded] == ["B"]


def test_get_tasks_skips_private_teamless_project_with_team_filter_and_no_allowlist() -> (
    None
):
    """A private, teamless project cannot satisfy the configured team filter
    (None is never equal to a real team gid), so it must be skipped when the
    user did not explicitly allowlist it. Pins the corner that emerges from
    the new compound skip condition so future refactors of that branch don't
    silently flip its behavior."""
    setup = _build_api_with_mocks(
        {"P_NULL": [_make_task_data("A")]},
        team_gid="T_CONFIGURED",
        project_metadata={
            "P_NULL": {"team": None, "privacy_setting": "private"},
        },
    )

    yielded = list(
        setup.api.get_tasks(project_gids=None, start_date="2026-01-01T00:00:00+00:00")
    )

    assert yielded == []


def test_get_tasks_processes_public_teamless_project_with_team_filter_and_no_allowlist() -> (
    None
):
    """Public projects are not subject to the team filter — only the
    `private` branch applies it. A teamless public project must therefore
    still index when no allowlist is supplied, even with a team filter
    configured. Pins the symmetric counterpart of the private skip above."""
    setup = _build_api_with_mocks(
        {"P_NULL": [_make_task_data("A")]},
        team_gid="T_CONFIGURED",
        project_metadata={
            "P_NULL": {"team": None, "privacy_setting": "public"},
        },
    )

    yielded = list(
        setup.api.get_tasks(project_gids=None, start_date="2026-01-01T00:00:00+00:00")
    )

    assert [t.id for t in yielded] == ["A"]


def test_get_tasks_skips_archived_project_even_when_allowlisted() -> None:
    """The archived filter is unconditional — even an explicit allowlist
    shouldn't pull tasks from an archived project (they are read-only and
    typically already indexed)."""
    setup = _build_api_with_mocks(
        {"P_ARCHIVED": [_make_task_data("X")]},
        project_metadata={"P_ARCHIVED": {"archived": True}},
    )

    yielded = list(
        setup.api.get_tasks(
            project_gids=["P_ARCHIVED"], start_date="2026-01-01T00:00:00+00:00"
        )
    )

    assert yielded == []
