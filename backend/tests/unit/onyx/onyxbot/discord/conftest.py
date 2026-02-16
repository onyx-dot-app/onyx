"""Fixtures for Discord bot unit tests."""

import random
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import discord
import pytest


class AsyncIteratorMock:
    """Helper class to mock async iterators like channel.history()."""

    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.index = 0

    def __aiter__(self) -> "AsyncIteratorMock":
        return self

    async def __anext__(self) -> Any:
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


def mock_message(
    content: str = "Test message",
    author_bot: bool = False,
    message_type: discord.MessageType = discord.MessageType.default,
    reference: MagicMock | None = None,
    message_id: int | None = None,
    author_id: int | None = None,
    author_display_name: str | None = None,
) -> MagicMock:
    """Helper to create mock Discord messages."""
    msg = MagicMock(spec=discord.Message)
    msg.id = message_id or random.randint(100000, 999999)
    msg.content = content
    msg.author = MagicMock()
    msg.author.id = author_id or random.randint(100000, 999999)
    msg.author.bot = author_bot
    msg.author.display_name = author_display_name or ("Bot" if author_bot else "User")
    msg.type = message_type
    msg.reference = reference
    msg.mentions = []
    msg.role_mentions = []
    msg.channel_mentions = []
    return msg


@pytest.fixture
def mock_bot_user() -> MagicMock:
    """Mock Discord bot user."""
    user = MagicMock(spec=discord.ClientUser)
    user.id = 123456789
    user.display_name = "OnyxBot"
    user.bot = True
    return user


@pytest.fixture
def mock_discord_guild() -> MagicMock:
    """Mock Discord guild with channels."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 987654321
    guild.name = "Test Server"
    guild.default_role = MagicMock()

    # Create some mock channels
    text_channel = MagicMock(spec=discord.TextChannel)
    text_channel.id = 111111111
    text_channel.name = "general"
    text_channel.type = discord.ChannelType.text
    perms = MagicMock()
    perms.view_channel = True
    text_channel.permissions_for.return_value = perms

    forum_channel = MagicMock(spec=discord.ForumChannel)
    forum_channel.id = 222222222
    forum_channel.name = "forum"
    forum_channel.type = discord.ChannelType.forum
    forum_channel.permissions_for.return_value = perms

    guild.channels = [text_channel, forum_channel]
    guild.text_channels = [text_channel]
    guild.forum_channels = [forum_channel]

    return guild


@pytest.fixture
def mock_discord_message(mock_bot_user: MagicMock) -> MagicMock:  # noqa: ARG001
    """Mock Discord message for testing."""
    msg = MagicMock(spec=discord.Message)
    msg.id = 555555555
    msg.author = MagicMock()
    msg.author.id = 444444444
    msg.author.bot = False
    msg.author.display_name = "TestUser"
    msg.content = "Hello bot"
    msg.guild = MagicMock()
    msg.guild.id = 987654321
    msg.guild.name = "Test Server"
    msg.channel = MagicMock()
    msg.channel.id = 111111111
    msg.channel.name = "general"
    msg.type = discord.MessageType.default
    msg.mentions = []
    msg.role_mentions = []
    msg.channel_mentions = []
    msg.reference = None
    return msg


@pytest.fixture
def mock_thread_with_messages(mock_bot_user: MagicMock) -> MagicMock:
    """Mock Discord thread with message history."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = 666666666
    thread.name = "Test Thread"
    thread.owner_id = mock_bot_user.id
    thread.parent = MagicMock(spec=discord.TextChannel)
    thread.parent.id = 111111111

    # Mock starter message
    starter = mock_message(
        content="Thread starter message",
        author_bot=False,
        message_id=thread.id,
    )

    messages = [
        mock_message(author_bot=False, content="User msg 1", message_id=100),
        mock_message(author_bot=True, content="Bot response", message_id=101),
        mock_message(author_bot=False, content="User msg 2", message_id=102),
    ]

    # Setup async iterator for history
    def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
        return AsyncIteratorMock(messages)

    thread.history = history

    # Mock parent.fetch_message
    async def fetch_starter(msg_id: int) -> MagicMock:
        if msg_id == thread.id:
            return starter
        raise discord.NotFound(MagicMock(), "Not found")

    thread.parent.fetch_message = AsyncMock(side_effect=fetch_starter)

    return thread


