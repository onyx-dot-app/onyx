import json
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import jwt
import pytest

import onyx.auth.oauth_claims_capture as claims_capture
from onyx.auth.oauth_claims_capture import capture_oauth_login_claims
from onyx.auth.oauth_claims_capture import get_captured_oauth_claims
from onyx.auth.oauth_claims_capture import get_idp_profile_fields
from onyx.auth.oauth_claims_capture import get_idp_profile_placeholder_values


@pytest.fixture(autouse=True)
def _enable_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claims_capture, "IDP_PROFILE_ENRICHMENT_ENABLED", True)


class _FakeOAuthClient:
    name = "openid"

    def __init__(self, userinfo_endpoint: str | None = None):
        self.openid_configuration: dict[str, Any] = {}
        if userinfo_endpoint:
            self.openid_configuration["userinfo_endpoint"] = userinfo_endpoint


def _make_token(claims: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": "at-123",
        "token_type": "Bearer",
        "scope": "openid profile email",
        "expires_at": 1_900_000_000,
        "id_token": jwt.encode(claims, "test-secret", algorithm="HS256"),
    }


@pytest.mark.asyncio
async def test_capture_stores_id_token_claims_and_token_meta() -> None:
    claims = {
        "sub": "abc",
        "email": "user@example.com",
        "name": "User Example",
        "groups": ["g1", "g2"],
    }
    redis = AsyncMock()

    with patch(
        "onyx.auth.oauth_claims_capture.get_async_redis_connection",
        return_value=redis,
    ):
        await capture_oauth_login_claims(
            _FakeOAuthClient(), "user@example.com", _make_token(claims)
        )

    redis.set.assert_awaited_once()
    key, payload = redis.set.await_args.args
    assert "user@example.com" in key
    snapshot = json.loads(payload)
    assert snapshot["id_token_claims"] == claims
    assert snapshot["oauth_name"] == "openid"
    # No userinfo endpoint configured -> empty userinfo, but capture still works
    assert snapshot["userinfo"] == {}
    meta = snapshot["token_meta"]
    assert meta["has_id_token"] is True
    assert meta["has_refresh_token"] is False
    assert meta["scope"] == "openid profile email"
    assert "access_token" in meta["keys"]
    # Raw token values must never be persisted
    assert "at-123" not in payload


@pytest.mark.asyncio
async def test_capture_fetches_userinfo_when_endpoint_available() -> None:
    userinfo = {"sub": "abc", "department": "R&D", "preferred_username": "user"}
    redis = AsyncMock()

    with (
        patch(
            "onyx.auth.oauth_claims_capture.get_async_redis_connection",
            return_value=redis,
        ),
        patch(
            "onyx.auth.oauth_claims_capture._fetch_userinfo",
            new=AsyncMock(return_value=userinfo),
        ) as fetch_mock,
    ):
        await capture_oauth_login_claims(
            _FakeOAuthClient("https://idp.example.com/userinfo"),
            "user@example.com",
            _make_token({"sub": "abc"}),
        )

    fetch_mock.assert_awaited_once_with("https://idp.example.com/userinfo", "at-123")
    snapshot = json.loads(redis.set.await_args.args[1])
    assert snapshot["userinfo"] == userinfo
    # Non-Microsoft IdP -> no Graph profile fetch
    assert snapshot["directory_profile"] is None


@pytest.mark.asyncio
async def test_capture_fetches_directory_profile_for_entra() -> None:
    """When the userinfo endpoint is Microsoft Graph (Entra ID), the capture
    also pulls the directory profile with country/usageLocation."""
    directory_profile = {"country": "Netherlands", "usageLocation": "NL", "city": "Ams"}
    redis = AsyncMock()

    with (
        patch(
            "onyx.auth.oauth_claims_capture.get_async_redis_connection",
            return_value=redis,
        ),
        patch(
            "onyx.auth.oauth_claims_capture._fetch_userinfo",
            new=AsyncMock(return_value={"sub": "abc"}),
        ),
        patch(
            "onyx.auth.oauth_claims_capture._fetch_ms_graph_profile",
            new=AsyncMock(return_value=directory_profile),
        ) as graph_mock,
    ):
        await capture_oauth_login_claims(
            _FakeOAuthClient("https://graph.microsoft.com/oidc/userinfo"),
            "user@example.com",
            _make_token({"sub": "abc"}),
        )

    graph_mock.assert_awaited_once_with("at-123")
    snapshot = json.loads(redis.set.await_args.args[1])
    assert snapshot["directory_profile"] == directory_profile
    assert snapshot["directory_source"] == "ms_graph"


