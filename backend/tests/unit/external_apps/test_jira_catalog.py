"""The Jira (Atlassian Cloud) provider catalog: REST routes resolve to exactly
the intended action, and default policies match the design (reads + JQL search
auto-approve; issue create/update/transition and comment writes require
approval).

Here we exercise the pure rule layer directly (the DB-driven
``recognize_actions`` path is covered elsewhere), mirroring
``test_notion_catalog.py``."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.jira import JiraAction
from onyx.external_apps.providers.registry import get_endpoint_catalog

_CATALOG = get_endpoint_catalog(ExternalAppType.JIRA)

# A real-looking Atlassian cloud id (a UUID) — the `{cloud_id}` placeholder is a
# normal single-segment match, so the exact value is irrelevant to routing.
_CLOUD = "11223344-5566-7788-99aa-bbccddeeff00"
_API = f"/ex/jira/{_CLOUD}/rest/api/3"


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
        # Site discovery lives off the /ex/jira tree, at the token endpoint.
        (
            "GET",
            "/oauth/token/accessible-resources",
            {JiraAction.ACCESSIBLE_RESOURCES},
        ),
        ("GET", f"{_API}/myself", {JiraAction.MYSELF}),
        # Projects — list vs project search both resolve to PROJECTS_READ.
        ("GET", f"{_API}/project", {JiraAction.PROJECTS_READ}),
        ("GET", f"{_API}/project/search", {JiraAction.PROJECTS_READ}),
        # JQL search is a read offered as both GET and POST; the POST must not
        # collide with the issue-create POST on the bare /issue path.
        ("GET", f"{_API}/search", {JiraAction.ISSUE_SEARCH}),
        ("POST", f"{_API}/search", {JiraAction.ISSUE_SEARCH}),
        # A single issue by id or key.
        ("GET", f"{_API}/issue/ENG-4287", {JiraAction.ISSUE_READ}),
        ("GET", f"{_API}/issue/10042", {JiraAction.ISSUE_READ}),
        (
            "GET",
            f"{_API}/issue/ENG-4287/transitions",
            {JiraAction.ISSUE_TRANSITIONS_READ},
        ),
        # Writes.
        ("POST", f"{_API}/issue", {JiraAction.ISSUE_CREATE}),
        ("PUT", f"{_API}/issue/ENG-4287", {JiraAction.ISSUE_UPDATE}),
        (
            "POST",
            f"{_API}/issue/ENG-4287/transitions",
            {JiraAction.ISSUE_TRANSITION},
        ),
        ("POST", f"{_API}/issue/ENG-4287/comment", {JiraAction.COMMENT_CREATE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


def test_search_post_and_issue_create_do_not_collide() -> None:
    """POST on /search (a JQL read) vs POST on /issue (a create write) must be
    distinct actions, so search stays auto-approved while creating an issue
    still asks."""
    assert _matching_actions("POST", f"{_API}/search") == {JiraAction.ISSUE_SEARCH}
    assert _matching_actions("POST", f"{_API}/issue") == {JiraAction.ISSUE_CREATE}


def test_issue_read_and_transitions_read_do_not_collide() -> None:
    """GET on an issue vs GET on its transitions must be different actions, so an
    admin can allow reading transitions independently."""
    assert _matching_actions("GET", f"{_API}/issue/ENG-1") == {JiraAction.ISSUE_READ}
    assert _matching_actions("GET", f"{_API}/issue/ENG-1/transitions") == {
        JiraAction.ISSUE_TRANSITIONS_READ
    }


def test_uncatalogued_route_matches_nothing() -> None:
    """A path outside the catalog matches no action — the proxy then falls back
    to the whole-domain ASK gate rather than injecting under a catalog action."""
    assert _matching_actions("DELETE", f"{_API}/issue/ENG-4287") == set()


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (JiraAction.ACCESSIBLE_RESOURCES, EndpointPolicy.ALWAYS),
        (JiraAction.MYSELF, EndpointPolicy.ALWAYS),
        (JiraAction.PROJECTS_READ, EndpointPolicy.ALWAYS),
        (JiraAction.ISSUE_SEARCH, EndpointPolicy.ALWAYS),
        (JiraAction.ISSUE_READ, EndpointPolicy.ALWAYS),
        (JiraAction.ISSUE_TRANSITIONS_READ, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (JiraAction.ISSUE_CREATE, EndpointPolicy.ASK),
        (JiraAction.ISSUE_UPDATE, EndpointPolicy.ASK),
        (JiraAction.ISSUE_TRANSITION, EndpointPolicy.ASK),
        (JiraAction.COMMENT_CREATE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(
    action: JiraAction, expected_policy: EndpointPolicy
) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
