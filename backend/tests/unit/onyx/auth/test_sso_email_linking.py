"""Per-provider email linking: a provider may claim an existing same-email
account only when the admin enabled it and scoped the provider to domains, and
only for an IdP-verified email. Google's People API email must be marked
verified, matching the OIDC client's guarantee."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx_oauth.exceptions import GetIdEmailError

from onyx.auth.oidc_client import (
    VerifiedEmailGoogleOAuth2,
    _select_primary_verified_email,
)
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.sso_provider import _validate_email_link_scope
from onyx.server.oidc_multi import _should_link_by_email


def _provider(allow: bool, domains: list[str]) -> SSOProvider:
    return SSOProvider(
        name="p",
        display_name="P",
        provider_type=SSOProviderType.OIDC,
        config=None,
        allowed_email_domains=domains,
        allow_email_link=allow,
    )


def test_link_gate_requires_flag_and_domains() -> None:
    assert _should_link_by_email(_provider(True, ["corp.com"])) is True
    assert _should_link_by_email(_provider(False, ["corp.com"])) is False
    assert _should_link_by_email(_provider(True, [])) is False


def test_validate_scope_rejects_link_without_domains() -> None:
    with pytest.raises(ValueError):
        _validate_email_link_scope(True, [])


def test_validate_scope_allows_link_with_domains() -> None:
    _validate_email_link_scope(True, ["corp.com"])
    _validate_email_link_scope(False, [])


def test_select_primary_verified_email() -> None:
    assert (
        _select_primary_verified_email(
            [{"value": "a@corp.com", "metadata": {"primary": True, "verified": True}}]
        )
        == "a@corp.com"
    )
    # Unverified, non-primary, and malformed entries never match.
    assert (
        _select_primary_verified_email(
            [{"value": "a@corp.com", "metadata": {"primary": True, "verified": False}}]
        )
        is None
    )
    assert (
        _select_primary_verified_email(
            [{"value": "a@corp.com", "metadata": {"primary": False, "verified": True}}]
        )
        is None
    )
    assert _select_primary_verified_email(["garbage", {}]) is None


def _google_client_with_response(
    payload: Any, status: int = 200
) -> VerifiedEmailGoogleOAuth2:
    client = VerifiedEmailGoogleOAuth2("cid", "secret")
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    httpx_client = AsyncMock()
    httpx_client.get.return_value = response
    ctx = MagicMock()
    ctx.__aenter__.return_value = httpx_client
    ctx.__aexit__.return_value = None
    client.get_httpx_client = MagicMock(return_value=ctx)  # ty: ignore[invalid-assignment]
    return client


@pytest.mark.asyncio
async def test_google_returns_verified_primary_email() -> None:
    client = _google_client_with_response(
        {
            "resourceName": "people/123",
            "emailAddresses": [
                {"value": "a@corp.com", "metadata": {"primary": True, "verified": True}}
            ],
        }
    )
    user_id, email = await client.get_id_email("tok")
    assert user_id == "people/123"
    assert email == "a@corp.com"


@pytest.mark.asyncio
async def test_google_rejects_unverified_email() -> None:
    client = _google_client_with_response(
        {
            "resourceName": "people/123",
            "emailAddresses": [
                {
                    "value": "a@corp.com",
                    "metadata": {"primary": True, "verified": False},
                }
            ],
        }
    )
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")


@pytest.mark.asyncio
async def test_google_rejects_malformed_body() -> None:
    client = _google_client_with_response({"unexpected": "shape"})
    with pytest.raises(GetIdEmailError):
        await client.get_id_email("tok")
