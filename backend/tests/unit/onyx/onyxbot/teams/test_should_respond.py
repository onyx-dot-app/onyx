"""Unit tests for Teams bot should_respond logic."""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.onyxbot.teams.handle_message import should_respond


class TestBasicShouldRespond:
    """Tests for basic should_respond decision logic."""

    def test_team_disabled_returns_false(self) -> None:
        """Team config enabled=false returns False."""
        mock_team_config = MagicMock()
        mock_team_config.enabled = False

        with patch(
            "onyx.onyxbot.teams.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with patch(
                "onyx.onyxbot.teams.handle_message.get_team_config_by_teams_id",
                return_value=mock_team_config,
            ):
                result = should_respond(
                    activity_dict={},
                    team_id="team-123",
                    channel_id="channel-456",
                    tenant_id="tenant1",
                    bot_id="bot-id",
                )

        assert result.should_respond is False

    def test_team_enabled_channel_enabled_no_mention_required(self) -> None:
        """Team + channel enabled, require_bot_mention=false returns True."""
        mock_team_config = MagicMock()
        mock_team_config.enabled = True
        mock_team_config.default_persona_id = 2

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_mention = False
        mock_channel_config.persona_override_id = None

        with patch(
            "onyx.onyxbot.teams.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.teams.handle_message.get_team_config_by_teams_id",
                    return_value=mock_team_config,
                ),
                patch(
                    "onyx.onyxbot.teams.handle_message.get_channel_config_by_teams_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = should_respond(
                    activity_dict={},
                    team_id="team-123",
                    channel_id="channel-456",
                    tenant_id="tenant1",
                    bot_id="bot-id",
                )

        assert result.should_respond is True
        assert result.persona_id == 2

    def test_channel_disabled_returns_false(self) -> None:
        """Channel config enabled=false returns False."""
        mock_team_config = MagicMock()
        mock_team_config.enabled = True

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = False

        with patch(
            "onyx.onyxbot.teams.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.teams.handle_message.get_team_config_by_teams_id",
                    return_value=mock_team_config,
                ),
                patch(
                    "onyx.onyxbot.teams.handle_message.get_channel_config_by_teams_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = should_respond(
                    activity_dict={},
                    team_id="team-123",
                    channel_id="channel-456",
                    tenant_id="tenant1",
                    bot_id="bot-id",
                )

        assert result.should_respond is False

    def test_channel_not_found_returns_false(self) -> None:
        """No channel config returns False (not whitelisted)."""
        mock_team_config = MagicMock()
        mock_team_config.enabled = True

        with patch(
            "onyx.onyxbot.teams.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.teams.handle_message.get_team_config_by_teams_id",
                    return_value=mock_team_config,
                ),
                patch(
                    "onyx.onyxbot.teams.handle_message.get_channel_config_by_teams_ids",
                    return_value=None,
                ),
            ):
                result = should_respond(
                    activity_dict={},
                    team_id="team-123",
                    channel_id="channel-456",
                    tenant_id="tenant1",
                    bot_id="bot-id",
                )

        assert result.should_respond is False

    def test_require_mention_true_with_mention(
        self, sample_activity_dict: dict
    ) -> None:
        """require_bot_mention=true with @mention returns True."""
        mock_team_config = MagicMock()
        mock_team_config.enabled = True
        mock_team_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_mention = True
        mock_channel_config.persona_override_id = None

        with patch(
            "onyx.onyxbot.teams.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.teams.handle_message.get_team_config_by_teams_id",
                    return_value=mock_team_config,
                ),
                patch(
                    "onyx.onyxbot.teams.handle_message.get_channel_config_by_teams_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = should_respond(
                    activity_dict=sample_activity_dict,
                    team_id="team-abc-123",
                    channel_id="19:channel-xyz@thread.tacv2",
                    tenant_id="tenant1",
                    bot_id="28:bot-id-456",
                )

        assert result.should_respond is True

    def test_require_mention_true_no_mention(self) -> None:
        """require_bot_mention=true without @mention returns False."""
        mock_team_config = MagicMock()
        mock_team_config.enabled = True
        mock_team_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_mention = True
        mock_channel_config.persona_override_id = None

        activity_no_mention = {"entities": []}

        with patch(
            "onyx.onyxbot.teams.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.teams.handle_message.get_team_config_by_teams_id",
                    return_value=mock_team_config,
                ),
                patch(
                    "onyx.onyxbot.teams.handle_message.get_channel_config_by_teams_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = should_respond(
                    activity_dict=activity_no_mention,
                    team_id="team-123",
                    channel_id="channel-456",
                    tenant_id="tenant1",
                    bot_id="bot-id",
                )

        assert result.should_respond is False

    def test_dm_no_team_returns_true(self) -> None:
        """DM (no team_id or channel_id) returns True."""
        result = should_respond(
            activity_dict={},
            team_id=None,
            channel_id=None,
            tenant_id="tenant1",
            bot_id="bot-id",
        )
        assert result.should_respond is True

    def test_persona_override_takes_priority(self) -> None:
        """Channel persona override takes priority over team default."""
        mock_team_config = MagicMock()
        mock_team_config.enabled = True
        mock_team_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_mention = False
        mock_channel_config.persona_override_id = 5

        with patch(
            "onyx.onyxbot.teams.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.teams.handle_message.get_team_config_by_teams_id",
                    return_value=mock_team_config,
                ),
                patch(
                    "onyx.onyxbot.teams.handle_message.get_channel_config_by_teams_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = should_respond(
                    activity_dict={},
                    team_id="team-123",
                    channel_id="channel-456",
                    tenant_id="tenant1",
                    bot_id="bot-id",
                )

        assert result.should_respond is True
        assert result.persona_id == 5
