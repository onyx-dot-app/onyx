from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.external_permissions.onedrive.group_sync import onedrive_group_sync
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.onedrive.models import (
    OneDriveGroup,
    OneDriveGroupMember,
    OneDriveGroupMemberPage,
    OneDriveGroupPage,
)


def _connector() -> MagicMock:
    connector = MagicMock()
    connector.ops.list_groups.side_effect = [
        OneDriveGroupPage(
            groups=[OneDriveGroup(id="group-1", displayName="First")],
            next_link="groups-next",
        ),
        OneDriveGroupPage(groups=[OneDriveGroup(id="group-2", displayName="Second")]),
    ]
    connector.ops.list_transitive_group_members.side_effect = [
        OneDriveGroupMemberPage(
            members=[
                OneDriveGroupMember(
                    id="user-1",
                    **{
                        "@odata.type": "#microsoft.graph.user",
                        "userPrincipalName": "FIRST@EXAMPLE.COM",
                    },
                )
            ],
            next_link="members-next",
        ),
        OneDriveGroupMemberPage(
            members=[
                OneDriveGroupMember(
                    id="nested-group",
                    **{"@odata.type": "#microsoft.graph.group", "mail": "group@mail"},
                )
            ]
        ),
        OneDriveGroupMemberPage(
            members=[OneDriveGroupMember(id="user-2", mail="second@example.com")]
        ),
    ]
    return connector


def test_group_sync_paginates_groups_and_transitive_members() -> None:
    connector = _connector()
    cc_pair = MagicMock()
    cc_pair.connector.connector_specific_config = {}

    with (
        patch(
            "ee.onyx.external_permissions.onedrive.group_sync.OneDriveConnector",
            return_value=connector,
        ),
        patch(
            "ee.onyx.external_permissions.onedrive.group_sync.credential_json",
            return_value={},
        ),
    ):
        groups = list(onedrive_group_sync("tenant", cc_pair))

    assert [(group.id, group.user_emails) for group in groups] == [
        ("group-1", ["first@example.com"]),
        ("group-2", ["second@example.com"]),
    ]
    assert connector.ops.list_groups.call_args_list[1].kwargs == {
        "next_link": "groups-next"
    }
    assert connector.ops.list_transitive_group_members.call_args_list[1].kwargs == {
        "group_id": "group-1",
        "next_link": "members-next",
    }


def test_hidden_membership_failure_clears_group_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _connector()
    connector.ops.list_groups.side_effect = [
        OneDriveGroupPage(
            groups=[
                OneDriveGroup(id="hidden", displayName="Hidden"),
                OneDriveGroup(id="visible", displayName="Visible"),
            ]
        )
    ]
    connector.ops.list_transitive_group_members.side_effect = [
        OneDriveGroupMemberPage(
            members=[OneDriveGroupMember(id="partial", mail="partial@example.com")],
            next_link="hidden-next",
        ),
        OneDriveGraphError(
            403, "Authorization_RequestDenied", "Insufficient privileges"
        ),
        OneDriveGroupMemberPage(
            members=[OneDriveGroupMember(id="visible-user", mail="user@example.com")]
        ),
    ]
    cc_pair = MagicMock()
    cc_pair.connector.connector_specific_config = {}

    with (
        patch(
            "ee.onyx.external_permissions.onedrive.group_sync.OneDriveConnector",
            return_value=connector,
        ),
        patch(
            "ee.onyx.external_permissions.onedrive.group_sync.credential_json",
            return_value={},
        ),
    ):
        groups = list(onedrive_group_sync("tenant", cc_pair))

    assert [(group.id, group.user_emails) for group in groups] == [
        ("hidden", []),
        ("visible", ["user@example.com"]),
    ]
    assert "Member.Read.Hidden" in caplog.text
    assert "Clearing its mapped users" in caplog.text
