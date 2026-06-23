"""The HubSpot provider catalog: CRM REST routes resolve to exactly the intended
action, and default policies match the design (reads — including POST searches —
auto-approve; create/update writes require approval).

The DB-driven ``recognize_actions`` path is covered elsewhere; here we exercise
the pure rule layer directly."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.hubspot import HubSpotAction
from onyx.external_apps.providers.registry import get_endpoint_catalog

_CATALOG = get_endpoint_catalog(ExternalAppType.HUBSPOT)


def _matching_actions(method: str, path: str, body: bytes | None = None) -> set[str]:
    """Every catalog action whose rules recognise the request — through the real
    matcher."""
    context = MatchContext(ProxiedRequest(method=method, path=path, body=body))
    return {
        endpoint.id
        for endpoint in _CATALOG
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    }


@pytest.mark.parametrize(
    "method, path, expected",
    [
        # Reads.
        ("GET", "/crm/v3/objects/contacts", {HubSpotAction.CONTACTS_READ}),
        ("GET", "/crm/v3/objects/contacts/12345", {HubSpotAction.CONTACTS_READ}),
        ("GET", "/crm/v3/objects/companies", {HubSpotAction.COMPANIES_READ}),
        ("GET", "/crm/v3/objects/companies/67890", {HubSpotAction.COMPANIES_READ}),
        ("GET", "/crm/v3/objects/deals", {HubSpotAction.DEALS_READ}),
        ("GET", "/crm/v3/objects/deals/24680", {HubSpotAction.DEALS_READ}),
        # Searches are POSTs but read-only.
        (
            "POST",
            "/crm/v3/objects/contacts/search",
            {HubSpotAction.CONTACTS_SEARCH},
        ),
        (
            "POST",
            "/crm/v3/objects/companies/search",
            {HubSpotAction.COMPANIES_SEARCH},
        ),
        ("POST", "/crm/v3/objects/deals/search", {HubSpotAction.DEALS_SEARCH}),
        # Creates.
        ("POST", "/crm/v3/objects/contacts", {HubSpotAction.CONTACTS_CREATE}),
        ("POST", "/crm/v3/objects/companies", {HubSpotAction.COMPANIES_CREATE}),
        ("POST", "/crm/v3/objects/deals", {HubSpotAction.DEALS_CREATE}),
        # Updates.
        (
            "PATCH",
            "/crm/v3/objects/contacts/12345",
            {HubSpotAction.CONTACTS_UPDATE},
        ),
        (
            "PATCH",
            "/crm/v3/objects/companies/67890",
            {HubSpotAction.COMPANIES_UPDATE},
        ),
        ("PATCH", "/crm/v3/objects/deals/24680", {HubSpotAction.DEALS_UPDATE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


def test_uncatalogued_route_matches_nothing() -> None:
    """A route outside the catalog matches no action — the proxy then falls back
    to the whole-domain ASK gate rather than injecting under a catalog action."""
    assert _matching_actions("GET", "/crm/v3/objects/tickets") == set()


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        # Reads (and POST searches) auto-approve.
        (HubSpotAction.CONTACTS_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.CONTACTS_SEARCH, EndpointPolicy.ALWAYS),
        (HubSpotAction.COMPANIES_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.COMPANIES_SEARCH, EndpointPolicy.ALWAYS),
        (HubSpotAction.DEALS_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.DEALS_SEARCH, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (HubSpotAction.CONTACTS_CREATE, EndpointPolicy.ASK),
        (HubSpotAction.CONTACTS_UPDATE, EndpointPolicy.ASK),
        (HubSpotAction.COMPANIES_CREATE, EndpointPolicy.ASK),
        (HubSpotAction.COMPANIES_UPDATE, EndpointPolicy.ASK),
        (HubSpotAction.DEALS_CREATE, EndpointPolicy.ASK),
        (HubSpotAction.DEALS_UPDATE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(
    action: HubSpotAction, expected_policy: EndpointPolicy
) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
