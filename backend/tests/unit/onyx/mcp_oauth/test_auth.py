from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.requests import Request

from onyx.auth.schemas import AuthBackend
from onyx.configs import app_configs
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.server.mcp_oauth import protocol as oauth_protocol
from onyx.server.mcp_oauth.api import _session_hash
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType


def test_consent_binding_tracks_bearer_even_with_an_unrelated_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_configs, "AUTH_BACKEND", AuthBackend.REDIS)
    user = User(id=uuid4(), account_type=AccountType.STANDARD)
    fingerprints = []
    for token in ("first-session", "second-session"):
        request = Request(
            {
                "type": "http",
                "headers": [
                    (b"cookie", f"{FASTAPI_USERS_AUTH_COOKIE_NAME}=unrelated".encode()),
                    (b"authorization", f"Bearer {token}".encode()),
                ],
                "state": {
                    "usage_credential": UsageCredentialIdentity(
                        UsageCredentialType.SESSION
                    )
                },
            }
        )
        fingerprints.append(_session_hash(request, user))
    assert fingerprints[0] != fingerprints[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("forwarded", "addresses"),
    [
        (
            ("1.1.1.1, 8.8.8.8, 10.0.0.8", "1.1.1.1, 9.9.9.9, 10.0.0.8"),
            ("8.8.8.8", "9.9.9.9"),
        ),
        (("10.1.2.3", "10.1.2.4"), ("10.1.2.3", "10.1.2.4")),
    ],
)
async def test_oauth_rate_limit_uses_forwarded_client_address(
    monkeypatch: pytest.MonkeyPatch,
    forwarded: tuple[str, str],
    addresses: tuple[str, str],
) -> None:
    limiter = AsyncMock(return_value=True)
    monkeypatch.setattr(oauth_protocol, "allow_mcp_oauth_request", limiter)
    for chain in forwarded:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp-oauth/register",
                "client": ("10.0.0.9", 1234),
                "headers": [
                    (
                        b"x-forwarded-for",
                        chain.encode("ascii"),
                    )
                ],
            }
        )
        assert await oauth_protocol._rate_limit(request, "register") is None
    buckets = [call.args[0] for call in limiter.await_args_list]
    assert buckets == [
        f"register:ip:{addresses[0]}",
        "register:global",
        f"register:ip:{addresses[1]}",
        "register:global",
    ]
