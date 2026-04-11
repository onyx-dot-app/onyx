from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from discord.errors import LoginFailure

from onyx.connectors.discord.connector import DiscordConnector
from onyx.connectors.exceptions import CredentialInvalidError


def _build_connector(token: str = "fake-bot-token") -> DiscordConnector:
    connector = DiscordConnector()
    connector.load_credentials({"discord_bot_token": token})
    return connector


@patch("onyx.connectors.discord.connector.Client.close", new_callable=AsyncMock)
@patch("onyx.connectors.discord.connector.Client.login", new_callable=AsyncMock)
def test_validate_success(
    mock_login: AsyncMock,
    mock_close: AsyncMock,
) -> None:
    connector = _build_connector()
    connector.validate_connector_settings()

    mock_login.assert_awaited_once_with("fake-bot-token")
    mock_close.assert_awaited_once()


@patch("onyx.connectors.discord.connector.Client.close", new_callable=AsyncMock)
@patch(
    "onyx.connectors.discord.connector.Client.login",
    new_callable=AsyncMock,
    side_effect=LoginFailure("Improper token has been passed."),
)
def test_validate_invalid_token(
    mock_login: AsyncMock,  # noqa: ARG001
    mock_close: AsyncMock,
) -> None:
    connector = _build_connector(token="bad-token")

    with pytest.raises(CredentialInvalidError, match="Invalid Discord bot token"):
        connector.validate_connector_settings()

    mock_close.assert_awaited_once()
