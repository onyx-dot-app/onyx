"""Unit tests for EE Slack perm sync on Enterprise Grid."""

from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from ee.onyx.external_permissions.slack.channel_access import (
    get_channel_access as ee_get_channel_access,
)
from ee.onyx.external_permissions.slack.doc_sync import _fetch_channel_permissions
from ee.onyx.external_permissions.slack.doc_sync import _fetch_workspace_permissions
from ee.onyx.external_permissions.slack.doc_sync import _get_slack_document_access
from ee.onyx.external_permissions.slack.utils import fetch_team_user_emails
from ee.onyx.external_permissions.slack.utils import fetch_user_id_to_email_map
from onyx.access.models import ExternalAccess
from onyx.connectors.models import SlimDocument
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
            "onyx.connectors.slack.utils.make_paginated_slack_api_call"
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
            "onyx.connectors.slack.utils.make_paginated_slack_api_call"
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

    def test_public_channel_fallback_to_is_public_when_teams_unknown(
        self,
    ) -> None:
        client = MagicMock()
        ws_emails = {"T_W1": {"a@x.com"}}
        ch = _channel("C_UNKNOWN", team="T_UNKNOWN")
        with patch(
            "ee.onyx.external_permissions.slack.doc_sync.get_channels_across_teams"
        ) as mock_get:
            mock_get.side_effect = [[ch], []]
            workspace_perm = _fetch_workspace_permissions({})
            result = _fetch_channel_permissions(
                slack_client=client,
                workspace_permissions=workspace_perm,
                user_id_to_email_map={},
                team_ids=["T_W1"],
                team_id_to_user_emails=ws_emails,
            )
            assert result["C_UNKNOWN"].is_public is True
            assert result["C_UNKNOWN"].external_user_emails == set()

    def test_public_channel_fallback_to_is_public_when_union_exceeds_cap(
        self,
    ) -> None:
        client = MagicMock()
        big = {f"u{i}@x.com" for i in range(ExternalAccess.MAX_NUM_ENTRIES + 1)}
        ws_emails = {"T_W1": big}
        ch = _channel("C_BIG", team="T_W1")
        with patch(
            "ee.onyx.external_permissions.slack.doc_sync.get_channels_across_teams"
        ) as mock_get:
            mock_get.side_effect = [[ch], []]
            workspace_perm = _fetch_workspace_permissions({})
            result = _fetch_channel_permissions(
                slack_client=client,
                workspace_permissions=workspace_perm,
                user_id_to_email_map={},
                team_ids=["T_W1"],
                team_id_to_user_emails=ws_emails,
            )
            assert result["C_BIG"].is_public is True
            assert result["C_BIG"].external_user_emails == set()

    def test_non_grid_public_channel_not_overridden(self) -> None:
        """Non-Grid public channels stay with their ingest-time is_public=True.

        The override path in ``_get_slack_document_access`` only fires when
        the channel id is in ``channel_permissions``; non-Grid public
        channels are intentionally absent so the ingest value wins.
        """
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
            assert "C1" not in result


