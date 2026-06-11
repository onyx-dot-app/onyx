"""Unit tests for Slack Enterprise Grid helpers.

These tests exercise the Grid-specific code paths added to the Slack connector
using a mocked Slack ``WebClient``. They do not hit the real Slack API.
"""

from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from slack_sdk.errors import SlackApiError

from onyx.connectors.slack.connector import _channel_team_id
from onyx.connectors.slack.connector import _channel_to_hierarchy_node
from onyx.connectors.slack.connector import channel_team_ids
from onyx.connectors.slack.connector import fetch_team_url
from onyx.connectors.slack.connector import get_channels_across_teams
from onyx.connectors.slack.connector import list_grid_team_ids
from onyx.connectors.slack.connector import SlackConnector
from onyx.connectors.slack.models import ChannelType
from onyx.connectors.slack.models import MessageType
from onyx.connectors.slack.utils import get_message_link


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


def _msg(ts: str, thread_ts: str | None = None) -> MessageType:
    data: dict[str, Any] = {"type": "message", "user": "U1", "text": "hi", "ts": ts}
    if thread_ts is not None:
        data["thread_ts"] = thread_ts
    return cast(MessageType, data)


class TestListGridTeamIds:
    def test_returns_team_ids_from_paginated_response(self) -> None:
        with patch(
            "onyx.connectors.slack.connector.make_paginated_slack_api_call"
        ) as mock_paginate:
            mock_paginate.return_value = iter(
                [
                    {"teams": [{"id": "T1"}, {"id": "T2"}]},
                    {"teams": [{"id": "T3"}]},
                ]
            )
            client = MagicMock()
            assert list_grid_team_ids(client) == ["T1", "T2", "T3"]

    def test_skips_teams_without_id(self) -> None:
        with patch(
            "onyx.connectors.slack.connector.make_paginated_slack_api_call"
        ) as mock_paginate:
            mock_paginate.return_value = iter(
                [{"teams": [{"id": "T1"}, {"name": "no-id-team"}, {"id": ""}]}]
            )
            assert list_grid_team_ids(MagicMock()) == ["T1"]

    def test_empty_response_returns_empty_list(self) -> None:
        with patch(
            "onyx.connectors.slack.connector.make_paginated_slack_api_call"
        ) as mock_paginate:
            mock_paginate.return_value = iter([{"teams": []}])
            assert list_grid_team_ids(MagicMock()) == []


class TestFetchTeamUrl:
    def test_returns_url_from_team_info(self) -> None:
        client = MagicMock()
        client.team_info.return_value = MagicMock(
            get=lambda key, default=None: (
                {"id": "T1", "url": "https://acme.slack.com/"}
                if key == "team"
                else default
            )
        )
        assert fetch_team_url(client, "T1") == "https://acme.slack.com/"
        client.team_info.assert_called_once_with(team="T1")

    def test_returns_none_when_slack_api_errors(self) -> None:
        client = MagicMock()
        err_response = MagicMock()
        err_response.get.return_value = "team_not_found"
        client.team_info.side_effect = SlackApiError("boom", err_response)
        assert fetch_team_url(client, "T_BAD") is None

    def test_returns_none_when_url_missing(self) -> None:
        client = MagicMock()
        client.team_info.return_value = MagicMock(
            get=lambda key, default=None: ({} if key == "team" else default)
        )
        assert fetch_team_url(client, "T1") is None


