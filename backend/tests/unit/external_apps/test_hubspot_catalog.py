"""The HubSpot provider catalog: REST routes resolve to exactly the intended
action, and default policies match the design (reads + CRM search auto-approve;
object writes require approval).

Here we exercise the pure rule layer directly (the DB-driven
``recognize_actions`` path is covered elsewhere)."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.hubspot import HubspotAction
from onyx.external_apps.providers.registry import get_endpoint_catalog

_CATALOG = get_endpoint_catalog(ExternalAppType.HUBSPOT)


def _matching_actions(method: str, path: str) -> set[str]:
    """Every catalog action whose rules recognise the request, through the real
    matcher."""
    context = MatchContext(ProxiedRequest(method=method, path=path, body=None))
    return {
        endpoint.id
        for endpoint in _CATALOG
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    }


@pytest.mark.parametrize(
    "method, path, expected",
    [
        # Reads resolve unchanged.
        ("GET", "/crm/v3/owners", {HubspotAction.OWNERS_READ}),
        ("GET", "/crm/v3/owners/42", {HubspotAction.OWNERS_READ}),
        ("GET", "/crm/v3/objects/contacts", {HubspotAction.CONTACTS_READ}),
        ("GET", "/crm/v3/objects/contacts/123", {HubspotAction.CONTACTS_READ}),
        ("GET", "/crm/v3/objects/companies", {HubspotAction.COMPANIES_READ}),
        ("GET", "/crm/v3/objects/companies/123", {HubspotAction.COMPANIES_READ}),
        ("GET", "/crm/v3/objects/deals", {HubspotAction.DEALS_READ}),
        ("GET", "/crm/v3/objects/deals/123", {HubspotAction.DEALS_READ}),
        # Search is a POST read on a distinct sub-path; it must not collide with
        # the create write on the bare object path.
        ("POST", "/crm/v3/objects/contacts/search", {HubspotAction.CRM_SEARCH}),
        ("POST", "/crm/v3/objects/companies/search", {HubspotAction.CRM_SEARCH}),
        ("POST", "/crm/v3/objects/deals/search", {HubspotAction.CRM_SEARCH}),
        # Writes.
        ("POST", "/crm/v3/objects/contacts", {HubspotAction.CONTACTS_WRITE}),
        ("PATCH", "/crm/v3/objects/contacts/123", {HubspotAction.CONTACTS_WRITE}),
        ("POST", "/crm/v3/objects/companies", {HubspotAction.COMPANIES_WRITE}),
        ("PATCH", "/crm/v3/objects/companies/123", {HubspotAction.COMPANIES_WRITE}),
        ("POST", "/crm/v3/objects/deals", {HubspotAction.DEALS_WRITE}),
        ("PATCH", "/crm/v3/objects/deals/123", {HubspotAction.DEALS_WRITE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


def test_uncatalogued_route_matches_nothing() -> None:
    """A path outside the catalog matches no action — the proxy then falls back
    to the whole-domain ASK gate rather than injecting under a catalog action."""
    assert _matching_actions("GET", "/crm/v3/objects/tickets") == set()


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (HubspotAction.OWNERS_READ, EndpointPolicy.ALWAYS),
        (HubspotAction.CONTACTS_READ, EndpointPolicy.ALWAYS),
        (HubspotAction.COMPANIES_READ, EndpointPolicy.ALWAYS),
        (HubspotAction.DEALS_READ, EndpointPolicy.ALWAYS),
        (HubspotAction.CRM_SEARCH, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (HubspotAction.CONTACTS_WRITE, EndpointPolicy.ASK),
        (HubspotAction.COMPANIES_WRITE, EndpointPolicy.ASK),
        (HubspotAction.DEALS_WRITE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(
    action: HubspotAction, expected_policy: EndpointPolicy
) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
