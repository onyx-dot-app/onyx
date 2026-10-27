"""Tests for Asana connector configuration parsing."""

from collections.abc import Iterator
from typing import Any, NamedTuple
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.connectors.asana.asana_api import AsanaAPI
from onyx.connectors.asana.connector import AsanaConnector
from onyx.connectors.asana.source_operations import (
    AsanaApiError,
    AsanaSourceOperations,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    TimedOutValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
    ValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError


class _AsanaTestSetup(NamedTuple):
    api: AsanaAPI
    ops: MagicMock


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
    """Construct an AsanaAPI over a mocked source-operations gateway.

    `project_to_tasks` maps each project gid to the tasks
    `iterate_project_tasks` will return when asked for that project.
    `project_metadata` lets a test override per-project metadata returned by
    `get_project` (the default is a public, team-bound, unarchived project).
    `team_gid` configures the API's team filter.

    Returns the api plus the gateway mock so tests can introspect call counts.
    """
    ops = create_autospec(AsanaSourceOperations, instance=True)
    api = AsanaAPI(ops=ops, workspace_gid="ws", team_gid=team_gid)

    default_metadata: dict[str, Any] = {
        "name": "p",
        "team": {"gid": "T1"},
        "archived": False,
        "privacy_setting": "public",
    }
    metadata_overrides = project_metadata or {}

    ops.iterate_projects.return_value = iter([{"gid": gid} for gid in project_to_tasks])

    def _get_project(project_gid: str, **_kwargs: Any) -> dict[str, Any]:
        return {**default_metadata, **metadata_overrides.get(project_gid, {})}

    ops.get_project.side_effect = _get_project

    def _iterate_project_tasks(
        project_gid: str, **_kwargs: Any
    ) -> Iterator[dict[str, Any]]:
        return iter(project_to_tasks.get(project_gid, []))

    ops.iterate_project_tasks.side_effect = _iterate_project_tasks
    ops.iterate_task_stories.return_value = iter([])

    return _AsanaTestSetup(api=api, ops=ops)


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
    assert setup.ops.iterate_task_stories.call_count == 3
    fetched_gids = [
        call.kwargs["task_gid"]
        for call in setup.ops.iterate_task_stories.call_args_list
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
    assert setup.ops.iterate_task_stories.call_count == 3


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


def _connector_with_ops(
    ops: MagicMock,
    asana_project_ids: str | None = None,
    asana_team_id: str | None = None,
) -> AsanaConnector:
    connector = AsanaConnector(
        asana_workspace_id="123",
        asana_project_ids=asana_project_ids,
        asana_team_id=asana_team_id,
    )
    connector._ops = ops
    return connector


def _api_error(status: int | None, *, timed_out: bool = False) -> AsanaApiError:
    return AsanaApiError(
        f"Asana answered {status}",
        status_code=status,
        method="GET",
        url="https://app.asana.com/api/1.0/workspaces/123",
        timed_out=timed_out,
    )


def _ops() -> MagicMock:
    ops = create_autospec(AsanaSourceOperations, instance=True)
    ops.get_workspace.return_value = {"gid": "123", "name": "Acme"}
    ops.get_me.return_value = {
        "gid": "u",
        "workspaces": [{"gid": "999", "name": "Other"}],
    }
    return ops


def test_validate_connector_settings_requires_credentials() -> None:
    connector = AsanaConnector(asana_workspace_id="123")
    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()


def test_load_credentials_builds_the_gateway() -> None:
    connector = AsanaConnector(asana_workspace_id="123")
    connector.load_credentials({"asana_api_token_secret": "token"})
    assert isinstance(connector.ops, AsanaSourceOperations)


def test_validate_connector_settings_reads_configured_workspace() -> None:
    ops = _ops()
    _connector_with_ops(ops).validate_connector_settings()
    ops.get_workspace.assert_called_once_with(workspace_gid="123")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, ConnectorValidationError),
        (404, ConnectorValidationError),
        (403, InsufficientPermissionsError),
    ],
)
def test_unknown_workspace_names_the_readable_ones(
    status: int, expected: type[Exception]
) -> None:
    ops = _ops()
    ops.get_workspace.side_effect = _api_error(status)

    with pytest.raises(expected) as raised:
        _connector_with_ops(ops).validate_connector_settings()

    error = raised.value
    assert isinstance(error, ValidationError)
    assert error.summary == "Workspace not found: 123"
    assert error.description is not None
    assert "The token can read: Other (999)." in error.description


@pytest.mark.parametrize(
    ("error", "expected", "summary"),
    [
        (_api_error(401), CredentialInvalidError, "Asana rejected the token"),
        (_api_error(429), RateLimitedValidationError, "Rate limited by Asana"),
        (_api_error(500), UnexpectedValidationError, "Asana had a server error"),
        (_api_error(None), UnreachableValidationError, "Cannot reach Asana"),
        (
            _api_error(None, timed_out=True),
            TimedOutValidationError,
            "Timed out",
        ),
    ],
)
def test_workspace_errors_map_to_row_text(
    error: AsanaApiError, expected: type[ValidationError], summary: str
) -> None:
    ops = _ops()
    ops.get_workspace.side_effect = error

    with pytest.raises(expected) as raised:
        _connector_with_ops(ops).validate_connector_settings()

    assert raised.value.summary == summary
    assert raised.value.__cause__ is error


def test_unusable_projects_are_named_in_one_error() -> None:
    ops = _ops()

    def _get_project(project_gid: str, **_kwargs: Any) -> dict[str, Any]:
        if project_gid == "1":
            raise _api_error(404)
        if project_gid == "2":
            return {"gid": "2", "name": "Elsewhere", "workspace": {"gid": "999"}}
        return {"gid": project_gid, "name": "Ok", "workspace": {"gid": "123"}}

    ops.get_project.side_effect = _get_project
    connector = _connector_with_ops(ops, asana_project_ids="1,2,3")

    with pytest.raises(ConnectorValidationError) as raised:
        connector.validate_connector_settings()

    assert raised.value.summary == "2 of 3 projects not usable"
    assert "Not found: 1." in raised.value.message
    assert "In another workspace: 2." in raised.value.message


def test_team_in_another_workspace_fails() -> None:
    ops = _ops()
    ops.get_team.return_value = {
        "gid": "7",
        "name": "Eng",
        "organization": {"gid": "999"},
    }
    connector = _connector_with_ops(ops, asana_team_id="7")

    with pytest.raises(ConnectorValidationError) as raised:
        connector.validate_connector_settings()

    assert raised.value.summary == "Team is in another workspace"


def test_team_is_not_read_when_projects_are_set() -> None:
    ops = _ops()
    ops.get_project.return_value = {"gid": "1", "workspace": {"gid": "123"}}
    connector = _connector_with_ops(ops, asana_project_ids="1", asana_team_id="7")

    connector.validate_connector_settings()

    ops.get_team.assert_not_called()
