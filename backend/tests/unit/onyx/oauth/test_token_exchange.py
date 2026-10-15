from unittest.mock import Mock

import pytest

from onyx.auth import oauth_token_manager
from onyx.oauth.protocol import OAuthFlowParams


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"error": "invalid_grant"},
        {"access_token": ""},
        {"access_token": "token", "expires_in": True},
        {"access_token": "token", "expires_in": "3600"},
        {"access_token": "token", "expires_in": float("inf")},
        {"access_token": "token", "expires_in": -1},
    ],
)
def test_exchange_rejects_invalid_token_payload(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    monkeypatch.setattr(oauth_token_manager, "validate_oauth_endpoint_url", Mock())
    response = Mock()
    response.json.return_value = payload
    monkeypatch.setattr(
        oauth_token_manager.requests, "post", Mock(return_value=response)
    )
    with pytest.raises(ValueError, match="OAuth token response"):
        oauth_token_manager.exchange_oauth_code_for_token(
            OAuthFlowParams(
                authorization_url="https://provider.example/auth",
                token_url="https://provider.example/token",
                client_id="client",
            ),
            "code",
            "https://onyx.example/callback",
        )
