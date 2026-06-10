"""The HubSpot provider catalog: CRM REST routes resolve to exactly the intended
action, the read-only ``POST .../search`` doesn't collide with the create POSTs,
and default policies match the design (reads auto-approve; writes require
approval).

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


def _matching_actions(method: str, path: str) -> set[str]:
    """Every catalog action whose rules recognise the request — through the real
    matcher, exactly as the proxy parses it."""
    context = MatchContext(ProxiedRequest(method=method, path=path, body=None))
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
        ("GET", "/crm/v3/objects/deals/11223", {HubSpotAction.DEALS_READ}),
        ("GET", "/crm/v3/owners", {HubSpotAction.OWNERS_READ}),
        ("GET", "/crm/v3/owners/42", {HubSpotAction.OWNERS_READ}),
        # Search is a read despite being a POST; the trailing `/search` segment
        # keeps it from colliding with the create POSTs.
        ("POST", "/crm/v3/objects/contacts/search", {HubSpotAction.SEARCH_READ}),
        ("POST", "/crm/v3/objects/companies/search", {HubSpotAction.SEARCH_READ}),
        ("POST", "/crm/v3/objects/deals/search", {HubSpotAction.SEARCH_READ}),
        # Writes.
        ("POST", "/crm/v3/objects/contacts", {HubSpotAction.CONTACTS_CREATE}),
        ("PATCH", "/crm/v3/objects/contacts/12345", {HubSpotAction.CONTACTS_UPDATE}),
        ("POST", "/crm/v3/objects/companies", {HubSpotAction.COMPANIES_CREATE}),
        ("POST", "/crm/v3/objects/deals", {HubSpotAction.DEALS_CREATE}),
        ("POST", "/crm/v3/objects/notes", {HubSpotAction.NOTES_CREATE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


def test_create_and_search_do_not_collide() -> None:
    """The contact create POST and the contact search POST must resolve to
    distinct, single actions (the search has an extra `/search` segment)."""
    assert _matching_actions("POST", "/crm/v3/objects/contacts") == {
        HubSpotAction.CONTACTS_CREATE
    }
    assert _matching_actions("POST", "/crm/v3/objects/contacts/search") == {
        HubSpotAction.SEARCH_READ
    }


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (HubSpotAction.CONTACTS_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.COMPANIES_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.DEALS_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.OWNERS_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.SEARCH_READ, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (HubSpotAction.CONTACTS_CREATE, EndpointPolicy.ASK),
        (HubSpotAction.CONTACTS_UPDATE, EndpointPolicy.ASK),
        (HubSpotAction.COMPANIES_CREATE, EndpointPolicy.ASK),
        (HubSpotAction.DEALS_CREATE, EndpointPolicy.ASK),
        (HubSpotAction.NOTES_CREATE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(
    action: HubSpotAction, expected_policy: EndpointPolicy
) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
