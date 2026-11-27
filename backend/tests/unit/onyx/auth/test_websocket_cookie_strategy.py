from unittest.mock import MagicMock

import pytest

from onyx.auth import users


def test_an_unknown_auth_backend_is_an_error_for_the_websocket_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As for HTTP requests: a websocket does not sign in with JWT for a
    backend that it does not know."""
    monkeypatch.setattr(users, "AUTH_BACKEND", "unknown")
    with pytest.raises(ValueError, match="Invalid auth backend"):
        users._cookie_strategy(MagicMock())
