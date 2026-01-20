"""Unit tests for Discord bot should_respond logic.

Tests the decision tree for when the bot should respond to messages.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import discord
import pytest

from onyx.onyxbot.discord.handle_message import check_implicit_invocation
from onyx.onyxbot.discord.handle_message import should_respond


class TestBasicShouldRespond:
    """Tests for basic should_respond decision logic."""

    @pytest.mark.asyncio
    async def test_should_respond_guild_disabled(
        self, mock_discord_message: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """Guild config enabled=false returns False."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = False

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with patch(
                "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                return_value=mock_guild_config,
            ):
                result = await should_respond(
                    mock_discord_message, "tenant1", mock_bot_user
                )

        assert result.should_respond is False

    @pytest.mark.asyncio
    async def test_should_respond_guild_enabled(
        self, mock_discord_message: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """Guild config enabled=true proceeds to channel check."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True
        mock_guild_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_invocation = False
        mock_channel_config.thread_only_mode = False
        mock_channel_config.persona_override_id = None

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = await should_respond(
                    mock_discord_message, "tenant1", mock_bot_user
                )

        assert result.should_respond is True

    @pytest.mark.asyncio
    async def test_should_respond_channel_disabled(
        self, mock_discord_message: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """Channel config enabled=false returns False."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = False

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = await should_respond(
                    mock_discord_message, "tenant1", mock_bot_user
                )

        assert result.should_respond is False

    @pytest.mark.asyncio
    async def test_should_respond_channel_enabled(
        self, mock_discord_message: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """Channel config enabled=true proceeds to mention check."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True
        mock_guild_config.default_persona_id = 2

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_invocation = False
        mock_channel_config.thread_only_mode = False
        mock_channel_config.persona_override_id = None

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = await should_respond(
                    mock_discord_message, "tenant1", mock_bot_user
                )

        assert result.should_respond is True
        assert result.persona_id == 2

    @pytest.mark.asyncio
    async def test_should_respond_channel_not_found(
        self, mock_discord_message: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """No channel config returns False (not whitelisted)."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=None,  # No config
                ),
            ):
                result = await should_respond(
                    mock_discord_message, "tenant1", mock_bot_user
                )

        assert result.should_respond is False

    @pytest.mark.asyncio
    async def test_should_respond_require_mention_true_no_mention(
        self, mock_discord_message: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """require_bot_invocation=true with no @mention returns False."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True
        mock_guild_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_invocation = True
        mock_channel_config.thread_only_mode = False
        mock_channel_config.persona_override_id = None

        # No bot mention
        mock_discord_message.mentions = []

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.check_implicit_invocation",
                    return_value=False,
                ),
            ):
                result = await should_respond(
                    mock_discord_message, "tenant1", mock_bot_user
                )

        assert result.should_respond is False

    @pytest.mark.asyncio
    async def test_should_respond_require_mention_true_with_mention(
        self, mock_message_with_bot_mention: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """require_bot_invocation=true with @mention returns True."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True
        mock_guild_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_invocation = True
        mock_channel_config.thread_only_mode = False
        mock_channel_config.persona_override_id = None

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = await should_respond(
                    mock_message_with_bot_mention, "tenant1", mock_bot_user
                )

        assert result.should_respond is True

    @pytest.mark.asyncio
    async def test_should_respond_require_mention_false_no_mention(
        self, mock_discord_message: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """require_bot_invocation=false with no @mention returns True."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True
        mock_guild_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_invocation = False
        mock_channel_config.thread_only_mode = False
        mock_channel_config.persona_override_id = None

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = await should_respond(
                    mock_discord_message, "tenant1", mock_bot_user
                )

        assert result.should_respond is True


class TestImplicitShouldRespond:
    """Tests for implicit invocation (no @mention required in certain contexts)."""

    @pytest.mark.asyncio
    async def test_implicit_respond_reply_to_bot_message(
        self, mock_bot_user: MagicMock
    ) -> None:
        """User replies to a bot message returns True."""
        # Create a message that replies to the bot
        msg = MagicMock(spec=discord.Message)
        msg.reference = MagicMock()
        msg.reference.message_id = 12345

        # Mock the referenced message as a bot message
        referenced_msg = MagicMock()
        referenced_msg.author.id = mock_bot_user.id

        msg.channel = MagicMock()
        msg.channel.fetch_message = AsyncMock(return_value=referenced_msg)

        result = await check_implicit_invocation(msg, mock_bot_user)
        assert result is True

    @pytest.mark.asyncio
    async def test_implicit_respond_reply_to_user_message(
        self, mock_bot_user: MagicMock
    ) -> None:
        """User replies to another user's message returns False."""
        msg = MagicMock(spec=discord.Message)
        msg.reference = MagicMock()
        msg.reference.message_id = 12345

        # Mock the referenced message as a user message
        referenced_msg = MagicMock()
        referenced_msg.author.id = 999999  # Different from bot

        msg.channel = MagicMock()
        msg.channel.fetch_message = AsyncMock(return_value=referenced_msg)

        result = await check_implicit_invocation(msg, mock_bot_user)
        assert result is False

    @pytest.mark.asyncio
    async def test_implicit_respond_in_bot_owned_thread(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Message in thread owned by bot returns True."""
        thread = MagicMock(spec=discord.Thread)
        thread.owner_id = mock_bot_user.id  # Bot owns the thread
        thread.parent = MagicMock(spec=discord.TextChannel)

        msg = MagicMock(spec=discord.Message)
        msg.reference = None
        msg.channel = thread

        result = await check_implicit_invocation(msg, mock_bot_user)
        assert result is True

    @pytest.mark.asyncio
    async def test_implicit_respond_in_user_owned_thread(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Message in thread owned by user returns False."""
        thread = MagicMock(spec=discord.Thread)
        thread.owner_id = 999999  # User owns the thread
        thread.parent = MagicMock(spec=discord.TextChannel)

        msg = MagicMock(spec=discord.Message)
        msg.reference = None
        msg.channel = thread

        result = await check_implicit_invocation(msg, mock_bot_user)
        assert result is False

    @pytest.mark.asyncio
    async def test_implicit_respond_reply_in_bot_thread(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Reply to user in bot-owned thread returns True (thread context)."""
        thread = MagicMock(spec=discord.Thread)
        thread.owner_id = mock_bot_user.id
        thread.parent = MagicMock(spec=discord.TextChannel)

        # User replying to another user in bot's thread
        referenced_msg = MagicMock()
        referenced_msg.author.id = 888888  # Another user

        msg = MagicMock(spec=discord.Message)
        msg.reference = MagicMock()
        msg.reference.message_id = 12345
        msg.channel = thread
        msg.channel.fetch_message = AsyncMock(return_value=referenced_msg)

        result = await check_implicit_invocation(msg, mock_bot_user)
        # Should return True because it's in bot's thread
        assert result is True

    @pytest.mark.asyncio
    async def test_implicit_respond_thread_from_bot_message(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Thread created from bot message (non-forum) returns True."""
        thread = MagicMock(spec=discord.Thread)
        thread.id = 777777
        thread.owner_id = 999999  # User owns thread but...
        thread.parent = MagicMock(spec=discord.TextChannel)

        # The starter message is from the bot
        starter_msg = MagicMock()
        starter_msg.author.id = mock_bot_user.id
        thread.parent.fetch_message = AsyncMock(return_value=starter_msg)

        msg = MagicMock(spec=discord.Message)
        msg.reference = None
        msg.channel = thread

        result = await check_implicit_invocation(msg, mock_bot_user)
        assert result is True

    @pytest.mark.asyncio
    async def test_implicit_respond_forum_channel_excluded(
        self, mock_bot_user: MagicMock, mock_thread_forum_parent: MagicMock
    ) -> None:
        """Thread parent is ForumChannel - does NOT check starter message."""
        msg = MagicMock(spec=discord.Message)
        msg.reference = None
        msg.channel = mock_thread_forum_parent
        mock_thread_forum_parent.owner_id = 999999  # Not bot

        result = await check_implicit_invocation(msg, mock_bot_user)
        # Should be False - forum threads don't use starter message check
        assert result is False

    @pytest.mark.asyncio
    async def test_implicit_respond_combined_with_mention(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Has @mention AND is implicit - should return True (either works)."""
        thread = MagicMock(spec=discord.Thread)
        thread.owner_id = mock_bot_user.id
        thread.parent = MagicMock(spec=discord.TextChannel)

        msg = MagicMock(spec=discord.Message)
        msg.reference = None
        msg.channel = thread
        msg.mentions = [mock_bot_user]

        result = await check_implicit_invocation(msg, mock_bot_user)
        assert result is True

    @pytest.mark.asyncio
    async def test_implicit_respond_reference_fetch_fails(
        self, mock_bot_user: MagicMock
    ) -> None:
        """discord.NotFound when fetching reply reference returns False."""
        msg = MagicMock(spec=discord.Message)
        msg.reference = MagicMock()
        msg.reference.message_id = 12345
        msg.channel = MagicMock()
        msg.channel.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "Not found")
        )

        result = await check_implicit_invocation(msg, mock_bot_user)
        assert result is False

    @pytest.mark.asyncio
    async def test_implicit_respond_http_exception(
        self, mock_bot_user: MagicMock
    ) -> None:
        """discord.HTTPException during check returns False."""
        msg = MagicMock(spec=discord.Message)
        msg.reference = MagicMock()
        msg.reference.message_id = 12345
        msg.channel = MagicMock()
        msg.channel.fetch_message = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(), "HTTP error")
        )

        result = await check_implicit_invocation(msg, mock_bot_user)
        assert result is False


class TestThreadOnlyMode:
    """Tests for thread_only_mode behavior."""

    @pytest.mark.asyncio
    async def test_thread_only_mode_message_in_thread(
        self, mock_bot_user: MagicMock
    ) -> None:
        """thread_only_mode=true, message in thread returns True."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True
        mock_guild_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_invocation = False
        mock_channel_config.thread_only_mode = True
        mock_channel_config.persona_override_id = None

        # Create thread message
        thread = MagicMock(spec=discord.Thread)
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.id = 111111111

        msg = MagicMock(spec=discord.Message)
        msg.guild = MagicMock()
        msg.guild.id = 987654321
        msg.channel = thread
        msg.mentions = []
        msg.reference = None

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = await should_respond(msg, "tenant1", mock_bot_user)

        assert result.should_respond is True
        assert result.thread_only_mode is True

    @pytest.mark.asyncio
    async def test_thread_only_mode_false_message_in_channel(
        self, mock_discord_message: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """thread_only_mode=false, message in channel returns True."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True
        mock_guild_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_invocation = False
        mock_channel_config.thread_only_mode = False
        mock_channel_config.persona_override_id = None

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = await should_respond(
                    mock_discord_message, "tenant1", mock_bot_user
                )

        assert result.should_respond is True
        assert result.thread_only_mode is False


class TestEdgeCases:
    """Edge case tests for should_respond."""

    @pytest.mark.asyncio
    async def test_should_respond_no_guild(self, mock_bot_user: MagicMock) -> None:
        """Message without guild (DM) returns False."""
        msg = MagicMock(spec=discord.Message)
        msg.guild = None

        result = await should_respond(msg, "tenant1", mock_bot_user)
        assert result.should_respond is False

    @pytest.mark.asyncio
    async def test_should_respond_thread_uses_parent_channel_config(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Thread under channel uses parent channel's config."""
        mock_guild_config = MagicMock()
        mock_guild_config.enabled = True
        mock_guild_config.default_persona_id = 1

        mock_channel_config = MagicMock()
        mock_channel_config.enabled = True
        mock_channel_config.require_bot_invocation = False
        mock_channel_config.thread_only_mode = False
        mock_channel_config.persona_override_id = 5  # Specific persona

        # Create thread message
        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.id = 111111111  # Parent channel ID

        msg = MagicMock(spec=discord.Message)
        msg.guild = MagicMock()
        msg.guild.id = 987654321
        msg.channel = thread
        msg.mentions = []
        msg.reference = None

        with patch(
            "onyx.onyxbot.discord.handle_message.get_session_with_tenant"
        ) as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            with (
                patch(
                    "onyx.onyxbot.discord.handle_message.get_guild_config_by_discord_id",
                    return_value=mock_guild_config,
                ),
                patch(
                    "onyx.onyxbot.discord.handle_message.get_channel_config_by_discord_ids",
                    return_value=mock_channel_config,
                ),
            ):
                result = await should_respond(msg, "tenant1", mock_bot_user)

        assert result.should_respond is True
        # Should use parent's persona override
        assert result.persona_id == 5
