from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import Response
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.documents import connector


@pytest.mark.parametrize(
    "endpoint, cookie_name",
    [
        (connector.gmail_auth, "gmail_credential_id"),
        (connector.google_drive_auth, "google_drive_credential_id"),
    ],
)
@pytest.mark.parametrize(
    "web_domain, expect_secure",
    [("https://onyx.example", True), ("http://localhost:3000", False)],
)
def test_google_oauth_credential_cookie_flags(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: Any,
    cookie_name: str,
    web_domain: str,
    expect_secure: bool,
) -> None:
    monkeypatch.setattr(connector, "WEB_DOMAIN", web_domain)
    monkeypatch.setattr(
        connector,
        "get_auth_url",
        lambda *_args, **_kwargs: "https://accounts.google.com/x",
    )
    response = Response()

    endpoint(
        response=response,
        credential_id="7",
        user=MagicMock(spec=User),
        db_session=MagicMock(spec=Session),
    )

    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{cookie_name}=7;")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert ("Secure" in set_cookie) is expect_secure
