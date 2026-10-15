"""The Zendesk provider catalog: REST routes resolve to exactly the intended
action — including the ``.json`` suffix form Zendesk accepts interchangeably —
and default policies match the design.

The DB-driven ``recognize_actions`` path is covered elsewhere; here we exercise
the pure rule layer directly, mirroring ``test_notion_catalog.py``."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.external_apps.matching.request import MatchContext, ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.external_apps.providers.zendesk import ZendeskAction

_CATALOG = get_endpoint_catalog(ExternalAppType.ZENDESK)

_WRITE_ACTIONS = {
    ZendeskAction.TICKETS_CREATE,
    ZendeskAction.TICKETS_UPDATE,
    ZendeskAction.TICKETS_DELETE,
    ZendeskAction.HELP_CENTER_WRITE,
    ZendeskAction.SIDE_CONVERSATIONS_WRITE,
    ZendeskAction.MACROS_WRITE,
}


def _matching_actions(method: str, path: str) -> set[str]:
    """Every catalog action whose rules recognise the request — through the real
    matcher, so path templates are compared exactly as the proxy compares them."""
    context = MatchContext(ProxiedRequest(method=method, path=path, body=None))
    return {
        endpoint.id
        for endpoint in _CATALOG
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    }


@pytest.mark.parametrize(
    "method, path, expected",
    [
        # Tickets: collection, one ticket, and its sub-resources.
        ("GET", "/api/v2/tickets", {ZendeskAction.TICKETS_READ}),
        ("GET", "/api/v2/tickets/12345", {ZendeskAction.TICKETS_READ}),
        ("GET", "/api/v2/tickets/12345/comments", {ZendeskAction.TICKETS_READ}),
        ("GET", "/api/v2/tickets/12345/audits", {ZendeskAction.TICKETS_READ}),
        # Search and the incremental export a scheduled task polls.
        ("GET", "/api/v2/search", {ZendeskAction.SEARCH}),
        ("GET", "/api/v2/search/export", {ZendeskAction.SEARCH}),
        (
            "GET",
            "/api/v2/incremental/tickets/cursor",
            {ZendeskAction.INCREMENTAL_EXPORT},
        ),
        # Metrics live under both the collection and one ticket.
        ("GET", "/api/v2/ticket_metrics", {ZendeskAction.TICKET_METRICS_READ}),
        (
            "GET",
            "/api/v2/tickets/12345/metrics",
            {ZendeskAction.TICKET_METRICS_READ},
        ),
        (
            "GET",
            "/api/v2/satisfaction_ratings",
            {ZendeskAction.SATISFACTION_RATINGS_READ},
        ),
        # /users/me and /users/{id} both resolve to USERS_READ.
        ("GET", "/api/v2/users", {ZendeskAction.USERS_READ}),
        ("GET", "/api/v2/users/me", {ZendeskAction.USERS_READ}),
        ("GET", "/api/v2/users/42", {ZendeskAction.USERS_READ}),
        ("GET", "/api/v2/organizations/7", {ZendeskAction.ORGANIZATIONS_READ}),
        (
            "GET",
            "/api/v2/organizations/7/tickets",
            {ZendeskAction.ORGANIZATIONS_READ},
        ),
        ("GET", "/api/v2/views", {ZendeskAction.VIEWS_READ}),
        ("GET", "/api/v2/views/360001/tickets", {ZendeskAction.VIEWS_READ}),
        ("GET", "/api/v2/ticket_fields", {ZendeskAction.TICKET_FIELDS_READ}),
        # Writes.
        ("POST", "/api/v2/tickets", {ZendeskAction.TICKETS_CREATE}),
        ("POST", "/api/v2/tickets/create_many", {ZendeskAction.TICKETS_CREATE}),
        ("PUT", "/api/v2/tickets/12345", {ZendeskAction.TICKETS_UPDATE}),
        ("PUT", "/api/v2/tickets/update_many", {ZendeskAction.TICKETS_UPDATE}),
        # Tags share the ticket-update action; see the catalog comment.
        ("PUT", "/api/v2/tickets/12345/tags", {ZendeskAction.TICKETS_UPDATE}),
        ("POST", "/api/v2/tickets/12345/tags", {ZendeskAction.TICKETS_UPDATE}),
        ("DELETE", "/api/v2/tickets/12345", {ZendeskAction.TICKETS_DELETE}),
        # A read route under a write method (or vice versa) matches nothing, so
        # the gate falls back to asking about the whole domain.
        ("POST", "/api/v2/views", set()),
        ("GET", "/api/v2/triggers", set()),
    ],
)
def test_route_resolves_to_expected_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/v2/tickets"),
        ("GET", "/api/v2/tickets/12345/comments"),
        ("GET", "/api/v2/search"),
        ("GET", "/api/v2/incremental/tickets/cursor"),
        ("GET", "/api/v2/views/360001/tickets"),
        ("POST", "/api/v2/tickets"),
        ("PUT", "/api/v2/tickets/12345/tags"),
    ],
)
def test_json_suffix_resolves_to_the_same_action(method: str, path: str) -> None:
    """The same endpoint either way, so neither spelling may slip the gate."""
    assert _matching_actions(method, path) == _matching_actions(method, f"{path}.json")


def test_ticket_id_placeholder_absorbs_the_json_suffix() -> None:
    """A trailing id already matches `123.json`, so it carries no twin."""
    assert _matching_actions("GET", "/api/v2/tickets/12345.json") == {
        ZendeskAction.TICKETS_READ
    }


def test_tags_cannot_be_changed_outside_the_ticket_update_action() -> None:
    """The matcher sees method and path only, so every route that can change a
    tag must resolve to one action or the policy is bypassable."""
    tag_routes = [
        ("PUT", "/api/v2/tickets/12345/tags"),
        ("POST", "/api/v2/tickets/12345/tags"),
        ("DELETE", "/api/v2/tickets/12345/tags"),
        ("DELETE", "/api/v2/tickets/12345/tags.json"),
        ("PUT", "/api/v2/tickets/12345"),
        ("PUT", "/api/v2/tickets/update_many"),
    ]
    for method, path in tag_routes:
        assert _matching_actions(method, path) == {ZendeskAction.TICKETS_UPDATE}


def test_every_catalog_id_is_unique() -> None:
    ids = [endpoint.id for endpoint in _CATALOG]
    assert len(ids) == len(set(ids))


def test_reads_auto_approve_and_writes_ask() -> None:
    """Reads run unattended; every supported write needs approval."""
    for endpoint in _CATALOG:
        expected = (
            EndpointPolicy.ASK
            if endpoint.id in _WRITE_ACTIONS
            else EndpointPolicy.ALWAYS
        )
        assert endpoint.default_policy is expected, endpoint.id


@pytest.mark.parametrize("suffix", ["", ".json"])
@pytest.mark.parametrize(
    "path, read_action, write_action",
    [
        (
            "/api/v2/help_center/sections/12/articles",
            ZendeskAction.HELP_CENTER_READ,
            ZendeskAction.HELP_CENTER_WRITE,
        ),
        (
            "/api/v2/help_center/en-us/sections/12/articles",
            ZendeskAction.HELP_CENTER_READ,
            ZendeskAction.HELP_CENTER_WRITE,
        ),
        (
            "/api/v2/help_center/articles/34",
            ZendeskAction.HELP_CENTER_READ,
            ZendeskAction.HELP_CENTER_WRITE,
        ),
        (
            "/api/v2/help_center/articles/34/translations/en-us",
            ZendeskAction.HELP_CENTER_READ,
            ZendeskAction.HELP_CENTER_WRITE,
        ),
        (
            "/api/v2/tickets/12/side_conversations",
            ZendeskAction.SIDE_CONVERSATIONS_READ,
            ZendeskAction.SIDE_CONVERSATIONS_WRITE,
        ),
        (
            "/api/v2/tickets/12/side_conversations/abc/reply",
            ZendeskAction.SIDE_CONVERSATIONS_READ,
            ZendeskAction.SIDE_CONVERSATIONS_WRITE,
        ),
        (
            "/api/v2/tickets/12/side_conversations/abc/events",
            ZendeskAction.SIDE_CONVERSATIONS_READ,
            ZendeskAction.SIDE_CONVERSATIONS_WRITE,
        ),
        ("/api/v2/macros", ZendeskAction.MACROS_READ, ZendeskAction.MACROS_WRITE),
        ("/api/v2/macros/34", ZendeskAction.MACROS_READ, ZendeskAction.MACROS_WRITE),
        (
            "/api/v2/macros/update_many",
            ZendeskAction.MACROS_READ,
            ZendeskAction.MACROS_WRITE,
        ),
        (
            "/api/v2/macros/destroy_many",
            ZendeskAction.MACROS_READ,
            ZendeskAction.MACROS_WRITE,
        ),
    ],
)
def test_resource_policies_cover_nested_and_bulk_routes(
    path: str, read_action: ZendeskAction, write_action: ZendeskAction, suffix: str
) -> None:
    assert _matching_actions("GET", path + suffix) == {read_action}
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert _matching_actions(method, path + suffix) == {write_action}


def test_new_policies_do_not_claim_other_resources() -> None:
    for path in (
        "/api/v2/views",
        "/api/v2/triggers",
        "/api/v2/automations",
        "/api/v2/macros_extra",
        "/api/v2/tickets/12/side_conversations_extra",
    ):
        assert _matching_actions("POST", path) == set()
