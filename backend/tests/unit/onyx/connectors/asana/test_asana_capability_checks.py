"""The Asana checks name what is wrong: a rejected token, a workspace the
token cannot read (with the ones it can), archived projects, and a scope
without tasks or comments to sample. The gateway maps the SDK's errors."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from asana.rest import ApiException
from urllib3.exceptions import MaxRetryError, ReadTimeoutError

from onyx.configs.constants import DocumentSource
from onyx.connectors.asana.capability_checks import build_asana_indexing_checks
from onyx.connectors.asana.source_operations import (
    AsanaApiError,
    AsanaSourceOperations,
    _call,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CheckOutput,
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

_WORKSPACE = {"gid": "1", "name": "Acme"}


def _run(
    check_id: str, ops: MagicMock, config: dict[str, Any] | None = None
) -> CheckOutput | None:
    check = next(
        check for check in build_asana_indexing_checks() if check.check_id == check_id
    )
    return check.run(
        CapabilityCheckContext(
            source=DocumentSource.ASANA,
            credential_json={},
            connector_specific_config=config or {"asana_workspace_id": "1"},
            source_operations=ops,
        )
    )


def _ops() -> MagicMock:
    ops = create_autospec(AsanaSourceOperations, instance=True)
    ops.get_me.return_value = {
        "gid": "u",
        "email": "a@example.com",
        "workspaces": [_WORKSPACE],
    }
    ops.get_workspace.return_value = _WORKSPACE
    ops.iterate_projects.side_effect = lambda **_kwargs: iter(
        [{"gid": "2", "name": "Roadmap", "archived": False}]
    )
    ops.iterate_project_tasks.side_effect = lambda **_kwargs: iter(
        [{"gid": "4", "name": "Ship it", "created_by": {"gid": "u"}}]
    )
    ops.iterate_task_stories.side_effect = lambda **_kwargs: iter(
        [{"gid": "5", "resource_subtype": "comment_added"}]
    )
    return ops


def _not_found(path: str) -> AsanaApiError:
    return AsanaApiError(status_code=404, path=path, body=None)


def test_sign_in_names_the_user() -> None:
    output = _run("asana_token", _ops())

    assert output is not None
    assert output.summary == "Signed in as a@example.com"


def test_unexpected_status_is_wrapped() -> None:
    ops = _ops()
    ops.get_me.side_effect = AsanaApiError(status_code=500, path="/users/me", body=None)

    with pytest.raises(UnexpectedValidationError) as raised:
        _run("asana_token", ops)

    assert raised.value.__cause__ is ops.get_me.side_effect


def test_unknown_workspace_lists_the_readable_ones() -> None:
    ops = _ops()
    ops.get_workspace.side_effect = _not_found("/workspaces/42")

    with pytest.raises(ConnectorValidationError) as raised:
        _run("asana_workspace", ops, {"asana_workspace_id": "42"})

    assert raised.value.summary == "Workspace not found: 42"
    assert raised.value.description is not None
    assert "The token can read: Acme (1)." in raised.value.description


def test_archived_projects_pass_with_an_advisory() -> None:
    ops = _ops()
    ops.get_project.side_effect = lambda project_gid, **_kwargs: {
        "gid": project_gid,
        "name": f"P{project_gid}",
        "archived": project_gid == "3",
        "workspace": _WORKSPACE,
    }

    output = _run(
        "asana_projects", ops, {"asana_workspace_id": "1", "asana_project_ids": "2,3"}
    )

    assert output is not None
    assert output.summary == "Found all 2 projects"
    assert "Onyx skips archived projects: P3" in output.advisories[0].message


def test_tasks_sample_reads_a_comment_and_the_creator() -> None:
    ops = _ops()

    output = _run("asana_tasks", ops)

    assert output is not None
    assert output.summary == "Read task Ship it"
    assert output.advisories == []
    ops.get_story.assert_called_once()
    ops.get_user.assert_called_once_with(user_gid="u", opt_fields="name,email")


def test_empty_project_passes_with_an_advisory() -> None:
    ops = _ops()
    ops.iterate_project_tasks.side_effect = lambda **_kwargs: iter([])

    output = _run("asana_tasks", ops)

    assert output is not None
    assert "task and comment access were not checked" in output.advisories[0].message
    ops.iterate_task_stories.assert_not_called()


def test_no_project_in_scope_fails() -> None:
    ops = _ops()
    ops.iterate_projects.side_effect = lambda **_kwargs: iter([])

    with pytest.raises(ConnectorValidationError) as raised:
        _run("asana_tasks", ops)

    assert raised.value.summary == "No projects to index"
    assert ops.iterate_projects.call_args.kwargs["archived"] is False


def test_sample_skips_private_projects_of_other_teams() -> None:
    ops = _ops()
    ops.iterate_projects.side_effect = lambda **_kwargs: iter(
        [
            {
                "gid": "8",
                "name": "Secret",
                "privacy_setting": "private",
                "team": {"gid": "T2"},
            },
            {
                "gid": "2",
                "name": "Roadmap",
                "privacy_setting": "public",
                "team": {"gid": "T2"},
            },
        ]
    )

    output = _run(
        "asana_tasks", ops, {"asana_workspace_id": "1", "asana_team_id": "T1"}
    )

    assert output is not None
    assert output.summary == "Read task Ship it"
    assert ops.iterate_project_tasks.call_args.kwargs["project_gid"] == "2"


def test_sample_of_only_skipped_projects_is_inconclusive() -> None:
    ops = _ops()
    ops.iterate_projects.side_effect = lambda **_kwargs: iter(
        [
            {"gid": str(i), "privacy_setting": "private", "team": {"gid": "T2"}}
            for i in range(20)
        ]
    )

    output = _run(
        "asana_tasks", ops, {"asana_workspace_id": "1", "asana_team_id": "T1"}
    )

    assert output is not None
    assert "task access was not checked" in output.advisories[0].message
    ops.iterate_project_tasks.assert_not_called()


def _sdk_error(status: int) -> ApiException:
    error = ApiException(status=status, reason="error")
    error.body = b'{"errors":[{"message":"Not Authorized"}]}'
    return error


@pytest.mark.parametrize(
    ("status", "expected", "summary"),
    [
        (401, CredentialInvalidError, "Asana rejected the token"),
        (403, InsufficientPermissionsError, "Asana denied access"),
        (429, RateLimitedValidationError, "Rate limited by Asana"),
    ],
)
def test_gateway_maps_sdk_statuses_to_row_text(
    status: int, expected: type[ValidationError], summary: str
) -> None:
    def _fail() -> None:
        raise _sdk_error(status)

    with pytest.raises(expected) as raised:
        _call("/users/me", _fail)

    assert raised.value.summary == summary
    assert raised.value.description is not None
    if status == 401:
        assert "personal access token" in raised.value.description


def test_gateway_keeps_other_statuses_with_the_request_and_body() -> None:
    def _fail() -> None:
        raise _sdk_error(404)

    with pytest.raises(AsanaApiError) as raised:
        _call("/workspaces/abc", _fail)

    assert raised.value.not_found
    assert raised.value.url == "https://app.asana.com/api/1.0/workspaces/abc"
    assert raised.value.body == '{"errors":[{"message":"Not Authorized"}]}'


def test_gateway_maps_a_wrapped_connection_failure() -> None:
    def _fail() -> None:
        raise ApiException(status=0, reason="SSL handshake failed")

    with pytest.raises(UnreachableValidationError, match="SSL handshake failed"):
        _call("/users/me", _fail)


def test_gateway_maps_transport_failures() -> None:
    def _time_out() -> None:
        raise MaxRetryError(
            MagicMock(), "https://app.asana.com", ReadTimeoutError(MagicMock(), "", "")
        )

    def _refuse() -> None:
        raise MaxRetryError(MagicMock(), "https://app.asana.com")

    with pytest.raises(TimedOutValidationError):
        _call("/users/me", _time_out)
    with pytest.raises(UnreachableValidationError):
        _call("/users/me", _refuse)
