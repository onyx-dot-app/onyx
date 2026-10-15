"""The Zendesk provider's per-account resolution: every account lives on its
own `<subdomain>.zendesk.com` host, so the OAuth endpoints, the gateway pattern
and the skill's base URL all come from one admin-supplied field."""

from __future__ import annotations

import re

import pytest

from onyx.db.enums import ExternalAppType
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.registry import PROVIDERS
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
    """The value becomes a URL host, so it fails loudly rather than silently
    addressing elsewhere."""
    with pytest.raises(OnyxError):
        normalise_subdomain(raw)


def test_descriptor_pattern_is_a_single_account_template() -> None:
    """Filled with one account, the pattern matches that account's API and
    nothing else; a `*.zendesk.com` pattern would leak the tenant's token."""
    (template,) = _provider().spec.descriptor.upstream_url_patterns
    assert "{subdomain}" in template

    pattern = template.replace("{subdomain}", "acme")
    assert re.fullmatch(pattern, "https://acme.zendesk.com/api/v2/tickets.json")
    assert not re.fullmatch(pattern, "https://evil.zendesk.com/api/v2/tickets.json")
    assert not re.fullmatch(pattern, "https://acmexzendesk.com/api/v2/tickets")
    assert not re.fullmatch(pattern, "https://acme.zendesk.com/oauth/tokens")


def test_an_unfilled_template_matches_nothing() -> None:
    """An unfilled placeholder must match nothing, not match too much."""
    (template,) = _provider().spec.descriptor.upstream_url_patterns
    assert not re.fullmatch(template, "https://acme.zendesk.com/api/v2/tickets")


def test_skill_template_values_carry_the_account_base_url() -> None:
    assert _provider().skill_template_values({"subdomain": "acme"}) == {
        "base_url": "https://acme.zendesk.com"
    }


def test_oauth_endpoints_are_on_the_configured_account() -> None:
    endpoints = _provider().resolve_oauth_endpoints({"subdomain": "acme"})
    assert (
        endpoints.authorize_url == "https://acme.zendesk.com/oauth/authorizations/new"
    )
    assert endpoints.token_url == "https://acme.zendesk.com/oauth/tokens"


def test_spec_urls_stay_templates() -> None:
    """There is no one Zendesk host, so these must stay templates."""
    oauth = _provider().spec.oauth
    assert "{subdomain}" in oauth.authorize_url
    assert "{subdomain}" in oauth.token_url


def test_providers_on_a_fixed_host_contribute_no_skill_values() -> None:
    """Empty unless a provider's skill needs its own configuration."""
    for provider in PROVIDERS.values():
        if isinstance(provider, ZendeskProvider):
            continue  # per-account: covered above
        assert provider.skill_template_values({}) == {}


def test_token_exchange_posts_json_with_an_explicit_expiry() -> None:
    """Zendesk issues a refresh token only when the request names an expiry."""
    request = _provider().build_token_exchange_request(
        "the-code", "cid", "secret", "https://onyx.test/callback"
    )
    assert request.json_encoded is True
    assert request.headers["Content-Type"] == "application/json"
    assert request.body["grant_type"] == "authorization_code"
    assert request.body["code"] == "the-code"
    assert request.body["redirect_uri"] == "https://onyx.test/callback"
    assert request.body["scope"] == _provider().spec.oauth.scope
    # An integer, as Zendesk's JSON token endpoint documents it.
    assert isinstance(request.body["expires_in"], int)
    assert 300 <= request.body["expires_in"] <= 172800


def test_refresh_request_restates_the_expiry() -> None:
    body = _provider().build_refresh_request("rt", "cid", "secret")
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "rt"
    assert (
        body["expires_in"]
        == _provider()
        .build_token_exchange_request("c", "cid", "s", "https://onyx.test/callback")
        .body["expires_in"]
    )
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


def test_requested_scopes_allow_search_and_supported_writes() -> None:
    """Search and ticket audits reject resource-specific read scopes."""
    scopes = set(_provider().spec.oauth.scope.split())
    assert scopes == {
        "read",
        "tickets:write",
        "hc:write",
        "side_conversations:write",
        "macros:write",
    }
