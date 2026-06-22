"""The HubSpot built-in provider: OAuth, Onyx-managed credentials, and an action
catalog that matches the request paths the bundled ``hubspot_api.py`` helper
calls. Reads are auto-approved (ALWAYS); mutations default to ASK so the egress
gate prompts the user. Self-contained — no network."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.actions import path_matches
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.hubspot import HubSpotAction
from onyx.external_apps.providers.hubspot import HubSpotProvider
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.external_apps.providers.registry import PROVIDERS

_CATALOG = get_endpoint_catalog(ExternalAppType.HUBSPOT)

_READ_ACTIONS = {
    HubSpotAction.CONTACTS_READ,
    HubSpotAction.COMPANIES_READ,
    HubSpotAction.DEALS_READ,
}


def _provider() -> HubSpotProvider:
    provider = PROVIDERS[ExternalAppType.HUBSPOT]
    assert isinstance(provider, HubSpotProvider)
    return provider


def test_registered_as_managed_hubspot_provider() -> None:
    provider = _provider()
    assert isinstance(provider, OnyxManagedExtApp)
    assert provider.spec.app_type == ExternalAppType.HUBSPOT


def test_oauth_endpoints_scopes_and_patterns() -> None:
    spec = _provider().spec
    assert spec.oauth.authorize_url == "https://app.hubspot.com/oauth/authorize"
    assert spec.oauth.token_url == "https://api.hubapi.com/oauth/v1/token"
    assert spec.oauth.scope_param == "scope"
    scopes = spec.oauth.scope.split(" ")
    assert "crm.objects.contacts.read" in scopes
    assert "crm.objects.contacts.write" in scopes
    assert "crm.objects.companies.read" in scopes
    assert "crm.objects.deals.write" in scopes
    assert "oauth" in scopes
    assert spec.descriptor.upstream_url_patterns == ["https://api\\.hubapi\\.com/.*"]
    assert spec.descriptor.auth_template == {"Authorization": "Bearer {access_token}"}


def test_reads_always_writes_ask() -> None:
    """Reads are auto-approved; every mutation defaults to ASK. GET rules belong
    only to read actions and vice versa."""
    for endpoint in _CATALOG:
        methods = {r.method for r in endpoint.matches if isinstance(r, RestRoute)}
        if endpoint.id in _READ_ACTIONS:
            assert endpoint.default_policy == EndpointPolicy.ALWAYS
            assert methods == {"GET"}
        else:
            assert endpoint.default_policy == EndpointPolicy.ASK
            assert "GET" not in methods


def test_managed_credential_keys_match_required_fields() -> None:
    provider = _provider()
    required = {f.key for f in provider.spec.descriptor.required_org_credential_fields}
    assert set(provider.managed_org_credentials) == required


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("GET", "/crm/v3/objects/contacts", {HubSpotAction.CONTACTS_READ}),
        ("GET", "/crm/v3/objects/contacts/123", {HubSpotAction.CONTACTS_READ}),
        ("GET", "/crm/v3/objects/companies", {HubSpotAction.COMPANIES_READ}),
        ("GET", "/crm/v3/objects/companies/123", {HubSpotAction.COMPANIES_READ}),
        ("GET", "/crm/v3/objects/deals", {HubSpotAction.DEALS_READ}),
        ("GET", "/crm/v3/objects/deals/123", {HubSpotAction.DEALS_READ}),
        ("POST", "/crm/v3/objects/contacts", {HubSpotAction.CONTACTS_CREATE}),
        ("PATCH", "/crm/v3/objects/contacts/123", {HubSpotAction.CONTACTS_UPDATE}),
        ("POST", "/crm/v3/objects/companies", {HubSpotAction.COMPANIES_CREATE}),
        ("PATCH", "/crm/v3/objects/companies/123", {HubSpotAction.COMPANIES_UPDATE}),
        ("POST", "/crm/v3/objects/deals", {HubSpotAction.DEALS_CREATE}),
        ("PATCH", "/crm/v3/objects/deals/123", {HubSpotAction.DEALS_UPDATE}),
    ],
)
def test_catalog_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    """Each path the helper actually hits must be claimed by exactly one action,
    so per-action policy resolution can't silently misfire."""
    matched = {
        endpoint.id
        for endpoint in _CATALOG
        for rule in endpoint.matches
        if isinstance(rule, RestRoute)
        and rule.method == method
        and path_matches(rule.path, path)
    }
    assert matched == expected


def test_extract_credentials_pulls_token() -> None:
    provider = _provider()
    creds = provider.extract_credentials(
        {
            "access_token": "tok",
            "refresh_token": "ref",
            "token_type": "bearer",
            "expires_in": 1800,
        }
    )
    assert creds["access_token"] == "tok"
    assert creds["refresh_token"] == "ref"
    assert creds["expires_in"] == 1800


def test_extract_credentials_requires_access_token() -> None:
    from onyx.error_handling.exceptions import OnyxError

    provider = _provider()
    with pytest.raises(OnyxError):
        provider.extract_credentials({"refresh_token": "ref"})


def test_bad_refresh_token_is_terminal() -> None:
    assert "BAD_REFRESH_TOKEN" in HubSpotProvider.terminal_refresh_errors
    assert "invalid_grant" in HubSpotProvider.terminal_refresh_errors
