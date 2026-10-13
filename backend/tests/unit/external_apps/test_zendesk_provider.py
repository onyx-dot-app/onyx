"""The Zendesk provider's per-account resolution.

Every Zendesk account lives on its own `<subdomain>.zendesk.com` host, so the
OAuth endpoints, the gateway's URL patterns, and the skill's base URL are all
derived from one admin-supplied field. These tests pin that derivation: the
subdomain is validated before it reaches a URL, and the gateway pattern stays a
literal host so the proxy can never spend this tenant's token elsewhere."""

from __future__ import annotations

import re
from collections.abc import Mapping

import pytest

from onyx.db.enums import ExternalAppType
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import AppInstanceConfig
from onyx.external_apps.providers.registry import PROVIDERS, resolve_instance_config
from onyx.external_apps.providers.zendesk import ZendeskProvider, normalise_subdomain


def _provider() -> ZendeskProvider:
    provider = PROVIDERS[ExternalAppType.ZENDESK]
    assert isinstance(provider, ZendeskProvider)
    return provider


@pytest.mark.parametrize(
    "raw",
    [
        "acme",
        "ACME",
        "  acme  ",
        "acme.zendesk.com",
        "https://acme.zendesk.com",
        "https://acme.zendesk.com/agent/filters/360001",
        "http://ACME.zendesk.com:443/",
    ],
)
def test_subdomain_is_read_out_of_whatever_the_admin_pasted(raw: str) -> None:
    assert normalise_subdomain(raw) == "acme"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        123,
        "acme.example.com",
        "acme.zendesk.com.evil.test",
        "acme corp",
        "-acme",
        "acme-",
        "a" * 64,
        "https://evil.test/?x=acme.zendesk.com",
    ],
)
def test_malformed_subdomain_is_rejected(raw: object) -> None:
    """The value becomes a URL host, so anything that is not a single DNS label
    fails loudly at configure time rather than silently addressing elsewhere."""
    with pytest.raises(OnyxError):
        normalise_subdomain(raw)


def test_gateway_pattern_is_the_configured_account_only() -> None:
    instance = _provider().resolve_instance({"subdomain": "acme"})
    (pattern,) = instance.upstream_url_patterns
    assert re.fullmatch(pattern, "https://acme.zendesk.com/api/v2/tickets.json")
    # Another account, a look-alike host, and the non-API surface are all out.
    assert not re.fullmatch(pattern, "https://evil.zendesk.com/api/v2/tickets.json")
    assert not re.fullmatch(pattern, "https://acmexzendesk.com/api/v2/tickets")
    assert not re.fullmatch(pattern, "https://acme.zendesk.com/oauth/tokens")


def test_skill_template_values_carry_the_account_base_url() -> None:
    instance = _provider().resolve_instance({"subdomain": "acme"})
    assert instance.skill_template_values == {"base_url": "https://acme.zendesk.com"}


def test_oauth_endpoints_are_on_the_configured_account() -> None:
    endpoints = _provider().resolve_oauth_endpoints({"subdomain": "acme"})
    assert (
        endpoints.authorize_url == "https://acme.zendesk.com/oauth/authorizations/new"
    )
    assert endpoints.token_url == "https://acme.zendesk.com/oauth/tokens"


def test_descriptor_carries_no_fallback_pattern() -> None:
    """There is no account-agnostic Zendesk host to fall back to, so the static
    descriptor stays empty: a row is only ever matched on resolved patterns."""
    assert _provider().spec.descriptor.upstream_url_patterns == []


def test_resolve_instance_config_withholds_secret_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry hands providers only their non-secret fields — an admin form
    echoes secrets back masked, and nothing resolved here may contain one."""
    captured: dict[str, str] = {}

    def _spy(
        _self: ZendeskProvider, org_credentials: Mapping[str, str]
    ) -> AppInstanceConfig:
        captured.update(org_credentials)
        return AppInstanceConfig(upstream_url_patterns=[])

    monkeypatch.setattr(ZendeskProvider, "resolve_instance", _spy)
    resolve_instance_config(
        ExternalAppType.ZENDESK,
        {"subdomain": "acme", "client_id": "cid", "client_secret": "shh"},
    )
    assert captured == {"subdomain": "acme", "client_id": "cid"}


def test_token_exchange_posts_json_with_an_explicit_expiry() -> None:
    """Zendesk only issues a refresh token when the request names an expiry, and
    its token endpoint takes a JSON body."""
    request = _provider().build_token_exchange_request(
        "the-code", "cid", "secret", "https://onyx.test/callback"
    )
    assert request.json_encoded is True
    assert request.headers["Content-Type"] == "application/json"
    assert request.body["grant_type"] == "authorization_code"
    assert request.body["code"] == "the-code"
    assert request.body["redirect_uri"] == "https://onyx.test/callback"
    assert int(request.body["expires_in"]) >= 300


def test_refresh_request_restates_the_expiry() -> None:
    body = _provider().build_refresh_request("rt", "cid", "secret")
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "rt"
    assert int(body["expires_in"]) >= 300
    assert _provider().refresh_json_encoded is True


def test_extract_credentials_keeps_what_the_refresh_path_needs() -> None:
    creds = _provider().extract_credentials(
        {
            "access_token": "at",
            "refresh_token": "rt",
            "token_type": "bearer",
            "expires_in": 86400,
            "scope": "tickets:read",
        }
    )
    assert creds["access_token"] == "at"
    assert creds["refresh_token"] == "rt"
    assert creds["expires_in"] == 86400


def test_extract_credentials_rejects_a_response_without_a_token() -> None:
    with pytest.raises(OnyxError):
        _provider().extract_credentials({"error": "invalid_grant"})


def test_requested_scopes_cover_the_catalog_and_nothing_more() -> None:
    """Zendesk has no optional-scope mechanism, so every scope here must be one
    any Support plan can grant — and writes stop at tickets."""
    scopes = set(_provider().spec.oauth.scope.split())
    assert scopes == {
        "tickets:read",
        "tickets:write",
        "users:read",
        "organizations:read",
        "ticket_views:read",
        "satisfaction_ratings:read",
    }
