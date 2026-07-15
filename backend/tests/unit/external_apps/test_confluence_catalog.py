"""The Confluence provider catalog: REST routes resolve to exactly the intended
action, and default policies match the design (site discovery, reads, and CQL
search auto-approve; content create / update / delete require approval).

Here we exercise the pure rule layer directly (the DB-driven
``recognize_actions`` path is covered elsewhere), mirroring
``test_hubspot_catalog.py`` and ``test_notion_catalog.py``.

Paths use a real-looking Atlassian cloud id and numeric Confluence content ids,
matching what the proxy actually sees after ``https://api.atlassian.com``."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.confluence import ConfluenceAction
from onyx.external_apps.providers.registry import get_endpoint_catalog

_CATALOG = get_endpoint_catalog(ExternalAppType.CONFLUENCE)

# A real-looking Atlassian cloud id and the classic Confluence Cloud REST base.
_CLOUD_ID = "11111111-2222-3333-4444-555555555555"
_WIKI = f"/ex/confluence/{_CLOUD_ID}/wiki/rest/api"


def _matching_actions(method: str, path: str) -> set[str]:
    """Every catalog action whose rules recognise the request, through the real
    matcher — so path templates are compared exactly as the proxy compares them.
    """
    context = MatchContext(ProxiedRequest(method=method, path=path, body=None))
    return {
        endpoint.id
        for endpoint in _CATALOG
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    }


@pytest.mark.parametrize(
    "method, path, expected",
    [
        # Site discovery is the one unscoped call.
        (
            "GET",
            "/oauth/token/accessible-resources",
            {ConfluenceAction.ACCESSIBLE_RESOURCES},
        ),
        # Reads.
        ("GET", f"{_WIKI}/user/current", {ConfluenceAction.CURRENT_USER}),
        ("GET", f"{_WIKI}/space", {ConfluenceAction.SPACES_READ}),
        # CQL search lives on the dedicated search endpoint, kept off the
        # `/content/` path so it can't collide with a content read.
        ("GET", f"{_WIKI}/search", {ConfluenceAction.CONTENT_SEARCH}),
        ("GET", f"{_WIKI}/content", {ConfluenceAction.CONTENT_LIST}),
        ("GET", f"{_WIKI}/content/123456", {ConfluenceAction.CONTENT_READ}),
        (
            "GET",
            f"{_WIKI}/content/123456/child/page",
            {ConfluenceAction.CONTENT_CHILDREN_READ},
        ),
        # Writes.
        ("POST", f"{_WIKI}/content", {ConfluenceAction.CONTENT_CREATE}),
        ("PUT", f"{_WIKI}/content/123456", {ConfluenceAction.CONTENT_UPDATE}),
        ("DELETE", f"{_WIKI}/content/123456", {ConfluenceAction.CONTENT_DELETE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


def test_search_and_content_read_do_not_collide() -> None:
    """CQL search is catalogued under the dedicated ``.../search`` endpoint
    rather than ``.../content/search``: the content-read template
    ``.../content/{content_id}`` would otherwise swallow a literal ``search``
    segment (the matcher has no route precedence), double-matching the request.

    So the search route resolves to exactly the search action, a real numeric
    content id resolves to exactly the read action, and the two never overlap.
    """
    assert _matching_actions("GET", f"{_WIKI}/search") == {
        ConfluenceAction.CONTENT_SEARCH
    }
    assert _matching_actions("GET", f"{_WIKI}/content/123456") == {
        ConfluenceAction.CONTENT_READ
    }


def test_content_read_and_write_split_on_method() -> None:
    """The bare ``/content`` path lists (GET) vs creates (POST); the id path
    reads (GET) vs updates (PUT) vs deletes (DELETE). Each verb is a distinct
    action so an admin can allow reads without allowing writes."""
    assert _matching_actions("GET", f"{_WIKI}/content") == {
        ConfluenceAction.CONTENT_LIST
    }
    assert _matching_actions("POST", f"{_WIKI}/content") == {
        ConfluenceAction.CONTENT_CREATE
    }
    assert _matching_actions("GET", f"{_WIKI}/content/123456") == {
        ConfluenceAction.CONTENT_READ
    }
    assert _matching_actions("PUT", f"{_WIKI}/content/123456") == {
        ConfluenceAction.CONTENT_UPDATE
    }
    assert _matching_actions("DELETE", f"{_WIKI}/content/123456") == {
        ConfluenceAction.CONTENT_DELETE
    }


def test_uncatalogued_route_matches_nothing() -> None:
    """A path outside the catalog matches no action — the proxy then falls back
    to the whole-domain ASK gate rather than injecting under a catalog action."""
    assert _matching_actions("GET", f"{_WIKI}/longtask/123") == set()


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (ConfluenceAction.ACCESSIBLE_RESOURCES, EndpointPolicy.ALWAYS),
        (ConfluenceAction.CURRENT_USER, EndpointPolicy.ALWAYS),
        (ConfluenceAction.SPACES_READ, EndpointPolicy.ALWAYS),
        (ConfluenceAction.CONTENT_SEARCH, EndpointPolicy.ALWAYS),
        (ConfluenceAction.CONTENT_LIST, EndpointPolicy.ALWAYS),
        (ConfluenceAction.CONTENT_READ, EndpointPolicy.ALWAYS),
        (ConfluenceAction.CONTENT_CHILDREN_READ, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (ConfluenceAction.CONTENT_CREATE, EndpointPolicy.ASK),
        (ConfluenceAction.CONTENT_UPDATE, EndpointPolicy.ASK),
        (ConfluenceAction.CONTENT_DELETE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(
    action: ConfluenceAction, expected_policy: EndpointPolicy
) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
