"""The group sync fills one group per team the token can see and the
workspace members group, and refuses a users listing Linear cut short."""

from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from ee.onyx.configs.app_configs import LINEAR_PERMISSION_GROUP_SYNC_FREQUENCY
from ee.onyx.external_permissions.linear.group_sync import (
    linear_group_sync,
    team_groups,
)
from ee.onyx.external_permissions.sync_params import (
    get_source_perm_sync_config,
    source_requires_external_group_sync,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.linear.models import LinearTeam, LinearUser, WorkspaceUsers
from onyx.connectors.linear.source_operations import LinearSourceOperations

CONNECTOR = "ee.onyx.external_permissions.linear.connector"


def _user(email: str, **flags: bool) -> LinearUser:
    return LinearUser(
        email=email,
        active=flags.get("active", True),
        guest=flags.get("guest", False),
        app=flags.get("app", False),
    )


def _ops(
    users: list[LinearUser],
    user_count: int,
    teams: list[LinearTeam],
    members: dict[str, list[LinearUser]],
) -> MagicMock:
    ops = create_autospec(LinearSourceOperations, instance=True)
    ops.list_workspace_users.return_value = WorkspaceUsers(
        organization_id="org-1", user_count=user_count, users=users
    )
    ops.list_teams.return_value = teams
    ops.list_team_members.side_effect = lambda *, team_id: members[team_id]
    return ops


def test_groups_are_the_workspace_and_every_visible_team() -> None:
    ops = _ops(
        users=[
            _user("B@x"),
            _user("a@x"),
            _user("guest@y", guest=True),
            _user("bot@x", app=True),
            _user("gone@x", active=False),
        ],
        user_count=5,
        teams=[
            LinearTeam(id="p", key="P", visibility="private"),
            LinearTeam(id="r", key="R", visibility="restricted", parent_id="p"),
            LinearTeam(id="empty", key="E", visibility="public"),
        ],
        members={"p": [_user("a@x")], "r": [_user("guest@y", guest=True)], "empty": []},
    )

    groups = {group.id: group.user_emails for group in team_groups(ops)}

    # Bare ids: the source prefix is added when the groups are stored. Guests
    # are in their teams' groups, never in the workspace group.
    assert groups == {
        "workspace_members:org-1": ["a@x", "b@x"],
        "p": ["a@x"],
        "r": ["guest@y"],
    }


def test_a_short_users_listing_is_refused() -> None:
    ops = _ops(users=[_user("ann@x")], user_count=5, teams=[], members={})

    with pytest.raises(ConnectorValidationError, match="listed 1 of the 5 users"):
        list(team_groups(ops))


def test_the_sync_builds_the_connector_on_the_db_provider() -> None:
    cc_pair = MagicMock()
    cc_pair.connector.source = DocumentSource.LINEAR
    cc_pair.connector.connector_specific_config = {"team_keys": ["ENG"]}
    cc_pair.credential.id = 3
    provider = MagicMock()
    with (
        patch(
            f"{CONNECTOR}.build_db_credentials_provider", return_value=provider
        ) as build,
        patch(
            "ee.onyx.external_permissions.linear.group_sync.team_groups",
            return_value=iter([]),
        ) as groups,
    ):
        assert list(linear_group_sync("tenant", cc_pair)) == []

    build.assert_called_once_with(DocumentSource.LINEAR, 3)
    ops: Any = groups.call_args.args[0]
    assert isinstance(ops, LinearSourceOperations)
    assert ops.credentials_provider is provider


def test_linear_is_registered_for_group_sync() -> None:
    config = get_source_perm_sync_config(DocumentSource.LINEAR)
    assert config is not None and config.group_sync_config is not None
    assert (
        config.group_sync_config.group_sync_frequency
        == LINEAR_PERMISSION_GROUP_SYNC_FREQUENCY
    )
    assert config.group_sync_config.group_sync_is_cc_pair_agnostic is False
    assert source_requires_external_group_sync(DocumentSource.LINEAR)
