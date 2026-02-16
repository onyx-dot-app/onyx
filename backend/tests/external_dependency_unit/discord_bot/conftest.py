"""Fixtures for Discord bot external dependency tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import discord
import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


TEST_TENANT_ID: str = "public"


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Create a database session for testing."""
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    """Set up tenant context for testing."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture
def mock_cache_manager() -> MagicMock:
    """Mock DiscordCacheManager."""
    cache = MagicMock()
    cache.get_tenant.return_value = TEST_TENANT_ID
    cache.get_api_key.return_value = "test_api_key"
    cache.refresh_all = AsyncMock()
    cache.refresh_guild = AsyncMock()
    cache.is_initialized = True
    return cache


@pytest.fixture
def mock_api_client() -> MagicMock:
    """Mock OnyxAPIClient."""
    client = MagicMock()
    client.initialize = AsyncMock()
    client.close = AsyncMock()
    client.is_initialized = True

    # Mock successful response
    mock_response = MagicMock()
    mock_response.answer = "Test response from bot"
    mock_response.citation_info = None
    mock_response.top_documents = None
    mock_response.error_msg = None

    client.send_chat_message = AsyncMock(return_value=mock_response)
    client.health_check = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_discord_guild() -> MagicMock:
    """Mock Discord guild with channels."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 123456789
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

    private_channel = MagicMock(spec=discord.TextChannel)
    private_channel.id = 333333333
    private_channel.name = "private"
    private_channel.type = discord.ChannelType.text
    private_perms = MagicMock()
    private_perms.view_channel = False
    private_channel.permissions_for.return_value = private_perms

    guild.channels = [text_channel, forum_channel, private_channel]
    guild.text_channels = [text_channel, private_channel]
    guild.forum_channels = [forum_channel]

    return guild


@pytest.fixture
def mock_discord_message(mock_discord_guild: MagicMock) -> MagicMock:
    """Mock Discord message for testing."""
    msg = MagicMock(spec=discord.Message)
    msg.id = 555555555
    msg.author = MagicMock(spec=discord.Member)
    msg.author.id = 444444444
    msg.author.bot = False
    msg.author.display_name = "TestUser"
    msg.author.guild_permissions = MagicMock()
    msg.author.guild_permissions.administrator = True
    msg.author.guild_permissions.manage_guild = True
    msg.content = "Hello bot"
    msg.guild = mock_discord_guild
    msg.channel = MagicMock()
    msg.channel.id = 111111111
    msg.channel.name = "general"
    msg.channel.send = AsyncMock()
    msg.type = discord.MessageType.default
    msg.mentions = []
    msg.role_mentions = []
    msg.channel_mentions = []
    msg.reference = None
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.create_thread = AsyncMock()
    return msg


@pytest.fixture
def mock_bot_user() -> MagicMock:
    """Mock Discord bot user."""
    user = MagicMock(spec=discord.ClientUser)
    user.id = 987654321
    user.display_name = "OnyxBot"
    user.bot = True
    return user


@pytest.fixture
def mock_discord_bot(
    mock_cache_manager: MagicMock,
    mock_api_client: MagicMock,
    mock_bot_user: MagicMock,
) -> MagicMock:
    """Mock OnyxDiscordClient."""
    bot = MagicMock()
    bot.user = mock_bot_user
    bot.cache = mock_cache_manager
    bot.api_client = mock_api_client
    bot.ready = True
    bot.loop = MagicMock()
    bot.is_closed.return_value = False
    bot.guilds = []
    return bot
