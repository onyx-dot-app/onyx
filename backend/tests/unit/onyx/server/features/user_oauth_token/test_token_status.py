from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.auth import oauth_token_manager
from onyx.db.models import OAuthConfig, OAuthUserToken, User
from onyx.server.features.user_oauth_token import api
from onyx.utils.sensitive import make_mock_sensitive_value


@pytest.mark.parametrize(
    ("expires_at", "refresh_token", "client_id", "client_secret", "can_refresh"),
    [
        (1, "refresh-token", "client-id", "client-secret", True),
        (1, None, "client-id", "client-secret", False),
        (1, "", "client-id", "client-secret", False),
        (1, "refresh-token", None, "client-secret", False),
        (1, "refresh-token", "client-id", None, False),
        (1, "refresh-token", "", "client-secret", False),
        (1, "refresh-token", "client-id", "", False),
        (99999999999, "refresh-token", "client-id", "client-secret", True),
    ],
)
def test_token_status_reports_saved_refresh_capability_without_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
    expires_at: int,
    refresh_token: str | None,
    client_id: str | None,
    client_secret: str | None,
    can_refresh: bool,
) -> None:
    config = OAuthConfig(id=17)
    config.client_id = (
        make_mock_sensitive_value(client_id) if client_id is not None else None
    )
    config.client_secret = (
        make_mock_sensitive_value(client_secret) if client_secret is not None else None
    )
    token_data: dict[str, Any] = {
        "access_token": "access-token",
        "expires_at": expires_at,
    }
    if refresh_token is not None:
        token_data["refresh_token"] = refresh_token
    token = OAuthUserToken(oauth_config_id=17, oauth_config=config)
    token.token_data = make_mock_sensitive_value(token_data)
    user = User(id=uuid4())
    db = MagicMock(spec=Session)
    read_tokens = MagicMock(return_value=[token])
    monkeypatch.setattr(api, "get_all_user_oauth_tokens", read_tokens)
    refresh = MagicMock(side_effect=AssertionError("Status must not refresh tokens"))
    monkeypatch.setattr(oauth_token_manager.requests, "post", refresh)

    result = api.get_user_oauth_token_status(db, user)

    assert [status.model_dump() for status in result] == [
        {
            "oauth_config_id": 17,
            "expires_at": expires_at,
            "is_expired": expires_at == 1,
            "can_refresh": can_refresh,
        }
    ]
    read_tokens.assert_called_once_with(user.id, db)
    refresh.assert_not_called()
    db.commit.assert_not_called()


def test_token_status_does_not_invent_missing_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "get_all_user_oauth_tokens", lambda *_: [])

    assert (
        api.get_user_oauth_token_status(MagicMock(spec=Session), User(id=uuid4())) == []
    )
