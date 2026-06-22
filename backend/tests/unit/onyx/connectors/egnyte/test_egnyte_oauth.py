"""Unit tests for EgnyteConnector OAuth availability gating."""

from __future__ import annotations

from unittest.mock import patch

from onyx.connectors.egnyte.connector import EgnyteConnector


@patch("onyx.connectors.egnyte.connector.EGNYTE_CLIENT_SECRET", "secret")
@patch("onyx.connectors.egnyte.connector.EGNYTE_CLIENT_ID", "client-id")
def test_oauth_enabled_when_client_credentials_configured() -> None:
    """OAuth is available only when both client id and secret are set."""
    assert EgnyteConnector.oauth_enabled() is True


@patch("onyx.connectors.egnyte.connector.EGNYTE_CLIENT_SECRET", None)
@patch("onyx.connectors.egnyte.connector.EGNYTE_CLIENT_ID", None)
def test_oauth_disabled_when_client_credentials_missing() -> None:
    """Without client creds, OAuth is disabled so the UI uses manual entry."""
    assert EgnyteConnector.oauth_enabled() is False


@patch("onyx.connectors.egnyte.connector.EGNYTE_CLIENT_SECRET", None)
@patch("onyx.connectors.egnyte.connector.EGNYTE_CLIENT_ID", "client-id")
def test_oauth_disabled_when_secret_missing() -> None:
    """Both client id and secret are required for OAuth."""
    assert EgnyteConnector.oauth_enabled() is False
