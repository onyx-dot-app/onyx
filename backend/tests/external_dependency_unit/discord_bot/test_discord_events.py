"""Tests for Discord bot event handling with mocked Discord API.

These tests mock the Discord API to test event handling logic.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import discord
import pytest

from onyx.onyxbot.discord.handle_commands import get_text_channels
from onyx.onyxbot.discord.handle_commands import handle_dm
from onyx.onyxbot.discord.handle_commands import handle_registration_command
from onyx.onyxbot.discord.handle_commands import handle_sync_channels_command
from onyx.onyxbot.discord.handle_message import process_chat_message
from onyx.onyxbot.discord.handle_message import send_error_response
from onyx.onyxbot.discord.handle_message import send_response


class TestGuildRegistrationCommand:
    """Tests for !register command handling."""

    @pytest.mark.asyncio
    async def test_register_guild_success(
        self,
        mock_discord_message: MagicMock,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Valid registration key with admin perms succeeds."""
        mock_discord_message.content = "!register discord_public.valid_token"

        with (
            patch(
                "onyx.onyxbot.discord.handle_commands.parse_discord_registration_key",
                return_value="public",
            ),
            patch(
                "onyx.onyxbot.discord.handle_commands.get_session_with_tenant"
            ) as mock_session,
            patch(
                "onyx.onyxbot.discord.handle_commands.get_guild_config_by_registration_key"
            ) as mock_get_config,
            patch("onyx.onyxbot.discord.handle_commands.bulk_create_channel_configs"),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            mock_config = MagicMock()
            mock_config.id = 1
            mock_config.guild_id = None  # Not yet registered
            mock_get_config.return_value = mock_config

            mock_cache_manager.get_tenant.return_value = None  # Not in cache yet

            result = await handle_registration_command(
                mock_discord_message, mock_cache_manager
            )

        assert result is True
        mock_discord_message.reply.assert_called()
        # Check that success message was sent
        call_args = mock_discord_message.reply.call_args
        assert "Successfully registered" in str(call_args)

    @pytest.mark.asyncio
    async def test_register_invalid_key_format(
        self,
        mock_discord_message: MagicMock,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Malformed key DMs user and deletes message."""
        mock_discord_message.content = "!register abc"  # Malformed

        with patch(
            "onyx.onyxbot.discord.handle_commands.parse_discord_registration_key",
            return_value=None,  # Invalid format
        ):
            result = await handle_registration_command(
                mock_discord_message, mock_cache_manager
            )

        assert result is True
        # On failure: DM the author and delete the message
        mock_discord_message.author.send.assert_called()
        call_args = mock_discord_message.author.send.call_args
        assert "Invalid" in str(call_args)
        mock_discord_message.delete.assert_called()

    @pytest.mark.asyncio
    async def test_register_key_not_found(
        self,
        mock_discord_message: MagicMock,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Key not in database DMs user and deletes message."""
        mock_discord_message.content = "!register discord_public.notexist"

        with (
            patch(
                "onyx.onyxbot.discord.handle_commands.parse_discord_registration_key",
                return_value="public",
            ),
            patch(
                "onyx.onyxbot.discord.handle_commands.get_session_with_tenant"
            ) as mock_session,
            patch(
                "onyx.onyxbot.discord.handle_commands.get_guild_config_by_registration_key",
                return_value=None,  # Not found
            ),
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            # Must return False so exceptions are not suppressed
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_cache_manager.get_tenant.return_value = None

            result = await handle_registration_command(
                mock_discord_message, mock_cache_manager
            )

        assert result is True
        # On failure: DM the author and delete the message
        mock_discord_message.author.send.assert_called()
        call_args = mock_discord_message.author.send.call_args
        assert "not found" in str(call_args).lower()
        mock_discord_message.delete.assert_called()

    @pytest.mark.asyncio
    async def test_register_key_already_used(
        self,
        mock_discord_message: MagicMock,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Previously used key DMs user and deletes message."""
        mock_discord_message.content = "!register discord_public.used_key"

        with (
            patch(
                "onyx.onyxbot.discord.handle_commands.parse_discord_registration_key",
                return_value="public",
            ),
            patch(
                "onyx.onyxbot.discord.handle_commands.get_session_with_tenant"
            ) as mock_session,
            patch(
                "onyx.onyxbot.discord.handle_commands.get_guild_config_by_registration_key"
            ) as mock_get_config,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            # Must return False so exceptions are not suppressed
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            mock_config = MagicMock()
            mock_config.guild_id = 999999  # Already registered!
            mock_get_config.return_value = mock_config

            mock_cache_manager.get_tenant.return_value = None

            result = await handle_registration_command(
                mock_discord_message, mock_cache_manager
            )

        assert result is True
        # On failure: DM the author and delete the message
        mock_discord_message.author.send.assert_called()
        call_args = mock_discord_message.author.send.call_args
        assert "already" in str(call_args).lower()
        mock_discord_message.delete.assert_called()

    @pytest.mark.asyncio
    async def test_register_guild_already_registered(
        self,
        mock_discord_message: MagicMock,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Guild already in cache DMs user and deletes message."""
        mock_discord_message.content = "!register discord_public.valid_token"

        with patch(
            "onyx.onyxbot.discord.handle_commands.parse_discord_registration_key",
            return_value="public",
        ):
            # Guild already in cache
            mock_cache_manager.get_tenant.return_value = "existing_tenant"

            result = await handle_registration_command(
                mock_discord_message, mock_cache_manager
            )

        assert result is True
        # On failure: DM the author and delete the message
        mock_discord_message.author.send.assert_called()
        call_args = mock_discord_message.author.send.call_args
        assert "already registered" in str(call_args).lower()
        mock_discord_message.delete.assert_called()

    @pytest.mark.asyncio
    async def test_register_no_permission(
        self,
        mock_discord_message: MagicMock,
        mock_cache_manager: MagicMock,
    ) -> None:
        """User without admin perms gets DM and message deleted."""
        mock_discord_message.content = "!register discord_public.valid_token"
        mock_discord_message.author.guild_permissions.administrator = False
        mock_discord_message.author.guild_permissions.manage_guild = False

        result = await handle_registration_command(
            mock_discord_message, mock_cache_manager
        )

        assert result is True
        # On failure: DM the author and delete the message
        mock_discord_message.author.send.assert_called()
        call_args = mock_discord_message.author.send.call_args
        assert "permission" in str(call_args).lower()
        mock_discord_message.delete.assert_called()

    @pytest.mark.asyncio
    async def test_register_in_dm(
        self,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Registration in DM sends DM and returns True."""
        msg = MagicMock(spec=discord.Message)
        msg.guild = None  # DM
        msg.content = "!register discord_public.token"
        msg.author = MagicMock()
        msg.author.send = AsyncMock()

        result = await handle_registration_command(msg, mock_cache_manager)

        assert result is True
        msg.author.send.assert_called()
        call_args = msg.author.send.call_args
        assert "server" in str(call_args).lower()

    @pytest.mark.asyncio
    async def test_register_syncs_forum_channels(
        self,
        mock_discord_message: MagicMock,
        mock_discord_guild: MagicMock,
    ) -> None:
        """Forum channels are included in sync."""
        channels = get_text_channels(mock_discord_guild)

        channel_types = [c.channel_type for c in channels]
        assert "forum" in channel_types

    @pytest.mark.asyncio
    async def test_register_private_channel_detection(
        self,
        mock_discord_message: MagicMock,
        mock_discord_guild: MagicMock,
    ) -> None:
        """Private channels are marked correctly."""
        channels = get_text_channels(mock_discord_guild)

        private_channels = [c for c in channels if c.is_private]
        assert len(private_channels) >= 1


class TestSyncChannelsCommand:
    """Tests for !sync-channels command handling."""

    @pytest.mark.asyncio
    async def test_sync_channels_adds_new(
        self,
        mock_discord_message: MagicMock,
        mock_discord_bot: MagicMock,
    ) -> None:
        """New channel in Discord creates channel config."""
        mock_discord_message.content = "!sync-channels"

        with (
            patch(
                "onyx.onyxbot.discord.handle_commands.get_session_with_tenant"
            ) as mock_session,
            patch(
                "onyx.onyxbot.discord.handle_commands.get_guild_config_by_discord_id"
            ) as mock_get_guild,
            patch(
                "onyx.onyxbot.discord.handle_commands.get_guild_config_by_internal_id"
            ) as mock_get_guild_internal,
            patch(
                "onyx.onyxbot.discord.handle_commands.sync_channel_configs"
            ) as mock_sync,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock()

            mock_config = MagicMock()
            mock_config.id = 1
            mock_config.guild_id = 123456789
            mock_get_guild.return_value = mock_config
            mock_get_guild_internal.return_value = mock_config

            mock_sync.return_value = (1, 0, 0)  # 1 added, 0 removed, 0 updated

            mock_discord_bot.get_guild.return_value = mock_discord_message.guild

            result = await handle_sync_channels_command(
                mock_discord_message, "public", mock_discord_bot
            )

        assert result is True
        mock_discord_message.reply.assert_called()

    @pytest.mark.asyncio
    async def test_sync_channels_no_permission(
        self,
        mock_discord_message: MagicMock,
        mock_discord_bot: MagicMock,
    ) -> None:
        """User without admin perms gets DM and reaction."""
        mock_discord_message.content = "!sync-channels"
        mock_discord_message.author.guild_permissions.administrator = False
        mock_discord_message.author.guild_permissions.manage_guild = False

        result = await handle_sync_channels_command(
            mock_discord_message, "public", mock_discord_bot
        )

        assert result is True
        # On failure: DM the author and react with ❌
        mock_discord_message.author.send.assert_called()
        call_args = mock_discord_message.author.send.call_args
        assert "permission" in str(call_args).lower()
        mock_discord_message.add_reaction.assert_called_with("❌")

    @pytest.mark.asyncio
    async def test_sync_channels_unregistered_guild(
        self,
        mock_discord_message: MagicMock,
        mock_discord_bot: MagicMock,
    ) -> None:
        """Sync in unregistered guild gets DM and reaction."""
        mock_discord_message.content = "!sync-channels"

        # tenant_id is None = not registered
        result = await handle_sync_channels_command(
            mock_discord_message, None, mock_discord_bot
        )

        assert result is True
        # On failure: DM the author and react with ❌
        mock_discord_message.author.send.assert_called()
        call_args = mock_discord_message.author.send.call_args
        assert "not registered" in str(call_args).lower()
        mock_discord_message.add_reaction.assert_called_with("❌")


class TestMessageHandling:
    """Tests for message handling behavior."""

    @pytest.mark.asyncio
    async def test_message_adds_thinking_emoji(
        self,
        mock_discord_message: MagicMock,
        mock_api_client: MagicMock,
        mock_bot_user: MagicMock,
    ) -> None:
        """Thinking emoji is added during processing."""
        await process_chat_message(
            message=mock_discord_message,
            api_key="test_key",
            persona_id=None,
            thread_only_mode=False,
            api_client=mock_api_client,
            bot_user=mock_bot_user,
        )

        mock_discord_message.add_reaction.assert_called()

    @pytest.mark.asyncio
    async def test_message_removes_thinking_emoji(
        self,
        mock_discord_message: MagicMock,
        mock_api_client: MagicMock,
        mock_bot_user: MagicMock,
    ) -> None:
        """Thinking emoji is removed after response."""
        await process_chat_message(
            message=mock_discord_message,
            api_key="test_key",
            persona_id=None,
            thread_only_mode=False,
            api_client=mock_api_client,
            bot_user=mock_bot_user,
        )

        mock_discord_message.remove_reaction.assert_called()

    @pytest.mark.asyncio
    async def test_message_reaction_failure_non_blocking(
        self,
        mock_discord_message: MagicMock,
        mock_api_client: MagicMock,
        mock_bot_user: MagicMock,
    ) -> None:
        """add_reaction failure doesn't block processing."""
        mock_discord_message.add_reaction = AsyncMock(
            side_effect=discord.DiscordException("Cannot add reaction")
        )

        # Should not raise - just log warning and continue
        await process_chat_message(
            message=mock_discord_message,
            api_key="test_key",
            persona_id=None,
            thread_only_mode=False,
            api_client=mock_api_client,
            bot_user=mock_bot_user,
        )

        # Should still complete and send reply
        mock_discord_message.reply.assert_called()

    @pytest.mark.asyncio
    async def test_dm_response(self) -> None:
        """DM to bot sends redirect message."""
        msg = MagicMock(spec=discord.Message)
        msg.channel = MagicMock(spec=discord.DMChannel)
        msg.channel.send = AsyncMock()

        await handle_dm(msg)

        msg.channel.send.assert_called_once()
        call_args = msg.channel.send.call_args
        assert "DM" in str(call_args) or "server" in str(call_args).lower()


class TestThreadCreationAndResponseRouting:
    """Tests for thread creation and response routing."""

    @pytest.mark.asyncio
    async def test_response_in_existing_thread(
        self,
        mock_bot_user: MagicMock,
    ) -> None:
        """Message in thread - response appended to thread."""
        thread = MagicMock(spec=discord.Thread)
        thread.send = AsyncMock()

        msg = MagicMock(spec=discord.Message)
        msg.channel = thread
        msg.reply = AsyncMock()
        msg.create_thread = AsyncMock()

        await send_response(msg, "Test response", thread_only_mode=False)

        # Should send to thread, not create new thread
        thread.send.assert_called()
        msg.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_response_creates_thread_thread_only_mode(
        self,
        mock_discord_message: MagicMock,
        mock_bot_user: MagicMock,
    ) -> None:
        """thread_only_mode=true creates new thread for response."""
        mock_thread = MagicMock()
        mock_thread.send = AsyncMock()
        mock_discord_message.create_thread = AsyncMock(return_value=mock_thread)

        # Make sure it's not a thread
        mock_discord_message.channel = MagicMock(spec=discord.TextChannel)

        await send_response(
            mock_discord_message, "Test response", thread_only_mode=True
        )

        mock_discord_message.create_thread.assert_called()
        mock_thread.send.assert_called()

    @pytest.mark.asyncio
    async def test_response_replies_inline(
        self,
        mock_discord_message: MagicMock,
        mock_bot_user: MagicMock,
    ) -> None:
        """thread_only_mode=false uses message.reply()."""
        # Make sure it's not a thread
        mock_discord_message.channel = MagicMock(spec=discord.TextChannel)

        await send_response(
            mock_discord_message, "Test response", thread_only_mode=False
        )

        mock_discord_message.reply.assert_called()

    @pytest.mark.asyncio
    async def test_thread_name_truncation(
        self,
        mock_bot_user: MagicMock,
    ) -> None:
        """Thread name is truncated to 100 chars."""
        msg = MagicMock(spec=discord.Message)
        msg.channel = MagicMock(spec=discord.TextChannel)
        msg.author = MagicMock()
        msg.author.display_name = "A" * 200  # Very long name

        mock_thread = MagicMock()
        mock_thread.send = AsyncMock()
        msg.create_thread = AsyncMock(return_value=mock_thread)

        await send_response(msg, "Test", thread_only_mode=True)

        call_args = msg.create_thread.call_args
        thread_name = call_args.kwargs.get("name") or call_args[1].get("name")
        assert len(thread_name) <= 100

    @pytest.mark.asyncio
    async def test_error_response_creates_thread(
        self,
        mock_discord_message: MagicMock,
        mock_bot_user: MagicMock,
    ) -> None:
        """Error response in channel creates thread."""
        mock_discord_message.channel = MagicMock(spec=discord.TextChannel)
        mock_thread = MagicMock()
        mock_thread.send = AsyncMock()
        mock_discord_message.create_thread = AsyncMock(return_value=mock_thread)

        await send_error_response(mock_discord_message, mock_bot_user)

        mock_discord_message.create_thread.assert_called()


class TestBotLifecycle:
    """Tests for bot lifecycle management."""

    @pytest.mark.asyncio
    async def test_setup_hook_initializes_cache(
        self,
        mock_cache_manager: MagicMock,
        mock_api_client: MagicMock,
    ) -> None:
        """setup_hook calls cache.refresh_all()."""
        from onyx.onyxbot.discord.client import OnyxDiscordClient

        with (
            patch.object(OnyxDiscordClient, "__init__", lambda self: None),
            patch(
                "onyx.onyxbot.discord.client.DiscordCacheManager",
                return_value=mock_cache_manager,
            ),
            patch(
                "onyx.onyxbot.discord.client.OnyxAPIClient",
                return_value=mock_api_client,
            ),
        ):
            bot = OnyxDiscordClient()
            bot.cache = mock_cache_manager
            bot.api_client = mock_api_client
            bot.loop = MagicMock()
            bot.loop.create_task = MagicMock()

            await bot.setup_hook()

        mock_cache_manager.refresh_all.assert_called()

    @pytest.mark.asyncio
    async def test_setup_hook_initializes_api_client(
        self,
        mock_cache_manager: MagicMock,
        mock_api_client: MagicMock,
    ) -> None:
        """setup_hook calls api_client.initialize()."""
        from onyx.onyxbot.discord.client import OnyxDiscordClient

        with (patch.object(OnyxDiscordClient, "__init__", lambda self: None),):
            bot = OnyxDiscordClient()
            bot.cache = mock_cache_manager
            bot.api_client = mock_api_client
            bot.loop = MagicMock()
            bot.loop.create_task = MagicMock()

            await bot.setup_hook()

        mock_api_client.initialize.assert_called()

    @pytest.mark.asyncio
    async def test_close_closes_api_client(
        self,
        mock_cache_manager: MagicMock,
        mock_api_client: MagicMock,
    ) -> None:
        """close() calls api_client.close()."""
        from onyx.onyxbot.discord.client import OnyxDiscordClient

        with (
            patch.object(OnyxDiscordClient, "__init__", lambda self: None),
            patch.object(OnyxDiscordClient, "is_closed", return_value=True),
        ):
            bot = OnyxDiscordClient()
            bot.cache = mock_cache_manager
            bot.api_client = mock_api_client
            bot._cache_refresh_task = None
            bot.ready = True

            # Mock parent close
            async def mock_super_close() -> None:
                pass

            with patch("discord.ext.commands.Bot.close", mock_super_close):
                await bot.close()

        mock_api_client.close.assert_called()
        mock_cache_manager.clear.assert_called()
