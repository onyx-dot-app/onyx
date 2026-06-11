"""The HubSpot provider catalog: REST routes resolve to exactly the intended
action, and default policies match the design (reads — including the POST
``/search`` — auto-approve; create/update/archive writes require approval).

The DB-driven ``recognize_actions`` path is covered in
``external_dependency_unit/craft/test_action_matching.py``; here we exercise the
pure rule layer directly."""

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
    matcher, exactly as the proxy matches it."""
    context = MatchContext(ProxiedRequest(method=method, path=path, body=body))
    return {
        endpoint.id
        for endpoint in _CATALOG
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    }


@pytest.mark.parametrize(
    "method, path, expected",
    [
        # Reads across object types collapse onto the generic object actions.
        ("GET", "/crm/v3/objects/contacts", {HubSpotAction.OBJECTS_READ}),
        ("GET", "/crm/v3/objects/companies", {HubSpotAction.OBJECTS_READ}),
        ("GET", "/crm/v3/objects/deals/12345", {HubSpotAction.OBJECTS_READ}),
        # Search is a POST that mutates nothing — its own read action, and it must
        # NOT collapse onto create (which is POST on the parent collection).
        ("POST", "/crm/v3/objects/contacts/search", {HubSpotAction.OBJECTS_SEARCH}),
        ("POST", "/crm/v3/objects/deals/search", {HubSpotAction.OBJECTS_SEARCH}),
        # Properties + owners reads.
        ("GET", "/crm/v3/properties/contacts", {HubSpotAction.PROPERTIES_READ}),
        (
            "GET",
            "/crm/v3/properties/deals/dealname",
            {HubSpotAction.PROPERTIES_READ},
        ),
        ("GET", "/crm/v3/owners", {HubSpotAction.OWNERS_READ}),
        ("GET", "/crm/v3/owners/99", {HubSpotAction.OWNERS_READ}),
        # Writes.
        ("POST", "/crm/v3/objects/contacts", {HubSpotAction.OBJECTS_CREATE}),
        ("PATCH", "/crm/v3/objects/deals/12345", {HubSpotAction.OBJECTS_UPDATE}),
        ("DELETE", "/crm/v3/objects/companies/678", {HubSpotAction.OBJECTS_ARCHIVE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


def test_create_and_search_do_not_collide() -> None:
    """POST on the collection is create; POST on the `/search` subpath is search.
    Each must resolve to exactly one (different) action."""
    assert _matching_actions("POST", "/crm/v3/objects/contacts") == {
        HubSpotAction.OBJECTS_CREATE
    }
    assert _matching_actions("POST", "/crm/v3/objects/contacts/search") == {
        HubSpotAction.OBJECTS_SEARCH
    }


def test_uncatalogued_route_matches_nothing() -> None:
    """A path outside the catalog matches no action — the proxy then falls back
    to the whole-domain ASK gate rather than injecting under a catalog action."""
    assert _matching_actions("POST", "/crm/v3/objects/contacts/batch/read") == set()


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (HubSpotAction.OBJECTS_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.OBJECTS_SEARCH, EndpointPolicy.ALWAYS),
        (HubSpotAction.PROPERTIES_READ, EndpointPolicy.ALWAYS),
        (HubSpotAction.OWNERS_READ, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (HubSpotAction.OBJECTS_CREATE, EndpointPolicy.ASK),
        (HubSpotAction.OBJECTS_UPDATE, EndpointPolicy.ASK),
        (HubSpotAction.OBJECTS_ARCHIVE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(
    action: HubSpotAction, expected_policy: EndpointPolicy
) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
