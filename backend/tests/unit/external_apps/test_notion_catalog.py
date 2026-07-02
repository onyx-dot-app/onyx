"""The Notion provider catalog: REST routes resolve to exactly the intended
action, and default policies match the design (reads auto-approve; page / block /
database / comment writes require approval).

The DB-driven ``recognize_actions`` path is covered elsewhere; here we exercise
the pure rule layer directly, mirroring ``test_github_catalog.py``."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.notion import NotionAction
from onyx.external_apps.providers.registry import get_endpoint_catalog

_CATALOG = get_endpoint_catalog(ExternalAppType.NOTION)


def _matching_actions(method: str, path: str, body: bytes | None = None) -> set[str]:
    """Every catalog action whose rules recognise the request — through the real
    matcher, so path templates are compared exactly as the proxy compares them."""
    context = MatchContext(ProxiedRequest(method=method, path=path, body=body))
    return {
        endpoint.id
        for endpoint in _CATALOG
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    }


@pytest.mark.parametrize(
    "method, path, expected",
    [
        # Users — /users/me and /users/{id} both resolve to USERS_READ.
        ("GET", "/v1/users", {NotionAction.USERS_READ}),
        ("GET", "/v1/users/me", {NotionAction.USERS_READ}),
        (
            "GET",
            "/v1/users/1234abcd-1234-1234-1234-1234567890ab",
            {NotionAction.USERS_READ},
        ),
        # Search + data-source query are reads even though POSTs.
        ("POST", "/v1/search", {NotionAction.SEARCH}),
        ("POST", "/v1/data_sources/ds123/query", {NotionAction.DATA_SOURCES_QUERY}),
        # Pages.
        ("GET", "/v1/pages/page123", {NotionAction.PAGES_READ}),
        (
            "GET",
            "/v1/pages/page123/properties/prop456",
            {NotionAction.PAGES_READ},
        ),
        # Blocks — a bare block vs its children are distinct actions.
        ("GET", "/v1/blocks/block123", {NotionAction.BLOCKS_READ}),
        ("GET", "/v1/blocks/block123/children", {NotionAction.BLOCKS_READ}),
        # Databases (containers) vs data sources (schemas) are distinct reads.
        ("GET", "/v1/databases/db123", {NotionAction.DATABASES_READ}),
        ("GET", "/v1/data_sources/ds123", {NotionAction.DATA_SOURCES_READ}),
        ("GET", "/v1/comments", {NotionAction.COMMENTS_READ}),
        # Writes.
        ("POST", "/v1/pages", {NotionAction.PAGES_CREATE}),
        ("PATCH", "/v1/pages/page123", {NotionAction.PAGES_UPDATE}),
        (
            "PATCH",
            "/v1/blocks/block123/children",
            {NotionAction.BLOCKS_APPEND},
        ),
        ("PATCH", "/v1/blocks/block123", {NotionAction.BLOCKS_UPDATE}),
        ("DELETE", "/v1/blocks/block123", {NotionAction.BLOCKS_DELETE}),
        ("POST", "/v1/databases", {NotionAction.DATABASES_CREATE}),
        ("PATCH", "/v1/databases/db123", {NotionAction.DATABASES_UPDATE}),
        # Creating a data source vs querying one must not collide.
        ("POST", "/v1/data_sources", {NotionAction.DATA_SOURCES_CREATE}),
        ("PATCH", "/v1/data_sources/ds123", {NotionAction.DATA_SOURCES_UPDATE}),
        ("POST", "/v1/comments", {NotionAction.COMMENTS_CREATE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


def test_page_update_and_block_children_do_not_collide() -> None:
    """PATCH on a block itself vs its children must be different actions, so the
    admin can allow appending content without allowing arbitrary block edits."""
    assert _matching_actions("PATCH", "/v1/blocks/b1/children") == {
        NotionAction.BLOCKS_APPEND
    }
    assert _matching_actions("PATCH", "/v1/blocks/b1") == {NotionAction.BLOCKS_UPDATE}


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (NotionAction.USERS_READ, EndpointPolicy.ALWAYS),
        (NotionAction.SEARCH, EndpointPolicy.ALWAYS),
        (NotionAction.PAGES_READ, EndpointPolicy.ALWAYS),
        (NotionAction.BLOCKS_READ, EndpointPolicy.ALWAYS),
        (NotionAction.DATABASES_READ, EndpointPolicy.ALWAYS),
        (NotionAction.DATA_SOURCES_READ, EndpointPolicy.ALWAYS),
        (NotionAction.DATA_SOURCES_QUERY, EndpointPolicy.ALWAYS),
        (NotionAction.COMMENTS_READ, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (NotionAction.PAGES_CREATE, EndpointPolicy.ASK),
        (NotionAction.PAGES_UPDATE, EndpointPolicy.ASK),
        (NotionAction.BLOCKS_APPEND, EndpointPolicy.ASK),
        (NotionAction.BLOCKS_UPDATE, EndpointPolicy.ASK),
        (NotionAction.BLOCKS_DELETE, EndpointPolicy.ASK),
        (NotionAction.DATABASES_CREATE, EndpointPolicy.ASK),
        (NotionAction.DATABASES_UPDATE, EndpointPolicy.ASK),
        (NotionAction.DATA_SOURCES_CREATE, EndpointPolicy.ASK),
        (NotionAction.DATA_SOURCES_UPDATE, EndpointPolicy.ASK),
        (NotionAction.COMMENTS_CREATE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(
    action: NotionAction, expected_policy: EndpointPolicy
) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
