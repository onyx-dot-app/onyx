"""Discord bot behavior that differs between cloud and self-hosted mode.

Both checks read the MULTI_TENANT flag at call time from the module that uses it,
so the flag is patched here rather than driven from the environment.
"""

from unittest.mock import patch

import pytest


def test_cannot_create_bot_config_in_cloud_mode() -> None:
    """Bot config creation is blocked in cloud mode."""
    with patch("onyx.server.manage.discord_bot.api.MULTI_TENANT", True):
        from onyx.error_handling.exceptions import OnyxError
        from onyx.server.manage.discord_bot.api import _check_bot_config_api_access

        with pytest.raises(OnyxError) as exc_info:
            _check_bot_config_api_access()

        assert exc_info.value.status_code == 403
        assert "Cloud" in str(exc_info.value.detail)


def test_bot_token_from_env_only_in_cloud() -> None:
    """Bot token comes from env var in cloud mode, ignores DB."""
    from onyx.onyxbot.discord.utils import get_bot_token

    with (
        patch("onyx.onyxbot.discord.utils.DISCORD_BOT_TOKEN", "env_token"),
        patch("onyx.onyxbot.discord.utils.MULTI_TENANT", True),
    ):
        result = get_bot_token()

    assert result == "env_token"
