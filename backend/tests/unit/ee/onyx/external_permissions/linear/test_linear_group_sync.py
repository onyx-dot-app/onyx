"""The group sync fills one group per team the token can see and the
workspace members group, and refuses a members listing Linear cut short."""

from typing import Any
from unittest.mock import MagicMock, patch

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
from onyx.connectors.linear.connector import LinearConnector
from onyx.connectors.linear.models import LinearTeam, WorkspaceMembers

MODULE = "onyx.connectors.linear.connector"
CONNECTOR = "ee.onyx.external_permissions.linear.connector"


def _user(email: str, **flags: bool) -> dict[str, Any]:
    return {
        "email": email,
        "active": flags.get("active", True),
        "guest": flags.get("guest", False),
        "app": flags.get("app", False),
    }


def _response(data: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"data": data}
    return response


def _page_info(end_cursor: str | None = None) -> dict[str, Any]:
    return {"hasNextPage": end_cursor is not None, "endCursor": end_cursor}


def _connector() -> LinearConnector:
    connector = LinearConnector()
    connector.load_credentials({"linear_api_key": "lin_api_test"})
    return connector


def test_groups_are_the_workspace_and_every_visible_team() -> None:
    connector = MagicMock(spec=LinearConnector)
    connector.workspace_members.return_value = WorkspaceMembers(
        organization_id="org-1", emails={"b@x", "a@x"}
    )
    connector.list_teams.return_value = [
        LinearTeam(id="p", key="P", visibility="private"),
        LinearTeam(id="r", key="R", visibility="restricted", parent_id="p"),
        LinearTeam(id="empty", key="E", visibility="public"),
    ]
    connector.team_member_emails.side_effect = lambda team_id: {
        "p": {"a@x"},
        "r": {"guest@y"},
        "empty": set(),
    }[team_id]

    groups = {group.id: group.user_emails for group in team_groups(connector)}

    # Bare ids: the source prefix is added when the groups are stored.
    assert groups == {
        "workspace_members:org-1": ["a@x", "b@x"],
        "p": ["a@x"],
        "r": ["guest@y"],
    }


def test_workspace_members_leave_out_guests_apps_and_the_deactivated() -> None:
    connector = _connector()
    pages = [
        _response(
            {
                "organization": {"id": "org-1", "userCount": 3},
                "users": {
                    "nodes": [_user("Ann@x"), _user("guest@y", guest=True)],
                    "pageInfo": _page_info("c1"),
                },
            }
        ),
        _response(
            {
                "organization": {"id": "org-1", "userCount": 3},
                "users": {
                    "nodes": [_user("bot@x", app=True), _user("gone@x", active=False)],
                    "pageInfo": _page_info(),
                },
            }
        ),
    ]
    with patch(f"{MODULE}._make_query", side_effect=pages):
        assert connector.workspace_members() == WorkspaceMembers(
            organization_id="org-1", emails={"ann@x"}
        )


def test_a_short_users_listing_is_refused() -> None:
    connector = _connector()
    page = _response(
        {
            "organization": {"id": "org-1", "userCount": 5},
            "users": {"nodes": [_user("ann@x")], "pageInfo": _page_info()},
        }
    )
    with (
        patch(f"{MODULE}._make_query", return_value=page),
        pytest.raises(RuntimeError, match="listed 1 of the 5 users"),
    ):
        connector.workspace_members()


def test_team_members_are_paged_per_team() -> None:
    connector = _connector()
    pages = [
        _response(
            {
                "team": {
                    "memberships": {
                        "nodes": [{"user": _user("ann@x")}],
                        "pageInfo": _page_info("c1"),
                    }
                }
            }
        ),
        _response(
            {
                "team": {
                    "memberships": {
                        "nodes": [{"user": _user("bob@x")}],
                        "pageInfo": _page_info(),
                    }
                }
            }
        ),
    ]
    with patch(f"{MODULE}._make_query", side_effect=pages) as query:
        assert connector.team_member_emails("t1") == {"ann@x", "bob@x"}

    sent = [call.args[0]["variables"] for call in query.call_args_list]
    assert sent == [
        {"teamId": "t1", "first": 100, "after": None},
        {"teamId": "t1", "first": 100, "after": "c1"},
    ]


def test_a_cursor_that_stops_advancing_is_refused() -> None:
    connector = _connector()
    page = _response(
        {"teams": {"nodes": [], "pageInfo": _page_info("same")}},
    )
    with (
        patch(f"{MODULE}._make_query", return_value=page),
        pytest.raises(RuntimeError, match="stopped advancing"),
    ):
        connector.list_teams()


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
    connector: Any = groups.call_args.args[0]
    assert isinstance(connector, LinearConnector)
    assert connector.team_keys == ["ENG"]
    assert connector._credentials_provider is provider


def test_linear_is_registered_for_group_sync() -> None:
    config = get_source_perm_sync_config(DocumentSource.LINEAR)
    assert config is not None and config.group_sync_config is not None
    assert (
        config.group_sync_config.group_sync_frequency
        == LINEAR_PERMISSION_GROUP_SYNC_FREQUENCY
    )
    assert config.group_sync_config.group_sync_is_cc_pair_agnostic is False
    assert source_requires_external_group_sync(DocumentSource.LINEAR)
