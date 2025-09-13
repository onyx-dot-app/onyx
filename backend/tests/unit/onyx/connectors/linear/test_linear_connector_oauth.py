import pytest
from pytest_mock import MockerFixture

from onyx.connectors.linear.connector import LinearConnector


def test_oauth_authorization_url_uses_injected_client_id() -> None:
    # Missing client_id should fail
    with pytest.raises(ValueError, match="Linear client_id is not configured"):
        LinearConnector.oauth_authorization_url(
            "https://app.example.com", "test_state", {}
        )

    # With injected client_id
    url = LinearConnector.oauth_authorization_url(
        "https://app.example.com", "test_state", {"client_id": "CID123"}
    )

    assert "client_id=CID123" in url
    assert "linear.app/oauth/authorize" in url
    assert "redirect_uri=" in url
    assert "state=test_state" in url
    assert "scope=read" in url


def test_oauth_code_to_token_uses_injected_secrets(mocker: MockerFixture) -> None:
    # Mock successful token response
    fake_response = mocker.Mock()
    fake_response.ok = True
    fake_response.json.return_value = {"access_token": "ATOKEN123"}

    mocker.patch(
        "onyx.connectors.linear.connector.request_with_retries",
        return_value=fake_response,
    )

    # Missing client_secret should fail
    with pytest.raises(
        ValueError, match="Linear client_id/client_secret is not configured"
    ):
        LinearConnector.oauth_code_to_token(
            "https://app.example.com", "auth_code", {"client_id": "CID123"}
        )

    # With both injected
    token_data = LinearConnector.oauth_code_to_token(
        "https://app.example.com",
        "auth_code",
        {"client_id": "CID123", "client_secret": "SECRET456"},
    )

    assert token_data["linear_access_token"] == "ATOKEN123"


def test_oauth_authorization_url_preserves_other_params() -> None:
    url = LinearConnector.oauth_authorization_url(
        "https://app.example.com",
        "test_state",
        {"client_id": "CID123", "other_param": "value"},
    )

    # Should still work even with extra params
    assert "client_id=CID123" in url
    assert "prompt=consent" in url