class TestGetChannelsAcrossTeams:
    def test_iterates_each_team_and_concatenates(self) -> None:
        team_one_channels = [_channel("C1"), _channel("C2")]
        team_two_channels = [_channel("C3")]
        with patch("onyx.connectors.slack.connector.get_channels") as mock_get_channels:
            mock_get_channels.side_effect = [team_one_channels, team_two_channels]
            result = get_channels_across_teams(MagicMock(), ["T1", "T2"])
            assert [c["id"] for c in result] == ["C1", "C2", "C3"]
            assert mock_get_channels.call_count == 2
            assert mock_get_channels.call_args_list[0].kwargs["team_id"] == "T1"
            assert mock_get_channels.call_args_list[1].kwargs["team_id"] == "T2"

    def test_dedupes_org_shared_channels_by_id(self) -> None:
        shared = _channel("CSHARED", is_org_shared=True)
        with patch("onyx.connectors.slack.connector.get_channels") as mock_get_channels:
            mock_get_channels.side_effect = [
                [shared, _channel("C1")],
                [shared, _channel("C2")],
            ]
            result = get_channels_across_teams(MagicMock(), ["T1", "T2"])
            assert [c["id"] for c in result] == ["CSHARED", "C1", "C2"]

    def test_empty_team_list_returns_empty(self) -> None:
        with patch("onyx.connectors.slack.connector.get_channels") as mock_get_channels:
            assert get_channels_across_teams(MagicMock(), []) == []
            mock_get_channels.assert_not_called()

    def test_stamps_team_id_when_channel_team_missing(self) -> None:
        # Slack omits the team field on conversations.list when called with
        # an explicit team_id. Stamping the queried team_id onto each channel
        # lets downstream URL resolution work without an extra API call.
        ch_no_team = _channel("C1")
        ch_with_team = _channel("C2", team="T_EXISTING")
        with patch("onyx.connectors.slack.connector.get_channels") as mock_get_channels:
            mock_get_channels.side_effect = [[ch_no_team, ch_with_team]]
            result = get_channels_across_teams(MagicMock(), ["T_QUERIED"])
            stamped = {c["id"]: c.get("team") for c in result}
            assert stamped == {"C1": "T_QUERIED", "C2": "T_EXISTING"}


class TestChannelTeamId:
    def test_prefers_team_field(self) -> None:
        ch = _channel("C1", team="T_LIST", context_team_id="T_INFO")
        assert _channel_team_id(ch) == "T_LIST"

    def test_falls_back_to_context_team_id(self) -> None:
        ch = _channel("C1", context_team_id="T_INFO")
        assert _channel_team_id(ch) == "T_INFO"

    def test_none_when_neither_present(self) -> None:
        assert _channel_team_id(_channel("C1")) is None


class TestChannelTeamIdsPlural:
    def test_uses_shared_team_ids_when_present(self) -> None:
        ch = _channel("C1", team="T1", shared_team_ids=["T1", "T2", "T3"])
        assert channel_team_ids(ch) == ["T1", "T2", "T3"]

    def test_falls_back_to_single_team_id(self) -> None:
        ch = _channel("C1", team="T1")
        assert channel_team_ids(ch) == ["T1"]

    def test_falls_back_to_context_team_id(self) -> None:
        ch = _channel("C1", context_team_id="T_INFO")
        assert channel_team_ids(ch) == ["T_INFO"]

    def test_empty_when_no_team_info(self) -> None:
        assert channel_team_ids(_channel("C1")) == []


class TestChannelToHierarchyNode:
    def test_grid_uses_per_team_url(self) -> None:
        channel = _channel("C1", team="T1")
        team_id_to_url = {
            "T1": "https://team-one.slack.com",
            "T2": "https://team-two.slack.com",
        }
        node = _channel_to_hierarchy_node(
            channel,
            channel_access=None,
            workspace_url="https://fallback.slack.com",
            team_id_to_url=team_id_to_url,
        )
        assert node.link == "https://team-one.slack.com/archives/C1"

    def test_grid_falls_back_to_workspace_url_when_team_absent(self) -> None:
        channel = _channel("C1")  # no team field
        node = _channel_to_hierarchy_node(
            channel,
            channel_access=None,
            workspace_url="https://fallback.slack.com",
            team_id_to_url={"T1": "https://team-one.slack.com"},
        )
        assert node.link == "https://fallback.slack.com/archives/C1"

    def test_non_grid_path_uses_workspace_url_unchanged(self) -> None:
        channel = _channel("C1")
        node = _channel_to_hierarchy_node(
            channel,
            channel_access=None,
            workspace_url="https://ws.slack.com",
        )
        assert node.link == "https://ws.slack.com/archives/C1"


