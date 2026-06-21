"""The HubSpot built-in provider: OAuth + Onyx-managed, and its action catalog
matches the request paths the bundled ``hubspot_api.py`` helper calls. Reads
(list/get/search) are auto-approved (ALWAYS); writes (create/update) default to
ASK so the egress approval gate prompts the user."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.actions import path_matches
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.hubspot import HubSpotAction
from onyx.external_apps.providers.hubspot import HubSpotProvider
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.external_apps.providers.registry import PROVIDERS

_READ_ACTIONS = {
    HubSpotAction.CONTACTS_READ,
    HubSpotAction.CONTACTS_SEARCH,
    HubSpotAction.COMPANIES_READ,
    HubSpotAction.COMPANIES_SEARCH,
    HubSpotAction.DEALS_READ,
    HubSpotAction.DEALS_SEARCH,
}


def _provider() -> HubSpotProvider:
    provider = PROVIDERS[ExternalAppType.HUBSPOT]
    assert isinstance(provider, HubSpotProvider)
    return provider


def test_registered_as_managed_oauth_provider() -> None:
    provider = _provider()
    assert isinstance(provider, OnyxManagedExtApp)
    assert isinstance(provider, OAuthExternalAppProvider)
    assert provider.spec.app_type == ExternalAppType.HUBSPOT
    assert provider.spec.app_name == "HubSpot"


def test_oauth_spec_fields() -> None:
    spec = _provider().spec
    assert spec.oauth.authorize_url == "https://app.hubspot.com/oauth/authorize"
    assert spec.oauth.token_url == "https://api.hubapi.com/oauth/v1/token"
    assert spec.oauth.scope_param == "scope"
    # CRM read/write scopes for the three supported object types.
    assert spec.oauth.scope == (
        "crm.objects.contacts.read crm.objects.contacts.write "
        "crm.objects.companies.read crm.objects.companies.write "
        "crm.objects.deals.read crm.objects.deals.write"
    )
    assert spec.descriptor.upstream_url_patterns == ["https://api\\.hubapi\\.com/.*"]
    assert spec.descriptor.auth_template == {"Authorization": "Bearer {access_token}"}


def test_managed_credential_keys_match_required_fields() -> None:
    provider = _provider()
    required = {f.key for f in provider.spec.descriptor.required_org_credential_fields}
    assert set(provider.managed_org_credentials) == required
    assert required == {"client_id", "client_secret"}


def test_catalog_ids_unique() -> None:
    catalog = get_endpoint_catalog(ExternalAppType.HUBSPOT)
    ids = [endpoint.id for endpoint in catalog]
    assert len(ids) == len(set(ids))
    assert len(catalog) == 12


def test_reads_always_writes_ask() -> None:
    """Reads (list/get/search) auto-approve; writes (create/update) default to
    ASK. Search is a POST read, so policy — not method — defines a read here."""
    for endpoint in _provider().spec.endpoint_catalog:
        if endpoint.id in _READ_ACTIONS:
            assert endpoint.default_policy == EndpointPolicy.ALWAYS
        else:
            assert endpoint.default_policy == EndpointPolicy.ASK


def test_extract_credentials_keeps_refresh_token() -> None:
    creds = _provider().extract_credentials(
        {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 1800,
            "token_type": "bearer",
        }
    )
    assert creds["access_token"] == "at"
    assert creds["refresh_token"] == "rt"
    assert creds["expires_in"] == 1800


def test_extract_credentials_requires_access_token() -> None:
    from onyx.error_handling.exceptions import OnyxError

    with pytest.raises(OnyxError):
        _provider().extract_credentials({"refresh_token": "rt"})


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("GET", "/crm/v3/objects/contacts", {HubSpotAction.CONTACTS_READ}),
        ("GET", "/crm/v3/objects/contacts/123", {HubSpotAction.CONTACTS_READ}),
        ("POST", "/crm/v3/objects/contacts/search", {HubSpotAction.CONTACTS_SEARCH}),
        ("POST", "/crm/v3/objects/contacts", {HubSpotAction.CONTACTS_CREATE}),
        ("PATCH", "/crm/v3/objects/contacts/123", {HubSpotAction.CONTACTS_UPDATE}),
        ("GET", "/crm/v3/objects/companies", {HubSpotAction.COMPANIES_READ}),
        ("GET", "/crm/v3/objects/companies/123", {HubSpotAction.COMPANIES_READ}),
        ("POST", "/crm/v3/objects/companies/search", {HubSpotAction.COMPANIES_SEARCH}),
        ("POST", "/crm/v3/objects/companies", {HubSpotAction.COMPANIES_CREATE}),
        ("PATCH", "/crm/v3/objects/companies/123", {HubSpotAction.COMPANIES_UPDATE}),
        ("GET", "/crm/v3/objects/deals", {HubSpotAction.DEALS_READ}),
        ("GET", "/crm/v3/objects/deals/123", {HubSpotAction.DEALS_READ}),
        ("POST", "/crm/v3/objects/deals/search", {HubSpotAction.DEALS_SEARCH}),
        ("POST", "/crm/v3/objects/deals", {HubSpotAction.DEALS_CREATE}),
        ("PATCH", "/crm/v3/objects/deals/123", {HubSpotAction.DEALS_UPDATE}),
    ],
)
def test_catalog_recognises_helper_request_paths(
    method: str, path: str, expected: set[str]
) -> None:
    """Each path the helper actually hits must be claimed by exactly one action,
    so per-action policy resolution can't silently misfire."""
    matched = {
        endpoint.id
        for endpoint in _provider().spec.endpoint_catalog
        for rule in endpoint.matches
        if isinstance(rule, RestRoute)
        and rule.method == method
        and path_matches(rule.path, path)
    }
    assert matched == expected
