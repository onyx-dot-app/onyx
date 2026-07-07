"""The hardened OpenID client must reject unverified email claims (absent
email_verified counts as unverified) and refuse discovery documents whose
issuer does not own the configured endpoint."""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from httpx_oauth.exceptions import GetIdEmailError

from onyx.auth.sso_clients import OpenIDConfigurationIssuerMismatch
from onyx.auth.sso_clients import validate_issuer_owns_config_url
from onyx.auth.sso_clients import VerifiedEmailOpenID

_ISSUER = "https://idp.companyb.com"
_CONFIG_URL = f"{_ISSUER}/.well-known/openid-configuration"


def _discovery(issuer: str = _ISSUER) -> dict[str, Any]:
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{_ISSUER}/auth",
        "token_endpoint": f"{_ISSUER}/token",
        "userinfo_endpoint": f"{_ISSUER}/userinfo",
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
    }


def _build_client(discovery: dict[str, Any]) -> VerifiedEmailOpenID:
    discovery_response = MagicMock()
    discovery_response.json.return_value = discovery
    http_client = MagicMock()
    http_client.__enter__ = MagicMock(return_value=http_client)
    http_client.__exit__ = MagicMock(return_value=None)
    http_client.get.return_value = discovery_response
    with patch("httpx_oauth.clients.openid.httpx.Client", return_value=http_client):
        return VerifiedEmailOpenID("cid", "csecret", _CONFIG_URL)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def get(self, *_args: Any, **_kwargs: Any) -> _FakeResponse:
        return self._response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _with_userinfo(
    client: VerifiedEmailOpenID, payload: dict[str, Any], status_code: int = 200
) -> None:
    fake = _FakeAsyncClient(_FakeResponse(payload, status_code))
    client.get_httpx_client = MagicMock(  # ty: ignore[invalid-assignment]
        return_value=fake
    )


@pytest.mark.asyncio
async def test_verified_email_is_returned() -> None:
    client = _build_client(_discovery())
    _with_userinfo(
        client, {"sub": "s1", "email": "bob@companyb.com", "email_verified": True}
    )
    assert await client.get_id_email("tok") == ("s1", "bob@companyb.com")


@pytest.mark.asyncio
async def test_explicitly_unverified_email_rejected() -> None:
    client = _build_client(_discovery())
    _with_userinfo(
        client, {"sub": "s1", "email": "bob@companyb.com", "email_verified": False}
    )
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")


@pytest.mark.asyncio
async def test_absent_verified_claim_rejected() -> None:
    client = _build_client(_discovery())
    _with_userinfo(client, {"sub": "s1", "email": "bob@companyb.com"})
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")


@pytest.mark.asyncio
async def test_missing_email_passes_through() -> None:
    client = _build_client(_discovery())
    _with_userinfo(client, {"sub": "machine-1"})
    assert await client.get_id_email("tok") == ("machine-1", None)


@pytest.mark.asyncio
async def test_userinfo_error_status_raises() -> None:
    client = _build_client(_discovery())
    _with_userinfo(client, {}, status_code=401)
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")


def test_issuer_mismatch_rejected_at_construction() -> None:
    with pytest.raises(OpenIDConfigurationIssuerMismatch):
        _build_client(_discovery(issuer="https://evil.example.com"))


def test_missing_issuer_rejected() -> None:
    discovery = _discovery()
    del discovery["issuer"]
    with pytest.raises(OpenIDConfigurationIssuerMismatch):
        _build_client(discovery)


def test_expected_issuer_exposed() -> None:
    client = _build_client(_discovery())
    assert client.expected_issuer == _ISSUER


def test_validate_issuer_allows_trailing_slash_difference() -> None:
    validate_issuer_owns_config_url(f"{_ISSUER}/", _CONFIG_URL)
