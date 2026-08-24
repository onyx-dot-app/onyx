"""Optional aud/iss enforcement on the JWT_PUBLIC_KEY_URL flow. Unset settings
leave the claims unrestricted, and a configured expectation must reject
mismatched or absent claims."""

from typing import Any

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import onyx.auth.jwt as jwt_module
from onyx.auth.jwt import verify_jwt_token

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_PEM = (
    _PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


def _mint(claims: dict[str, Any]) -> str:
    return pyjwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture
def signed_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jwt_module, "get_public_key", lambda _token: _PUBLIC_PEM)


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    audience: str | None,
    issuer: str | None,
) -> None:
    monkeypatch.setattr(jwt_module, "JWT_EXPECTED_AUDIENCE", audience)
    monkeypatch.setattr(jwt_module, "JWT_EXPECTED_ISSUER", issuer)


@pytest.mark.parametrize(
    "claims",
    [
        {"email": "a@b.c"},
        {"email": "a@b.c", "aud": "some-other-service", "iss": "https://idp"},
    ],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("signed_key")
async def test_unset_settings_accept_any_signed_token(
    monkeypatch: pytest.MonkeyPatch, claims: dict[str, Any]
) -> None:
    _configure(monkeypatch, None, None)
    payload = await verify_jwt_token(_mint(claims))
    assert payload is not None
    assert payload["email"] == "a@b.c"


@pytest.mark.parametrize(
    "claims, accepted",
    [
        ({"aud": "onyx"}, True),
        ({"aud": ["onyx", "other"]}, True),
        ({"aud": "some-other-service"}, False),
        ({"aud": ["other-a", "other-b"]}, False),
        ({}, False),
    ],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("signed_key")
async def test_audience_enforced_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    claims: dict[str, Any],
    accepted: bool,
) -> None:
    _configure(monkeypatch, "onyx", None)
    payload = await verify_jwt_token(_mint(claims))
    assert (payload is not None) is accepted


@pytest.mark.parametrize(
    "claims, accepted",
    [
        ({"iss": "https://idp.example.com"}, True),
        ({"iss": "https://evil.example.com"}, False),
        ({}, False),
    ],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("signed_key")
async def test_issuer_enforced_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    claims: dict[str, Any],
    accepted: bool,
) -> None:
    _configure(monkeypatch, None, "https://idp.example.com")
    payload = await verify_jwt_token(_mint(claims))
    assert (payload is not None) is accepted


@pytest.mark.asyncio
@pytest.mark.usefixtures("signed_key")
async def test_both_enforced_and_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, "onyx", "https://idp.example.com")
    payload = await verify_jwt_token(
        _mint({"aud": "onyx", "iss": "https://idp.example.com", "email": "a@b.c"})
    )
    assert payload is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("signed_key")
async def test_both_enforced_rejects_wrong_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, "onyx", "https://idp.example.com")
    payload = await verify_jwt_token(
        _mint({"aud": "onyx", "iss": "https://evil.example.com"})
    )
    assert payload is None


def test_empty_env_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # Compose files pass absent vars through as "", which must not enable
    # enforcement (audience="" would reject every aud-less token).
    import importlib

    import onyx.configs.app_configs as app_configs

    monkeypatch.setenv("JWT_EXPECTED_AUDIENCE", "")
    monkeypatch.setenv("JWT_EXPECTED_ISSUER", "")
    monkeypatch.setenv("JWT_PUBLIC_KEY_URL", "")
    reloaded = importlib.reload(app_configs)
    try:
        assert reloaded.JWT_EXPECTED_AUDIENCE is None
        assert reloaded.JWT_EXPECTED_ISSUER is None
        assert reloaded.JWT_PUBLIC_KEY_URL is None
    finally:
        monkeypatch.undo()
        importlib.reload(app_configs)


@pytest.mark.asyncio
async def test_claim_rejection_does_not_refetch_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def _counting_get(_token: str) -> str:
        calls.append(1)
        return _PUBLIC_PEM

    monkeypatch.setattr(jwt_module, "get_public_key", _counting_get)
    _configure(monkeypatch, "onyx", None)
    assert await verify_jwt_token(_mint({"aud": "some-other-service"})) is None
    assert len(calls) == 1
