"""Unit tests for EE Slack perm sync on Enterprise Grid."""

from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from ee.onyx.external_permissions.slack.doc_sync import _fetch_channel_permissions
from ee.onyx.external_permissions.slack.doc_sync import _fetch_workspace_permissions
from ee.onyx.external_permissions.slack.utils import fetch_team_user_emails
from ee.onyx.external_permissions.slack.utils import fetch_user_id_to_email_map
from onyx.connectors.slack.models import ChannelType


def _channel(channel_id: str, **overrides: Any) -> ChannelType:
    base: dict[str, Any] = {
        "id": channel_id,
        "name": f"chan-{channel_id.lower()}",
        "is_channel": True,
        "is_group": False,
        "is_im": False,
        "created": 0,
        "creator": "U1",
        "is_archived": False,
        "is_general": False,
        "unlinked": 0,
        "name_normalized": f"chan-{channel_id.lower()}",
        "is_shared": False,
        "is_ext_shared": False,
        "is_org_shared": False,
        "pending_shared": [],
        "is_pending_ext_shared": False,
        "is_member": True,
        "is_private": False,
        "is_mpim": False,
        "updated": 0,
        "topic": {"value": "", "creator": "", "last_set": 0},
        "purpose": {"value": "", "creator": "", "last_set": 0},
        "previous_names": [],
        "num_members": 0,
    }
    base.update(overrides)
    return cast(ChannelType, base)


class TestFetchUserIdToEmailMap:
    def test_non_grid_calls_users_list_without_team_id(self) -> None:
        client = MagicMock()
        with patch(
            "ee.onyx.external_permissions.slack.utils.make_paginated_slack_api_call"
        ) as mock_paginate:
            mock_paginate.return_value = iter(
                [{"members": [{"id": "U1", "profile": {"email": "u1@x.com"}}]}]
            )
            result = fetch_user_id_to_email_map(client)
            assert result == {"U1": "u1@x.com"}
            assert mock_paginate.call_count == 1
            assert "team_id" not in mock_paginate.call_args.kwargs

    def test_grid_iterates_each_team_with_team_id(self) -> None:
        client = MagicMock()
        with patch(
            "ee.onyx.external_permissions.slack.utils.make_paginated_slack_api_call"
        ) as mock_paginate:
            mock_paginate.side_effect = [
                iter([{"members": [{"id": "U1", "profile": {"email": "u1@x.com"}}]}]),
                iter([{"members": [{"id": "U2", "profile": {"email": "u2@x.com"}}]}]),
            ]
            result = fetch_user_id_to_email_map(client, team_ids=["T1", "T2"])
            assert result == {"U1": "u1@x.com", "U2": "u2@x.com"}
            assert mock_paginate.call_count == 2
            assert mock_paginate.call_args_list[0].kwargs == {"team_id": "T1"}
            assert mock_paginate.call_args_list[1].kwargs == {"team_id": "T2"}


class TestFetchTeamUserEmails:
    def test_returns_per_team_email_sets(self) -> None:
        client = MagicMock()
        with patch(
            "ee.onyx.external_permissions.slack.utils.make_paginated_slack_api_call"
        ) as mock_paginate:
            mock_paginate.side_effect = [
                iter([{"members": [{"id": "U1", "profile": {"email": "u1@x.com"}}]}]),
                iter(
                    [
                        {
                            "members": [
                                {"id": "U2", "profile": {"email": "u2@x.com"}},
                                {"id": "U3", "profile": {"email": "u3@x.com"}},
                            ]
                        }
                    ]
                ),
            ]
            result = fetch_team_user_emails(client, ["T1", "T2"])
            assert result == {"T1": {"u1@x.com"}, "T2": {"u2@x.com", "u3@x.com"}}

    def test_skips_users_without_email(self) -> None:
        client = MagicMock()
        with patch(
            "ee.onyx.external_permissions.slack.utils.make_paginated_slack_api_call"
        ) as mock_paginate:
            mock_paginate.return_value = iter(
                [
                    {
                        "members": [
                            {"id": "U1", "profile": {"email": "u1@x.com"}},
                            {"id": "U2", "profile": {}},
                        ]
                    }
                ]
            )
            assert fetch_team_user_emails(client, ["T1"]) == {"T1": {"u1@x.com"}}


class TestFetchChannelPermissionsGrid:
    def test_public_channel_scoped_to_its_workspace_users(self) -> None:
        client = MagicMock()
        ws_emails = {
            "T_W1": {"a@x.com", "b@x.com", "c@x.com"},
            "T_W2": {"z@x.com"},
        }
        ch_w1 = _channel("C_W1", team="T_W1")
        ch_w2 = _channel("C_W2", team="T_W2")
        with patch(
            "ee.onyx.external_permissions.slack.doc_sync.get_channels_across_teams"
        ) as mock_get:
            mock_get.side_effect = [[ch_w1, ch_w2], []]  # public, private
            workspace_perm = _fetch_workspace_permissions({"U1": "a@x.com"})
            result = _fetch_channel_permissions(
                slack_client=client,
                workspace_permissions=workspace_perm,
                user_id_to_email_map={},
                team_ids=["T_W1", "T_W2"],
                team_id_to_user_emails=ws_emails,
            )
            assert result["C_W1"].external_user_emails == {
                "a@x.com",
                "b@x.com",
                "c@x.com",
            }
            assert result["C_W2"].external_user_emails == {"z@x.com"}
            assert result["C_W1"].is_public is False
            assert result["C_W2"].is_public is False

    def test_org_shared_public_channel_unions_users_across_workspaces(self) -> None:
        client = MagicMock()
        ws_emails = {
            "T_W1": {"a@x.com", "b@x.com"},
            "T_W2": {"z@x.com"},
        }
        shared = _channel(
            "C_SHARED",
            team="T_W1",
            shared_team_ids=["T_W1", "T_W2"],
            is_org_shared=True,
        )
        with patch(
            "ee.onyx.external_permissions.slack.doc_sync.get_channels_across_teams"
        ) as mock_get:
            mock_get.side_effect = [[shared], []]
            workspace_perm = _fetch_workspace_permissions({})
            result = _fetch_channel_permissions(
                slack_client=client,
                workspace_permissions=workspace_perm,
                user_id_to_email_map={},
                team_ids=["T_W1", "T_W2"],
                team_id_to_user_emails=ws_emails,
            )
            assert result["C_SHARED"].external_user_emails == {
                "a@x.com",
                "b@x.com",
                "z@x.com",
            }

    def test_non_grid_falls_back_to_workspace_permissions(self) -> None:
        client = MagicMock()
        ch = _channel("C1")  # no team field, non-Grid
        with patch(
            "ee.onyx.external_permissions.slack.doc_sync.get_channels"
        ) as mock_get:
            mock_get.side_effect = [[ch], []]  # public, private
            workspace_perm = _fetch_workspace_permissions(
                {"U1": "a@x.com", "U2": "b@x.com"}
            )
            result = _fetch_channel_permissions(
                slack_client=client,
                workspace_permissions=workspace_perm,
                user_id_to_email_map={},
                team_ids=None,
                team_id_to_user_emails=None,
            )
            assert result["C1"].external_user_emails == {"a@x.com", "b@x.com"}
