"""The Asana checks name what is wrong: a rejected token, a workspace the
token cannot read (with the ones it can), archived projects, and a scope
without tasks or comments to sample."""

import json
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from asana.rest import ApiException

from onyx.configs.constants import DocumentSource
from onyx.connectors.asana.capability_checks import build_asana_indexing_checks
from onyx.connectors.asana.source_operations import (
    AsanaApiError,
    AsanaSourceOperations,
    _translated,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CheckOutput,
)
from onyx.connectors.exceptions import ConnectorValidationError, CredentialInvalidError

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


def _error(status: int) -> AsanaApiError:
    return AsanaApiError(
        f"Asana answered {status}",
        status_code=status,
        method="GET",
        url="https://app.asana.com/api/1.0/users/me",
    )


def test_sign_in_names_the_user() -> None:
    output = _run("asana_token", _ops())

    assert output is not None
    assert output.summary == "Signed in as a@example.com"


def test_rejected_token_says_how_to_get_a_new_one() -> None:
    ops = _ops()
    ops.get_me.side_effect = _error(401)

    with pytest.raises(CredentialInvalidError) as raised:
        _run("asana_token", ops)

    assert raised.value.summary == "Asana rejected the token"
    assert raised.value.description is not None
    assert "personal access token" in raised.value.description


def test_unknown_workspace_lists_the_readable_ones() -> None:
    ops = _ops()
    ops.get_workspace.side_effect = _error(404)

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
    ops.iterate_projects.side_effect = lambda **_kwargs: iter(
        [{"gid": "2", "archived": True}]
    )

    with pytest.raises(ConnectorValidationError) as raised:
        _run("asana_tasks", ops)

    assert raised.value.summary == "No projects to index"


def test_sdk_errors_carry_asana_s_message_and_the_request() -> None:
    sdk_error = ApiException(status=400, reason="Bad Request")
    sdk_error.body = json.dumps(
        {"errors": [{"message": "workspace: Not a recognized ID: abc"}]}
    ).encode()

    def _fail() -> None:
        raise sdk_error

    with pytest.raises(AsanaApiError) as raised:
        _translated("GET", "/workspaces/abc", _fail)

    assert raised.value.status_code == 400
    assert raised.value.asana_message == "workspace: Not a recognized ID: abc"
    assert raised.value.url == "https://app.asana.com/api/1.0/workspaces/abc"
    assert raised.value.body is not None
