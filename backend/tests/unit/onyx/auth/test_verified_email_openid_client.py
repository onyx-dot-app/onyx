"""The hardened OpenID client must reject unverified email claims (absent
email_verified counts as unverified) and refuse discovery documents whose
issuer does not own the configured endpoint."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx_oauth.exceptions import GetIdEmailError

from onyx.auth.oidc_client import (
    OpenIDConfigurationIssuerMismatch,
    validate_issuer_owns_config_url,
    VerifiedEmailOpenID,
)

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


def _build_client(
    discovery: dict[str, Any], config_url: str = _CONFIG_URL
) -> VerifiedEmailOpenID:
    discovery_response = MagicMock()
    discovery_response.json.return_value = discovery
    http_client = MagicMock()
    http_client.__enter__ = MagicMock(return_value=http_client)
    http_client.__exit__ = MagicMock(return_value=None)
    http_client.get.return_value = discovery_response
    with patch("httpx_oauth.clients.openid.httpx.Client", return_value=http_client):
        return VerifiedEmailOpenID("cid", "csecret", config_url)


class _FakeResponse:
    def __init__(
        self, payload: Any, status_code: int = 200, json_raises: bool = False
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self._json_raises = json_raises

    def json(self) -> Any:
        if self._json_raises:
            raise ValueError("not valid JSON")
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
    client: VerifiedEmailOpenID,
    payload: Any,
    status_code: int = 200,
    json_raises: bool = False,
) -> None:
    fake = _FakeAsyncClient(_FakeResponse(payload, status_code, json_raises))
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


@pytest.mark.asyncio
async def test_non_string_email_rejected() -> None:
    client = _build_client(_discovery())
    _with_userinfo(client, {"sub": "s1", "email": ["a@b.com"], "email_verified": True})
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")


@pytest.mark.asyncio
async def test_invalid_json_rejected() -> None:
    client = _build_client(_discovery())
    _with_userinfo(client, None, json_raises=True)
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")


@pytest.mark.asyncio
async def test_non_object_body_rejected() -> None:
    client = _build_client(_discovery())
    _with_userinfo(client, ["not", "an", "object"])
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")


@pytest.mark.asyncio
async def test_missing_sub_rejected() -> None:
    client = _build_client(_discovery())
    _with_userinfo(client, {"email": "bob@companyb.com", "email_verified": True})
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")


def test_issuer_mismatch_rejected_at_construction() -> None:
    with pytest.raises(OpenIDConfigurationIssuerMismatch):
        _build_client(_discovery(issuer="https://evil.example.com"))


def test_lookalike_host_prefix_rejected() -> None:
    # discovery reports issuer https://idp.companyb.com, but the configured
    # endpoint is on the look-alike host idp.companyb.com.attacker.com
    lookalike = "https://idp.companyb.com.attacker.com/.well-known/openid-configuration"
    with pytest.raises(OpenIDConfigurationIssuerMismatch):
        _build_client(_discovery(), config_url=lookalike)


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


def test_path_based_issuer_dot_segments_rejected() -> None:
    with pytest.raises(OpenIDConfigurationIssuerMismatch):
        validate_issuer_owns_config_url(
            "https://idp.example.com/oidc",
            "https://idp.example.com/oidc/../../evil/.well-known/openid-configuration",
        )


def test_path_based_issuer_legit_config_accepted() -> None:
    validate_issuer_owns_config_url(
        "https://idp.example.com/oidc",
        "https://idp.example.com/oidc/.well-known/openid-configuration",
    )


def _encode_times(segment: str, times: int) -> str:
    encoded = "".join(f"%{ord(ch):02x}" for ch in segment)
    for _ in range(times - 1):
        encoded = encoded.replace("%", "%25")
    return encoded


def test_encoding_beyond_decode_bound_fails_closed() -> None:
    # 12 levels of encoding exceeds _fully_decoded's bound, so it must NOT
    # silently validate a still-encoded traversal.
    deep = _encode_times("..", 12)
    with pytest.raises(OpenIDConfigurationIssuerMismatch):
        validate_issuer_owns_config_url(
            "https://idp.example.com/oidc",
            f"https://idp.example.com/oidc/{deep}/evil/.well-known/openid-configuration",
        )


@pytest.mark.parametrize(
    "encoded",
    [
        "%2e%2e",  # single-encoded ..
        "%252e%252e",  # double-encoded
        "%25252e%25252e",  # triple-encoded
    ],
)
def test_encoded_dot_segments_rejected(encoded: str) -> None:
    with pytest.raises(OpenIDConfigurationIssuerMismatch):
        validate_issuer_owns_config_url(
            "https://idp.example.com/oidc",
            f"https://idp.example.com/oidc/{encoded}/evil/.well-known/openid-configuration",
        )