class TestGetMessageLinkTeamAware:
    def test_uses_per_team_url_when_provided(self) -> None:
        client = MagicMock()
        client.token = "xoxb-test"
        link = get_message_link(
            event=_msg("1700000000.000100"),
            client=client,
            channel_id="C1",
            team_id="T1",
            team_id_to_url={"T1": "https://team-one.slack.com"},
        )
        assert link.startswith("https://team-one.slack.com/archives/C1/p")

    def test_falls_back_to_get_base_url_when_team_id_to_url_missing(self) -> None:
        client = MagicMock()
        client.token = "xoxb-fallback"
        with patch(
            "onyx.connectors.slack.utils.get_base_url",
            return_value="https://fallback.slack.com",
        ):
            link = get_message_link(
                event=_msg("1700000000.000100"),
                client=client,
                channel_id="C1",
                team_id="T1",
                team_id_to_url=None,
            )
        assert link.startswith("https://fallback.slack.com/archives/C1/p")

    def test_thread_ts_appended_when_present(self) -> None:
        client = MagicMock()
        client.token = "xoxb-thread"
        link = get_message_link(
            event=_msg("1700000001.000200", thread_ts="1700000000.000100"),
            client=client,
            channel_id="C1",
            team_id="T1",
            team_id_to_url={"T1": "https://team-one.slack.com"},
        )
        assert "?thread_ts=1700000000.000100" in link


@pytest.mark.parametrize(
    "channel_id_set,expected_order",
    [
        ([("T1", ["C1", "C2"]), ("T2", ["C2", "C3"])], ["C1", "C2", "C3"]),
        ([("T1", []), ("T2", ["C9"])], ["C9"]),
    ],
)
def test_dedupe_preserves_first_occurrence_order(
    channel_id_set: list[tuple[str, list[str]]],
    expected_order: list[str],
) -> None:
    with patch("onyx.connectors.slack.connector.get_channels") as mock_get_channels:
        mock_get_channels.side_effect = [
            [_channel(cid) for cid in cids] for _, cids in channel_id_set
        ]
        team_ids = [tid for tid, _ in channel_id_set]
        result = get_channels_across_teams(MagicMock(), team_ids)
        assert [c["id"] for c in result] == expected_order


class TestSlackConnectorGridProperties:
    def _connector(
        self,
        is_grid: bool,
        team_ids: list[str],
        team_id_to_url: dict[str, str],
        team_id_to_user_emails: dict[str, set[str]],
    ) -> SlackConnector:
        c = SlackConnector(channels=None, use_redis=False)
        c._is_grid = is_grid
        c._team_ids = team_ids
        c._team_id_to_url = team_id_to_url
        c._team_id_to_user_emails = team_id_to_user_emails
        return c

    def test_grid_properties_return_underlying_fields_on_grid(self) -> None:
        c = self._connector(
            is_grid=True,
            team_ids=["T1"],
            team_id_to_url={"T1": "https://x.slack.com"},
            team_id_to_user_emails={"T1": {"a@x.com"}},
        )
        assert c.grid_team_ids == ["T1"]
        assert c.grid_team_id_to_url == {"T1": "https://x.slack.com"}
        assert c.grid_team_id_to_user_emails == {"T1": {"a@x.com"}}

    def test_grid_properties_return_none_when_not_grid(self) -> None:
        c = self._connector(
            is_grid=False,
            team_ids=["T1"],
            team_id_to_url={"T1": "https://x.slack.com"},
            team_id_to_user_emails={"T1": {"a@x.com"}},
        )
        assert c.grid_team_ids is None
        assert c.grid_team_id_to_url is None
        assert c.grid_team_id_to_user_emails is None