class TestEEGetChannelAccessGrid:
    def test_public_channel_non_grid_returns_is_public_true(self) -> None:
        ch = _channel("C1", is_private=False)
        access = ee_get_channel_access(MagicMock(), ch, {}, team_id_to_user_emails=None)
        assert access.is_public is True
        assert access.external_user_emails == set()

    def test_public_channel_grid_scoped_to_workspace_users(self) -> None:
        ch = _channel("C1", is_private=False, team="T1")
        access = ee_get_channel_access(
            MagicMock(),
            ch,
            {},
            team_id_to_user_emails={"T1": {"a@x.com"}, "T2": {"z@x.com"}},
        )
        assert access.is_public is False
        assert access.external_user_emails == {"a@x.com"}

    def test_public_channel_grid_org_shared_unions_workspaces(self) -> None:
        ch = _channel(
            "C1",
            is_private=False,
            team="T1",
            shared_team_ids=["T1", "T2"],
            is_org_shared=True,
        )
        access = ee_get_channel_access(
            MagicMock(),
            ch,
            {},
            team_id_to_user_emails={"T1": {"a@x.com"}, "T2": {"z@x.com"}},
        )
        assert access.is_public is False
        assert access.external_user_emails == {"a@x.com", "z@x.com"}

    def test_public_channel_grid_falls_back_to_is_public_when_teams_unknown(
        self,
    ) -> None:
        ch = _channel("C1", is_private=False, team="T_UNKNOWN")
        access = ee_get_channel_access(
            MagicMock(),
            ch,
            {},
            team_id_to_user_emails={"T1": {"a@x.com"}},
        )
        assert access.is_public is True
        assert access.external_user_emails == set()

    def test_public_channel_grid_falls_back_to_is_public_when_channel_team_ids_empty(
        self,
    ) -> None:
        ch = _channel("C1", is_private=False)  # no team / context_team_id
        access = ee_get_channel_access(
            MagicMock(),
            ch,
            {},
            team_id_to_user_emails={"T1": {"a@x.com"}},
        )
        assert access.is_public is True
        assert access.external_user_emails == set()

    def test_public_channel_grid_falls_back_to_is_public_when_union_exceeds_cap(
        self,
    ) -> None:
        from onyx.access.models import ExternalAccess as _EA

        big = {f"u{i}@x.com" for i in range(_EA.MAX_NUM_ENTRIES + 1)}
        ch = _channel("C1", is_private=False, team="T1")
        access = ee_get_channel_access(
            MagicMock(),
            ch,
            {},
            team_id_to_user_emails={"T1": big},
        )
        assert access.is_public is True
        assert access.external_user_emails == set()

    def test_private_channel_uses_members_path_regardless_of_grid(self) -> None:
        client = MagicMock()
        ch = _channel("C1", is_private=True, team="T1")
        with (
            patch(
                "ee.onyx.external_permissions.slack.channel_access.make_paginated_slack_api_call"
            ) as mock_paginate,
            patch(
                "ee.onyx.external_permissions.slack.channel_access.expert_info_from_slack_id"
            ) as mock_expert,
        ):
            mock_paginate.return_value = iter([{"members": ["U1", "U2"]}])
            mock_expert.side_effect = lambda user_id, client, user_cache: (  # noqa: ARG005
                MagicMock(email=f"{user_id.lower()}@x.com") if user_id else None
            )
            access = ee_get_channel_access(
                client,
                ch,
                {},
                team_id_to_user_emails={"T1": {"a@x.com"}, "T2": {"z@x.com"}},
            )
            assert access.is_public is False
            assert access.external_user_emails == {"u1@x.com", "u2@x.com"}


class TestGetSlackDocumentAccess:
    def test_channel_permissions_override_external_access(self) -> None:
        connector = MagicMock()
        original_access = ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        )
        override_access = ExternalAccess(
            external_user_emails={"allowed@x.com"},
            external_user_group_ids=set(),
            is_public=False,
        )
        slim_doc = SlimDocument(
            id="C1__123",
            external_access=original_access,
            parent_hierarchy_raw_node_id="C1",
        )
        connector.retrieve_all_slim_docs_perm_sync.return_value = iter([[slim_doc]])

        results = list(
            _get_slack_document_access(
                slack_connector=connector,
                channel_permissions={"C1": override_access},
                callback=None,
                indexing_start=None,
            )
        )

        assert len(results) == 1
        assert results[0].external_access == override_access

    def test_falls_back_when_channel_missing(self) -> None:
        connector = MagicMock()
        access = ExternalAccess(
            external_user_emails={"stay@x.com"},
            external_user_group_ids=set(),
            is_public=False,
        )
        slim_doc = SlimDocument(
            id="C2__999",
            external_access=access,
            parent_hierarchy_raw_node_id="C2",
        )
        connector.retrieve_all_slim_docs_perm_sync.return_value = iter([[slim_doc]])

        results = list(
            _get_slack_document_access(
                slack_connector=connector,
                channel_permissions={},
                callback=None,
                indexing_start=None,
            )
        )

        assert len(results) == 1
        assert results[0].external_access == access
