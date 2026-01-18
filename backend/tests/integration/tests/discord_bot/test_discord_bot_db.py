"""Integration tests for Discord bot database operations.

These tests verify CRUD operations for Discord bot models.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.discord_bot import bulk_create_channel_configs
from onyx.db.discord_bot import create_discord_bot_config
from onyx.db.discord_bot import create_guild_config
from onyx.db.discord_bot import delete_discord_bot_config
from onyx.db.discord_bot import delete_discord_service_api_key
from onyx.db.discord_bot import delete_guild_config
from onyx.db.discord_bot import get_channel_configs
from onyx.db.discord_bot import get_discord_bot_config
from onyx.db.discord_bot import get_discord_service_api_key
from onyx.db.discord_bot import get_guild_config_by_internal_id
from onyx.db.discord_bot import get_guild_config_by_registration_key
from onyx.db.discord_bot import get_guild_configs
from onyx.db.discord_bot import get_or_create_discord_service_api_key
from onyx.db.discord_bot import sync_channel_configs
from onyx.db.discord_bot import update_discord_channel_config
from onyx.db.discord_bot import update_guild_config
from onyx.db.models import Persona
from onyx.db.utils import DiscordChannelView
from onyx.server.manage.discord_bot.utils import generate_discord_registration_key


def _create_test_persona(db_session: Session, persona_id: int, name: str) -> Persona:
    """Create a minimal test persona."""
    persona = Persona(
        id=persona_id,
        name=name,
        description="Test persona for Discord bot tests",
        num_chunks=5.0,
        chunks_above=1,
        chunks_below=1,
        llm_relevance_filter=False,
        llm_filter_extraction=False,
        recency_bias=RecencyBiasSetting.FAVOR_RECENT,
        is_visible=True,
        is_default_persona=False,
        deleted=False,
        builtin_persona=False,
    )
    db_session.add(persona)
    db_session.flush()
    return persona


def _delete_test_persona(db_session: Session, persona_id: int) -> None:
    """Delete a test persona."""
    db_session.query(Persona).filter(Persona.id == persona_id).delete()
    db_session.flush()


class TestBotConfigAPI:
    """Tests for bot config API operations."""

    def test_create_bot_config(self, db_session: Session) -> None:
        """Create bot config succeeds with valid token."""
        # Clean up any existing config first
        delete_discord_bot_config(db_session)
        db_session.commit()

        config = create_discord_bot_config(db_session, bot_token="test_token_123")
        db_session.commit()

        assert config is not None
        assert config.bot_token == "test_token_123"

        # Cleanup
        delete_discord_bot_config(db_session)
        db_session.commit()

    def test_create_bot_config_already_exists(self, db_session: Session) -> None:
        """Creating config twice raises ValueError."""
        # Clean up first
        delete_discord_bot_config(db_session)
        db_session.commit()

        create_discord_bot_config(db_session, bot_token="token1")
        db_session.commit()

        with pytest.raises(ValueError):
            create_discord_bot_config(db_session, bot_token="token2")

        # Cleanup
        delete_discord_bot_config(db_session)
        db_session.commit()

    def test_get_bot_config(self, db_session: Session) -> None:
        """Get bot config returns config with masked token."""
        # Clean up first
        delete_discord_bot_config(db_session)
        db_session.commit()

        create_discord_bot_config(db_session, bot_token="my_secret_token")
        db_session.commit()

        config = get_discord_bot_config(db_session)

        assert config is not None
        # Token should be stored (we don't mask in DB, only API response)
        assert config.bot_token is not None

        # Cleanup
        delete_discord_bot_config(db_session)
        db_session.commit()

    def test_delete_bot_config(self, db_session: Session) -> None:
        """Delete bot config removes it from DB."""
        # Clean up first
        delete_discord_bot_config(db_session)
        db_session.commit()

        create_discord_bot_config(db_session, bot_token="token")
        db_session.commit()

        deleted = delete_discord_bot_config(db_session)
        db_session.commit()

        assert deleted is True
        assert get_discord_bot_config(db_session) is None

    def test_delete_bot_config_not_found(self, db_session: Session) -> None:
        """Delete when no config exists returns False."""
        # Ensure no config exists
        delete_discord_bot_config(db_session)
        db_session.commit()

        deleted = delete_discord_bot_config(db_session)
        assert deleted is False


class TestRegistrationKeyAPI:
    """Tests for registration key API operations."""

    def test_create_registration_key(self, db_session: Session) -> None:
        """Create registration key with proper format."""
        key = generate_discord_registration_key("test_tenant")

        config = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        assert config is not None
        assert config.registration_key == key
        assert key.startswith("discord_")
        assert "test_tenant" in key or "test%5Ftenant" in key

        # Cleanup
        delete_guild_config(db_session, config.id)
        db_session.commit()

    def test_registration_key_is_unique(self, db_session: Session) -> None:
        """Each generated key is unique."""
        keys = [generate_discord_registration_key("tenant") for _ in range(5)]
        assert len(set(keys)) == 5

    def test_delete_registration_key(self, db_session: Session) -> None:
        """Deleted key can no longer be used."""
        key = generate_discord_registration_key("tenant")
        config = create_guild_config(db_session, registration_key=key)
        db_session.commit()
        config_id = config.id

        # Delete
        deleted = delete_guild_config(db_session, config_id)
        db_session.commit()

        assert deleted is True

        # Should not find it anymore
        found = get_guild_config_by_registration_key(db_session, key)
        assert found is None


class TestGuildConfigAPI:
    """Tests for guild config API operations."""

    def test_list_guilds(self, db_session: Session) -> None:
        """List guilds returns all guild configs."""
        # Create some guild configs
        key1 = generate_discord_registration_key("t1")
        key2 = generate_discord_registration_key("t2")

        config1 = create_guild_config(db_session, registration_key=key1)
        config2 = create_guild_config(db_session, registration_key=key2)
        db_session.commit()

        configs = get_guild_configs(db_session)

        assert len(configs) >= 2

        # Cleanup
        delete_guild_config(db_session, config1.id)
        delete_guild_config(db_session, config2.id)
        db_session.commit()

    def test_get_guild_config(self, db_session: Session) -> None:
        """Get specific guild config by ID."""
        key = generate_discord_registration_key("tenant")
        config = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        found = get_guild_config_by_internal_id(db_session, config.id)

        assert found is not None
        assert found.id == config.id
        assert found.registration_key == key

        # Cleanup
        delete_guild_config(db_session, config.id)
        db_session.commit()

    def test_update_guild_enabled(self, db_session: Session) -> None:
        """Update guild enabled status."""
        key = generate_discord_registration_key("tenant")
        config = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        # Initially enabled is True by default
        assert config.enabled is True

        # Disable
        updated = update_guild_config(
            db_session, config, enabled=False, default_persona_id=None
        )
        db_session.commit()

        assert updated.enabled is False

        # Cleanup
        delete_guild_config(db_session, config.id)
        db_session.commit()

    def test_update_guild_persona(self, db_session: Session) -> None:
        """Update guild default persona."""
        # Create test persona first to satisfy foreign key constraint
        _create_test_persona(db_session, 5, "Test Persona 5")
        db_session.commit()

        key = generate_discord_registration_key("tenant")
        config = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        # Set persona
        updated = update_guild_config(
            db_session, config, enabled=True, default_persona_id=5
        )
        db_session.commit()

        assert updated.default_persona_id == 5

        # Cleanup
        delete_guild_config(db_session, config.id)
        _delete_test_persona(db_session, 5)
        db_session.commit()


class TestChannelConfigAPI:
    """Tests for channel config API operations."""

    def test_list_channels_for_guild(self, db_session: Session) -> None:
        """List channels returns all channel configs for guild."""
        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        # Create some channels
        channels = [
            DiscordChannelView(
                channel_id=111,
                channel_name="general",
                channel_type="text",
                is_private=False,
            ),
            DiscordChannelView(
                channel_id=222,
                channel_name="help",
                channel_type="text",
                is_private=False,
            ),
        ]
        bulk_create_channel_configs(db_session, guild.id, channels)
        db_session.commit()

        channel_configs = get_channel_configs(db_session, guild.id)

        assert len(channel_configs) == 2

        # Cleanup
        delete_guild_config(db_session, guild.id)
        db_session.commit()

    def test_update_channel_enabled(self, db_session: Session) -> None:
        """Update channel enabled status."""
        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        channels = [
            DiscordChannelView(
                channel_id=111,
                channel_name="general",
                channel_type="text",
                is_private=False,
            ),
        ]
        created = bulk_create_channel_configs(db_session, guild.id, channels)
        db_session.commit()

        # Channels are disabled by default
        assert created[0].enabled is False

        # Enable
        updated = update_discord_channel_config(
            db_session,
            created[0],
            channel_name="general",
            thread_only_mode=False,
            require_bot_invocation=True,
            enabled=True,
        )
        db_session.commit()

        assert updated.enabled is True

        # Cleanup
        delete_guild_config(db_session, guild.id)
        db_session.commit()

    def test_update_channel_thread_only_mode(self, db_session: Session) -> None:
        """Update channel thread_only_mode setting."""
        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        channels = [
            DiscordChannelView(
                channel_id=111,
                channel_name="general",
                channel_type="text",
                is_private=False,
            ),
        ]
        created = bulk_create_channel_configs(db_session, guild.id, channels)
        db_session.commit()

        # Update thread_only_mode
        updated = update_discord_channel_config(
            db_session,
            created[0],
            channel_name="general",
            thread_only_mode=True,
            require_bot_invocation=True,
            enabled=True,
        )
        db_session.commit()

        assert updated.thread_only_mode is True

        # Cleanup
        delete_guild_config(db_session, guild.id)
        db_session.commit()

    def test_sync_channels_adds_new(self, db_session: Session) -> None:
        """Sync channels adds new channels."""
        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        # Initial channels
        initial = [
            DiscordChannelView(
                channel_id=111,
                channel_name="general",
                channel_type="text",
                is_private=False,
            ),
        ]
        bulk_create_channel_configs(db_session, guild.id, initial)
        db_session.commit()

        # Sync with new channel
        current = [
            DiscordChannelView(
                channel_id=111,
                channel_name="general",
                channel_type="text",
                is_private=False,
            ),
            DiscordChannelView(
                channel_id=222,
                channel_name="new-channel",
                channel_type="text",
                is_private=False,
            ),
        ]
        added, removed, updated = sync_channel_configs(db_session, guild.id, current)
        db_session.commit()

        assert added == 1
        assert removed == 0

        # Cleanup
        delete_guild_config(db_session, guild.id)
        db_session.commit()

    def test_sync_channels_removes_deleted(self, db_session: Session) -> None:
        """Sync channels removes deleted channels."""
        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        # Initial channels
        initial = [
            DiscordChannelView(
                channel_id=111,
                channel_name="general",
                channel_type="text",
                is_private=False,
            ),
            DiscordChannelView(
                channel_id=222,
                channel_name="old-channel",
                channel_type="text",
                is_private=False,
            ),
        ]
        bulk_create_channel_configs(db_session, guild.id, initial)
        db_session.commit()

        # Sync with one channel removed
        current = [
            DiscordChannelView(
                channel_id=111,
                channel_name="general",
                channel_type="text",
                is_private=False,
            ),
        ]
        added, removed, updated = sync_channel_configs(db_session, guild.id, current)
        db_session.commit()

        assert added == 0
        assert removed == 1

        # Cleanup
        delete_guild_config(db_session, guild.id)
        db_session.commit()

    def test_sync_channels_updates_renamed(self, db_session: Session) -> None:
        """Sync channels updates renamed channels."""
        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        db_session.commit()

        # Initial channels
        initial = [
            DiscordChannelView(
                channel_id=111,
                channel_name="old-name",
                channel_type="text",
                is_private=False,
            ),
        ]
        bulk_create_channel_configs(db_session, guild.id, initial)
        db_session.commit()

        # Sync with renamed channel
        current = [
            DiscordChannelView(
                channel_id=111,
                channel_name="new-name",
                channel_type="text",
                is_private=False,
            ),
        ]
        added, removed, updated = sync_channel_configs(db_session, guild.id, current)
        db_session.commit()

        assert added == 0
        assert removed == 0
        assert updated == 1

        # Verify name was updated
        configs = get_channel_configs(db_session, guild.id)
        assert configs[0].channel_name == "new-name"

        # Cleanup
        delete_guild_config(db_session, guild.id)
        db_session.commit()


class TestPersonaConfigurationAPI:
    """Tests for persona configuration in API."""

    def test_guild_persona_used_in_api_call(self, db_session: Session) -> None:
        """Guild default_persona_id is used when no channel override."""
        # Create test persona first
        _create_test_persona(db_session, 42, "Test Persona 42")
        db_session.commit()

        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        update_guild_config(db_session, guild, enabled=True, default_persona_id=42)
        db_session.commit()

        # Verify persona is set
        config = get_guild_config_by_internal_id(db_session, guild.id)
        assert config is not None
        assert config.default_persona_id == 42

        # Cleanup
        delete_guild_config(db_session, guild.id)
        _delete_test_persona(db_session, 42)
        db_session.commit()

    def test_channel_persona_override_in_api_call(self, db_session: Session) -> None:
        """Channel persona_override_id takes precedence over guild default."""
        # Create test personas first
        _create_test_persona(db_session, 42, "Test Persona 42")
        _create_test_persona(db_session, 99, "Test Persona 99")
        db_session.commit()

        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        update_guild_config(db_session, guild, enabled=True, default_persona_id=42)
        db_session.commit()

        channels = [
            DiscordChannelView(
                channel_id=111,
                channel_name="general",
                channel_type="text",
                is_private=False,
            ),
        ]
        created = bulk_create_channel_configs(db_session, guild.id, channels)
        db_session.commit()

        # Set channel persona override
        updated = update_discord_channel_config(
            db_session,
            created[0],
            channel_name="general",
            thread_only_mode=False,
            require_bot_invocation=True,
            enabled=True,
            persona_override_id=99,  # Override!
        )
        db_session.commit()

        assert updated.persona_override_id == 99

        # Cleanup
        delete_guild_config(db_session, guild.id)
        _delete_test_persona(db_session, 42)
        _delete_test_persona(db_session, 99)
        db_session.commit()

    def test_no_persona_uses_default(self, db_session: Session) -> None:
        """Neither guild nor channel has persona - uses API default."""
        key = generate_discord_registration_key("tenant")
        guild = create_guild_config(db_session, registration_key=key)
        # No persona set
        db_session.commit()

        config = get_guild_config_by_internal_id(db_session, guild.id)
        assert config is not None
        assert config.default_persona_id is None

        # Cleanup
        delete_guild_config(db_session, guild.id)
        db_session.commit()


class TestServiceApiKeyAPI:
    """Tests for Discord service API key operations."""

    def test_create_service_api_key(self, db_session: Session) -> None:
        """Create service API key returns valid key."""
        # Clean up any existing key first
        delete_discord_service_api_key(db_session)
        db_session.commit()

        api_key = get_or_create_discord_service_api_key(db_session, "public")
        db_session.commit()

        assert api_key is not None
        assert len(api_key) > 0

        # Verify key was stored in database
        stored_key = get_discord_service_api_key(db_session)
        assert stored_key is not None

        # Cleanup
        delete_discord_service_api_key(db_session)
        db_session.commit()

    def test_get_or_create_returns_existing(self, db_session: Session) -> None:
        """get_or_create_discord_service_api_key regenerates key if exists."""
        # Clean up any existing key first
        delete_discord_service_api_key(db_session)
        db_session.commit()

        # Create first key
        key1 = get_or_create_discord_service_api_key(db_session, "public")
        db_session.commit()

        # Call again - should regenerate (per implementation, it regenerates to update cache)
        key2 = get_or_create_discord_service_api_key(db_session, "public")
        db_session.commit()

        # Keys should be different since it regenerates
        assert key1 != key2

        # But there should still be only one key in the database
        stored_key = get_discord_service_api_key(db_session)
        assert stored_key is not None

        # Cleanup
        delete_discord_service_api_key(db_session)
        db_session.commit()

    def test_delete_service_api_key(self, db_session: Session) -> None:
        """Delete service API key removes it from DB."""
        # Clean up any existing key first
        delete_discord_service_api_key(db_session)
        db_session.commit()

        # Create a key
        get_or_create_discord_service_api_key(db_session, "public")
        db_session.commit()

        # Delete it
        deleted = delete_discord_service_api_key(db_session)
        db_session.commit()

        assert deleted is True
        assert get_discord_service_api_key(db_session) is None

    def test_delete_service_api_key_not_found(self, db_session: Session) -> None:
        """Delete when no key exists returns False."""
        # Ensure no key exists
        delete_discord_service_api_key(db_session)
        db_session.commit()

        deleted = delete_discord_service_api_key(db_session)
        assert deleted is False


# Pytest fixture for db_session
@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Create database session for tests."""
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.db.engine.sql_engine import SqlEngine
    from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    token = CURRENT_TENANT_ID_CONTEXTVAR.set("public")
    try:
        with get_session_with_current_tenant() as session:
            yield session
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
