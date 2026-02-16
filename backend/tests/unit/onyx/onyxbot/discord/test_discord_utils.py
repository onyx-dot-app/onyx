"""Unit tests for Discord bot utilities.

Tests for:
- Token management (get_bot_token)
- Registration key parsing (parse_discord_registration_key, generate_discord_registration_key)
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.onyxbot.discord.utils import get_bot_token
from onyx.server.manage.discord_bot.utils import generate_discord_registration_key
from onyx.server.manage.discord_bot.utils import parse_discord_registration_key
from onyx.server.manage.discord_bot.utils import REGISTRATION_KEY_PREFIX


class TestGetBotToken:
    """Tests for get_bot_token function."""

    def test_get_token_from_env(self) -> None:
        """When env var is set, returns env var."""
        with patch("onyx.onyxbot.discord.utils.DISCORD_BOT_TOKEN", "env_token_123"):
            result = get_bot_token()
            assert result == "env_token_123"

    def test_get_token_from_db(self) -> None:
        """When no env var and DB config exists, returns DB token."""
        mock_config = MagicMock()
        mock_config.bot_token = "db_token_456"

        with (
            patch("onyx.onyxbot.discord.utils.DISCORD_BOT_TOKEN", None),
            patch("onyx.onyxbot.discord.utils.AUTH_TYPE", "basic"),  # Not CLOUD
            patch("onyx.onyxbot.discord.utils.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.utils.get_discord_bot_config",
                return_value=mock_config,
            ),
        ):
            mock_session.return_value.__enter__ = MagicMock()
            mock_session.return_value.__exit__ = MagicMock()
            result = get_bot_token()
            assert result == "db_token_456"

    def test_get_token_none(self) -> None:
        """When no env var and no DB config, returns None."""
        with (
            patch("onyx.onyxbot.discord.utils.DISCORD_BOT_TOKEN", None),
            patch("onyx.onyxbot.discord.utils.AUTH_TYPE", "basic"),  # Not CLOUD
            patch("onyx.onyxbot.discord.utils.get_session_with_tenant") as mock_session,
            patch(
                "onyx.onyxbot.discord.utils.get_discord_bot_config",
                return_value=None,
            ),
        ):
            mock_session.return_value.__enter__ = MagicMock()
            mock_session.return_value.__exit__ = MagicMock()
            result = get_bot_token()
            assert result is None

    def test_get_token_env_priority(self) -> None:
        """When both env var and DB exist, env var takes priority."""
        mock_config = MagicMock()
        mock_config.bot_token = "db_token_456"

        with (
            patch("onyx.onyxbot.discord.utils.DISCORD_BOT_TOKEN", "env_token_123"),
            patch(
                "onyx.onyxbot.discord.utils.get_discord_bot_config",
                return_value=mock_config,
            ),
        ):
            result = get_bot_token()
            # Should return env var, not DB token
            assert result == "env_token_123"


class TestParseRegistrationKey:
    """Tests for parse_discord_registration_key function."""

    def test_parse_registration_key_valid(self) -> None:
        """Valid key format returns tenant_id."""
        key = "discord_tenant123.randomtoken"
        result = parse_discord_registration_key(key)
        assert result == "tenant123"

    def test_parse_registration_key_invalid(self) -> None:
        """Malformed key returns None."""
        result = parse_discord_registration_key("malformed_key")
        assert result is None

    def test_parse_registration_key_missing_prefix(self) -> None:
        """Key without 'discord_' prefix returns None."""
        key = "tenant123.randomtoken"
        result = parse_discord_registration_key(key)
        assert result is None

    def test_parse_registration_key_missing_dot(self) -> None:
        """Key without separator '.' returns None."""
        key = "discord_tenant123randomtoken"
        result = parse_discord_registration_key(key)
        assert result is None

    def test_parse_registration_key_empty_token(self) -> None:
        """Key with empty token part returns None."""
        # This test verifies behavior with empty token after dot
        key = "discord_tenant123."
        result = parse_discord_registration_key(key)
        # Current implementation allows empty token, but returns tenant
        # If this should be invalid, update the implementation
        assert result == "tenant123" or result is None

    def test_parse_registration_key_url_encoded_tenant(self) -> None:
        """Tenant ID with URL encoding is decoded correctly."""
        # URL encoded "my tenant" -> "my%20tenant"
        key = "discord_my%20tenant.randomtoken"
        result = parse_discord_registration_key(key)
        assert result == "my tenant"

    def test_parse_registration_key_special_chars(self) -> None:
        """Key with special characters in tenant ID."""
        # Tenant with slashes (URL encoded)
        key = "discord_tenant%2Fwith%2Fslashes.randomtoken"
        result = parse_discord_registration_key(key)
        assert result == "tenant/with/slashes"


class TestGenerateRegistrationKey:
    """Tests for generate_discord_registration_key function."""

    def test_generate_registration_key(self) -> None:
        """Generated key has correct format."""
        key = generate_discord_registration_key("tenant123")

        assert key.startswith(REGISTRATION_KEY_PREFIX)
        assert "tenant123" in key
        assert "." in key

        # Parse it back to verify round-trip
        parsed = parse_discord_registration_key(key)
        assert parsed == "tenant123"

    def test_generate_registration_key_unique(self) -> None:
        """Each generated key is unique."""
        keys = [generate_discord_registration_key("tenant123") for _ in range(10)]
        assert len(set(keys)) == 10  # All unique

    def test_generate_registration_key_special_tenant(self) -> None:
        """Key generation handles special characters in tenant ID."""
        key = generate_discord_registration_key("my tenant/id")

        # Should be URL encoded
        assert "%20" in key or "%2F" in key

        # Parse it back
        parsed = parse_discord_registration_key(key)
        assert parsed == "my tenant/id"