@pytest.mark.asyncio
async def test_capture_never_raises_when_redis_is_down() -> None:
    redis = AsyncMock()
    redis.set.side_effect = ConnectionError("redis down")

    with patch(
        "onyx.auth.oauth_claims_capture.get_async_redis_connection",
        return_value=redis,
    ):
        # Must not raise — login flow depends on it
        await capture_oauth_login_claims(
            _FakeOAuthClient(), "user@example.com", _make_token({"sub": "abc"})
        )


@pytest.mark.asyncio
async def test_get_captured_oauth_claims_roundtrip() -> None:
    stored = {"captured_at": "2026-07-02T00:00:00+00:00", "id_token_claims": {}}
    redis = AsyncMock()
    redis.get.return_value = json.dumps(stored)

    with patch(
        "onyx.auth.oauth_claims_capture.get_async_redis_connection",
        return_value=redis,
    ):
        assert await get_captured_oauth_claims("user@example.com") == stored

    redis.get.return_value = None
    with patch(
        "onyx.auth.oauth_claims_capture.get_async_redis_connection",
        return_value=redis,
    ):
        assert await get_captured_oauth_claims("user@example.com") is None


def test_get_idp_profile_fields_maps_directory_profile() -> None:
    snapshot = {
        "directory_profile": {
            "country": "Germany",
            "usageLocation": "DE",
            "city": "Berlin",
            "state": None,
            "department": "Technology",
            "jobTitle": "SRE",
            "companyName": "ExampleCorp",
        }
    }
    redis = MagicMock()
    redis.get.return_value = json.dumps(snapshot)

    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        fields = get_idp_profile_fields("user@example.com")

    assert fields == {
        "Country": "Germany",
        "Usage location (ISO code)": "DE",
        "City": "Berlin",
        "Department": "Technology",
        "Job title": "SRE",
        "Company": "ExampleCorp",
    }


def test_get_idp_profile_fields_empty_on_missing_or_error() -> None:
    redis = MagicMock()
    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        redis.get.return_value = None
        assert get_idp_profile_fields("user@example.com") == {}

        redis.get.return_value = json.dumps(
            {"directory_profile": {"error": "Graph /me returned HTTP 403."}}
        )
        assert get_idp_profile_fields("user@example.com") == {}

        redis.get.side_effect = ConnectionError("redis down")
        assert get_idp_profile_fields("user@example.com") == {}


def test_get_idp_profile_placeholder_values_maps_directory_profile() -> None:
    snapshot = {
        "directory_profile": {
            "country": "Germany",
            "usageLocation": "DE",
            "city": "Berlin",
            "state": None,
            "department": "Technology",
            "jobTitle": "SRE",
            "companyName": "ExampleCorp",
        }
    }
    redis = MagicMock()
    redis.get.return_value = json.dumps(snapshot)

    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        values = get_idp_profile_placeholder_values("user@example.com")

    # Snake_case placeholder keys; empty/absent fields dropped.
    assert values == {
        "country": "Germany",
        "usage_location": "DE",
        "city": "Berlin",
        "department": "Technology",
        "job_title": "SRE",
        "company_name": "ExampleCorp",
    }


def test_get_idp_profile_placeholder_values_empty_on_missing_or_error() -> None:
    redis = MagicMock()
    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        redis.get.return_value = None
        assert get_idp_profile_placeholder_values("user@example.com") == {}

        redis.get.return_value = json.dumps(
            {"directory_profile": {"error": "Graph /me returned HTTP 403."}}
        )
        assert get_idp_profile_placeholder_values("user@example.com") == {}

        redis.get.side_effect = ConnectionError("redis down")
        assert get_idp_profile_placeholder_values("user@example.com") == {}


