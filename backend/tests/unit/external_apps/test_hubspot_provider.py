"""The HubSpot built-in provider: it is registered and resolvable, its action
catalog claims the request paths the bundled ``hubspot_api.py`` helper calls,
its OAuth token response maps to stored credentials, and reads auto-approve
(ALWAYS) while writes default to ASK (require approval)."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import path_matches
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.hubspot import HubSpotAction
from onyx.external_apps.providers.hubspot import HubSpotProvider
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.external_apps.providers.registry import PROVIDERS

_READ_ACTIONS = {
    HubSpotAction.ACCOUNT_READ,
    HubSpotAction.CONTACTS_READ,
    HubSpotAction.COMPANIES_READ,
    HubSpotAction.DEALS_READ,
    HubSpotAction.SEARCH_READ,
}

_WRITE_ACTIONS = {
    HubSpotAction.CONTACTS_CREATE,
    HubSpotAction.CONTACTS_UPDATE,
}


def _provider() -> HubSpotProvider:
    provider = PROVIDERS[ExternalAppType.HUBSPOT]
    assert isinstance(provider, HubSpotProvider)
    return provider


def test_registered_and_resolvable() -> None:
    provider = _provider()
    assert provider.spec.app_type == ExternalAppType.HUBSPOT
    assert provider.spec.app_name == "HubSpot"


def test_oauth_and_patterns() -> None:
    spec = _provider().spec
    assert spec.oauth.authorize_url == "https://app.hubspot.com/oauth/authorize"
    assert spec.oauth.token_url == "https://api.hubapi.com/oauth/v1/token"
    assert spec.oauth.scope_param == "scope"
    assert "oauth" in spec.oauth.scope.split()
    assert spec.descriptor.upstream_url_patterns == ["https://api\\.hubapi\\.com/.*"]
    assert spec.descriptor.auth_template == {"Authorization": "Bearer {access_token}"}


def test_required_org_credential_fields() -> None:
    fields = {f.key: f for f in _provider().spec.descriptor.required_org_credential_fields}
    assert set(fields) == {"client_id", "client_secret"}
    assert fields["client_secret"].secret is True
    assert fields["client_id"].secret is False


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("GET", "/account-info/v3/details", HubSpotAction.ACCOUNT_READ),
        ("GET", "/crm/v3/objects/contacts", HubSpotAction.CONTACTS_READ),
        ("GET", "/crm/v3/objects/contacts/123", HubSpotAction.CONTACTS_READ),
        ("GET", "/crm/v3/objects/companies", HubSpotAction.COMPANIES_READ),
        ("GET", "/crm/v3/objects/companies/456", HubSpotAction.COMPANIES_READ),
        ("GET", "/crm/v3/objects/deals", HubSpotAction.DEALS_READ),
        ("GET", "/crm/v3/objects/deals/789", HubSpotAction.DEALS_READ),
        ("POST", "/crm/v3/objects/contacts/search", HubSpotAction.SEARCH_READ),
        ("POST", "/crm/v3/objects/companies/search", HubSpotAction.SEARCH_READ),
        ("POST", "/crm/v3/objects/deals/search", HubSpotAction.SEARCH_READ),
        ("POST", "/crm/v3/objects/contacts", HubSpotAction.CONTACTS_CREATE),
        ("PATCH", "/crm/v3/objects/contacts/123", HubSpotAction.CONTACTS_UPDATE),
    ],
)
def test_catalog_resolves_to_exactly_one_action(
    method: str, path: str, expected: HubSpotAction
) -> None:
    """Each path the helper hits is claimed by exactly one action, so per-action
    policy resolution can't silently misfire."""
    catalog = get_endpoint_catalog(ExternalAppType.HUBSPOT)
    matched = [
        endpoint.id
        for endpoint in catalog
        for rule in endpoint.matches
        if isinstance(rule, RestRoute)
        and rule.method == method
        and path_matches(rule.path, path)
    ]
    assert matched == [expected], f"{method} {path} matched {matched}"


def test_reads_always_writes_ask() -> None:
    """Reads auto-approve; writes require approval out of the box."""
    by_id = {e.id: e for e in _provider().spec.endpoint_catalog}
    for action in _READ_ACTIONS:
        assert by_id[action].default_policy == EndpointPolicy.ALWAYS
    for action in _WRITE_ACTIONS:
        assert by_id[action].default_policy == EndpointPolicy.ASK


def test_extract_credentials_happy_path() -> None:
    creds = _provider().extract_credentials(
        {
            "access_token": "tok-123",
            "refresh_token": "refresh-456",
            "expires_in": 1800,
            "token_type": "bearer",
        }
    )
    assert creds["access_token"] == "tok-123"
    assert creds["refresh_token"] == "refresh-456"
    assert creds["expires_in"] == 1800
    assert creds["token_type"] == "bearer"


def test_extract_credentials_missing_token_raises() -> None:
    with pytest.raises(OnyxError):
        _provider().extract_credentials({"refresh_token": "r", "expires_in": 1800})
