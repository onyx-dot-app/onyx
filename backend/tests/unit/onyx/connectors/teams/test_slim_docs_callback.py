"""Test callback handling in retrieve_all_slim_docs_perm_sync."""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.teams.connector import TeamsConnector
from onyx.connectors.teams.models import Message


def _make_mock_team(team_id: str = "team-1") -> MagicMock:
    team = MagicMock()
    team.id = team_id
    team.display_name = "Test Team"
    return team


def _make_mock_channel(channel_id: str = "channel-1") -> MagicMock:
    channel = MagicMock()
    channel.id = channel_id
    channel.display_name = "Test Channel"
    return channel


def _make_mock_message(message_id: str) -> Message:
    return Message.model_validate(
        {
            "id": message_id,
            "replyToId": None,
            "subject": None,
            "from": None,
            "body": {"contentType": "text", "content": "test content"},
            "createdDateTime": datetime.now(tz=timezone.utc).isoformat(),
            "lastModifiedDateTime": None,
            "lastEditedDateTime": None,
            "deletedDateTime": None,
            "webUrl": f"https://teams.microsoft.com/messages/{message_id}",
        }
    )


@patch("onyx.connectors.teams.connector.fetch_messages")
@patch("onyx.connectors.teams.connector.fetch_external_access")
@patch("onyx.connectors.teams.connector._collect_all_channels_from_team")
@patch("onyx.connectors.teams.connector._collect_all_teams")
def test_callback_progress_called_for_each_message(
    mock_collect_teams: MagicMock,
    mock_collect_channels: MagicMock,
    mock_fetch_external_access: MagicMock,
    mock_fetch_messages: MagicMock,
) -> None:
    """Test that callback.progress() is called for each message processed."""
    mock_collect_teams.return_value = [_make_mock_team()]
    mock_collect_channels.return_value = [_make_mock_channel()]
    mock_fetch_external_access.return_value = ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids=set(),
        is_public=True,
    )
    mock_fetch_messages.return_value = iter(
        [
            _make_mock_message("msg-1"),
            _make_mock_message("msg-2"),
            _make_mock_message("msg-3"),
        ]
    )

    mock_callback = MagicMock()
    mock_callback.should_stop.return_value = False

    connector = TeamsConnector(teams=["Test Team"])
    connector.graph_client = MagicMock()

    # Consume the generator
    results = list(connector.retrieve_all_slim_docs_perm_sync(callback=mock_callback))

    # Verify progress was called 3 times (once per message)
    assert mock_callback.progress.call_count == 3
    mock_callback.progress.assert_called_with("retrieve_all_slim_docs_perm_sync", 1)

    # Verify we got the slim docs
    all_docs = [doc for batch in results for doc in batch]
    assert len(all_docs) == 3


@patch("onyx.connectors.teams.connector.fetch_messages")
@patch("onyx.connectors.teams.connector.fetch_external_access")
@patch("onyx.connectors.teams.connector._collect_all_channels_from_team")
@patch("onyx.connectors.teams.connector._collect_all_teams")
def test_callback_stop_signal_raises_runtime_error(
    mock_collect_teams: MagicMock,
    mock_collect_channels: MagicMock,
    mock_fetch_external_access: MagicMock,
    mock_fetch_messages: MagicMock,
) -> None:
    """Test that RuntimeError is raised when callback.should_stop() returns True."""
    mock_collect_teams.return_value = [_make_mock_team()]
    mock_collect_channels.return_value = [_make_mock_channel()]
    mock_fetch_external_access.return_value = ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids=set(),
        is_public=True,
    )
    mock_fetch_messages.return_value = iter(
        [
            _make_mock_message("msg-1"),
            _make_mock_message("msg-2"),
        ]
    )

    mock_callback = MagicMock()
    # Stop after first message
    mock_callback.should_stop.side_effect = [False, True]

    connector = TeamsConnector(teams=["Test Team"])
    connector.graph_client = MagicMock()

    with pytest.raises(RuntimeError, match="Stop signal detected"):
        # Consume the generator
        list(connector.retrieve_all_slim_docs_perm_sync(callback=mock_callback))

    # Verify progress was called once before stop
    assert mock_callback.progress.call_count == 1


@patch("onyx.connectors.teams.connector.fetch_messages")
@patch("onyx.connectors.teams.connector.fetch_external_access")
@patch("onyx.connectors.teams.connector._collect_all_channels_from_team")
@patch("onyx.connectors.teams.connector._collect_all_teams")
def test_no_callback_works_without_error(
    mock_collect_teams: MagicMock,
    mock_collect_channels: MagicMock,
    mock_fetch_external_access: MagicMock,
    mock_fetch_messages: MagicMock,
) -> None:
    """Test that retrieve_all_slim_docs_perm_sync works when callback is None."""
    mock_collect_teams.return_value = [_make_mock_team()]
    mock_collect_channels.return_value = [_make_mock_channel()]
    mock_fetch_external_access.return_value = ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids=set(),
        is_public=True,
    )
    mock_fetch_messages.return_value = iter(
        [
            _make_mock_message("msg-1"),
            _make_mock_message("msg-2"),
        ]
    )

    connector = TeamsConnector(teams=["Test Team"])
    connector.graph_client = MagicMock()

    # Should not raise - callback is None
    results = list(connector.retrieve_all_slim_docs_perm_sync(callback=None))

    all_docs = [doc for batch in results for doc in batch]
    assert len(all_docs) == 2