@pytest.fixture
def mock_thread_forum_parent() -> MagicMock:
    """Mock thread with ForumChannel parent (special case)."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = 777777777
    thread.name = "Forum Post"
    thread.parent = MagicMock(spec=discord.ForumChannel)
    thread.parent.id = 222222222
    return thread


@pytest.fixture
def mock_reply_chain() -> MagicMock:
    """Mock message with reply chain."""
    # Build chain backwards: msg3 -> msg2 -> msg1
    ref3 = MagicMock()
    ref3.message_id = 1003

    ref2 = MagicMock()
    ref2.message_id = 1002

    msg3 = mock_message(content="Third message", reference=None, message_id=1003)
    msg2 = mock_message(content="Second message", reference=ref3, message_id=1002)
    msg1 = mock_message(content="First message", reference=ref2, message_id=1001)

    # Store messages for lookup
    msg1._chain = {1002: msg2, 1003: msg3}
    msg2._chain = {1003: msg3}

    return msg1


@pytest.fixture
def mock_guild_config_enabled() -> MagicMock:
    """Guild config that is enabled."""
    config = MagicMock()
    config.id = 1
    config.guild_id = 987654321
    config.enabled = True
    config.default_persona_id = 1
    return config


@pytest.fixture
def mock_guild_config_disabled() -> MagicMock:
    """Guild config that is disabled."""
    config = MagicMock()
    config.id = 2
    config.guild_id = 987654321
    config.enabled = False
    config.default_persona_id = None
    return config


@pytest.fixture
def mock_channel_config_factory() -> Callable[..., MagicMock]:
    """Factory fixture for creating channel configs with various settings."""

    def _make_config(
        enabled: bool = True,
        require_bot_invocation: bool = True,
        thread_only_mode: bool = False,
        persona_override_id: int | None = None,
    ) -> MagicMock:
        config = MagicMock()
        config.id = random.randint(1, 1000)
        config.channel_id = 111111111
        config.enabled = enabled
        config.require_bot_invocation = require_bot_invocation
        config.thread_only_mode = thread_only_mode
        config.persona_override_id = persona_override_id
        return config

    return _make_config


@pytest.fixture
def mock_message_with_bot_mention(mock_bot_user: MagicMock) -> MagicMock:
    """Message that mentions the bot."""
    msg = MagicMock(spec=discord.Message)
    msg.id = 888888888
    msg.mentions = [mock_bot_user]
    msg.author = MagicMock()
    msg.author.id = 444444444
    msg.author.bot = False
    msg.author.display_name = "TestUser"
    msg.type = discord.MessageType.default
    msg.content = f"<@{mock_bot_user.id}> hello"
    msg.reference = None
    msg.guild = MagicMock()
    msg.guild.id = 987654321
    msg.channel = MagicMock()
    msg.channel.id = 111111111
    msg.role_mentions = []
    msg.channel_mentions = []
    return msg


@pytest.fixture
def mock_guild_with_members() -> MagicMock:
    """Mock guild for mention resolution."""
    guild = MagicMock(spec=discord.Guild)

    def get_member(member_id: int) -> MagicMock:
        member = MagicMock()
        member.display_name = f"User{member_id}"
        return member

    def get_role(role_id: int) -> MagicMock:
        role = MagicMock()
        role.name = f"Role{role_id}"
        return role

    def get_channel(channel_id: int) -> MagicMock:
        channel = MagicMock()
        channel.name = f"channel{channel_id}"
        return channel

    guild.get_member = get_member
    guild.get_role = get_role
    guild.get_channel = get_channel
    return guild