@pytest.mark.asyncio
async def test_capture_noop_when_enrichment_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(claims_capture, "IDP_PROFILE_ENRICHMENT_ENABLED", False)
    redis = AsyncMock()
    with patch(
        "onyx.auth.oauth_claims_capture.get_async_redis_connection",
        return_value=redis,
    ):
        await capture_oauth_login_claims(
            _FakeOAuthClient(), "user@example.com", _make_token({"sub": "abc"})
        )
    redis.set.assert_not_awaited()


def test_getters_empty_when_enrichment_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(claims_capture, "IDP_PROFILE_ENRICHMENT_ENABLED", False)
    redis = MagicMock()
    redis.get.return_value = json.dumps({"directory_profile": {"country": "Germany"}})
    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        assert get_idp_profile_fields("user@example.com") == {}
        assert get_idp_profile_placeholder_values("user@example.com") == {}


def test_profile_resolves_from_userinfo_for_generic_oidc() -> None:
    """Okta/Keycloak-style: no directory API, but userinfo carries the
    equivalent claims — the claim map must pick them up."""
    snapshot = {
        "directory_profile": None,
        "userinfo": {
            "department": "Support",
            "title": "Engineer",  # Okta's job-title claim
            "locale": "en-US",  # standard OIDC
            "zoneinfo": "Europe/Amsterdam",  # standard OIDC
            "organization": "ExampleCorp",
        },
        "id_token_claims": {"sub": "abc"},
    }
    redis = MagicMock()
    redis.get.return_value = json.dumps(snapshot)

    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        values = get_idp_profile_placeholder_values("user@example.com")

    assert values == {
        "department": "Support",
        "job_title": "Engineer",
        "preferred_language": "en-US",
        "timezone": "Europe/Amsterdam",
        "company_name": "ExampleCorp",
    }


def test_profile_falls_back_to_id_token_claims() -> None:
    snapshot = {
        "directory_profile": None,
        "userinfo": {},
        "id_token_claims": {"ctry": "NL", "department": "Legal"},
    }
    redis = MagicMock()
    redis.get.return_value = json.dumps(snapshot)

    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        fields = get_idp_profile_fields("user@example.com")

    assert fields == {"Country": "NL", "Department": "Legal"}


def test_directory_profile_takes_precedence_over_userinfo() -> None:
    snapshot = {
        "directory_profile": {"department": "Directory Dept"},
        "userinfo": {"department": "Userinfo Dept"},
        "id_token_claims": {"department": "Token Dept"},
    }
    redis = MagicMock()
    redis.get.return_value = json.dumps(snapshot)

    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        values = get_idp_profile_placeholder_values("user@example.com")

    assert values["department"] == "Directory Dept"


def test_claim_map_override_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IDP_PROFILE_CLAIM_MAP lets a deployment map custom claim names."""
    monkeypatch.setattr(
        claims_capture, "IDP_PROFILE_CLAIM_MAP", {"department": ["custom_dept"]}
    )
    snapshot = {
        "directory_profile": None,
        "userinfo": {"custom_dept": "Platform", "department": "Ignored?"},
        "id_token_claims": {},
    }
    redis = MagicMock()
    redis.get.return_value = json.dumps(snapshot)

    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        values = get_idp_profile_placeholder_values("user@example.com")

    # Configured alias wins; built-in aliases remain as fallback.
    assert values["department"] == "Platform"


def test_source_precedence_holds_across_aliases() -> None:
    """A higher-priority source must win even via a lower-priority alias:
    directory `division` beats userinfo `department`."""
    snapshot = {
        "directory_profile": {"division": "Directory Division"},
        "userinfo": {"department": "Userinfo Dept"},
        "id_token_claims": {},
    }
    redis = MagicMock()
    redis.get.return_value = json.dumps(snapshot)

    with patch("onyx.redis.redis_pool.get_raw_redis_client", return_value=redis):
        values = get_idp_profile_placeholder_values("user@example.com")

    assert values["department"] == "Directory Division"
