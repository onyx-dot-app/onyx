"""The Zendesk provider catalog: REST routes resolve to exactly the intended
action — including the ``.json`` suffix form Zendesk accepts interchangeably —
and default policies match the design (reads auto-approve; ticket writes and
deletes require approval).

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
    ZendeskAction.TICKET_TAGS_UPDATE,
    ZendeskAction.TICKETS_DELETE,
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
        ("PUT", "/api/v2/tickets/12345/tags", {ZendeskAction.TICKET_TAGS_UPDATE}),
        ("POST", "/api/v2/tickets/12345/tags", {ZendeskAction.TICKET_TAGS_UPDATE}),
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
    """Zendesk serves `/api/v2/tickets` and `/api/v2/tickets.json` as the same
    endpoint, so the catalog must not let one of them slip the gate."""
    assert _matching_actions(method, path) == _matching_actions(method, f"{path}.json")


def test_ticket_id_placeholder_absorbs_the_json_suffix() -> None:
    """A trailing id already matches `123.json`, so those routes carry no twin
    and `/api/v2/tickets/123.json` still resolves."""
    assert _matching_actions("GET", "/api/v2/tickets/12345.json") == {
        ZendeskAction.TICKETS_READ
    }


def test_every_catalog_id_is_unique() -> None:
    ids = [endpoint.id for endpoint in _CATALOG]
    assert len(ids) == len(set(ids))


def test_reads_auto_approve_and_writes_ask() -> None:
    """Reads run unattended — a scheduled task is the point of this app — while
    anything that changes or removes a ticket needs a human."""
    for endpoint in _CATALOG:
        expected = (
            EndpointPolicy.ASK
            if endpoint.id in _WRITE_ACTIONS
            else EndpointPolicy.ALWAYS
        )
        assert endpoint.default_policy is expected, endpoint.id
