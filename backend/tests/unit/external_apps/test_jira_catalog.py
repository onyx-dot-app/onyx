"""The Jira provider catalog: REST routes resolve to exactly the intended
action, and default policies match the design (site discovery, user reads,
project/issue/comment reads, and JQL search auto-approve; issue create / update
and comment create require approval).

Here we exercise the pure rule layer directly (the DB-driven
``recognize_actions`` path is covered elsewhere), mirroring
``test_confluence_catalog.py``, ``test_hubspot_catalog.py``, and
``test_notion_catalog.py``.

Paths use a real-looking Atlassian cloud id and realistic Jira issue ids/keys,
matching what the proxy actually sees after ``https://api.atlassian.com``."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.external_apps.matching.request import MatchContext, ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.jira import JiraAction
from onyx.external_apps.providers.registry import get_endpoint_catalog

_CATALOG = get_endpoint_catalog(ExternalAppType.JIRA)

# A real-looking Atlassian cloud id and the v3 Jira Cloud REST base.
_CLOUD_ID = "11111111-2222-3333-4444-555555555555"
_JIRA = f"/ex/jira/{_CLOUD_ID}/rest/api/3"


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
            {JiraAction.ACCESSIBLE_RESOURCES},
        ),
        # Reads.
        ("GET", f"{_JIRA}/myself", {JiraAction.MYSELF}),
        ("GET", f"{_JIRA}/project/search", {JiraAction.PROJECTS_READ}),
        # JQL search lives on the dedicated search endpoint, kept off the
        # `/issue/` path so it can't collide with an issue read.
        ("GET", f"{_JIRA}/search", {JiraAction.ISSUES_SEARCH}),
        ("GET", f"{_JIRA}/issue/12345", {JiraAction.ISSUE_READ}),
        ("GET", f"{_JIRA}/issue/PROJ-123", {JiraAction.ISSUE_READ}),
        ("GET", f"{_JIRA}/issue/12345/comment", {JiraAction.COMMENTS_READ}),
        # Writes.
        ("POST", f"{_JIRA}/issue", {JiraAction.ISSUE_CREATE}),
        ("PUT", f"{_JIRA}/issue/12345", {JiraAction.ISSUE_UPDATE}),
        ("POST", f"{_JIRA}/issue/12345/comment", {JiraAction.COMMENT_CREATE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


def test_search_and_issue_read_do_not_collide() -> None:
    """JQL search is catalogued under the bare ``.../search`` endpoint rather
    than anything under ``.../issue/``: the issue-read template
    ``.../issue/{issue_id_or_key}`` would otherwise swallow a literal ``search``
    segment (the matcher has no route precedence), double-matching the request.

    So the search route resolves to exactly the search action, a real issue id
    resolves to exactly the read action, and the two never overlap.
    """
    assert _matching_actions("GET", f"{_JIRA}/search") == {JiraAction.ISSUES_SEARCH}
    assert _matching_actions("GET", f"{_JIRA}/issue/12345") == {JiraAction.ISSUE_READ}


def test_issue_read_and_write_split_on_method() -> None:
    """Each verb is a distinct action so an admin can allow reads without
    allowing writes: the bare ``/issue`` path creates (POST); the id path reads
    (GET) vs updates (PUT); the comment path lists (GET) vs creates (POST)."""
    assert _matching_actions("POST", f"{_JIRA}/issue") == {JiraAction.ISSUE_CREATE}
    assert _matching_actions("GET", f"{_JIRA}/issue/12345") == {JiraAction.ISSUE_READ}
    assert _matching_actions("PUT", f"{_JIRA}/issue/12345") == {JiraAction.ISSUE_UPDATE}
    assert _matching_actions("GET", f"{_JIRA}/issue/12345/comment") == {
        JiraAction.COMMENTS_READ
    }
    assert _matching_actions("POST", f"{_JIRA}/issue/12345/comment") == {
        JiraAction.COMMENT_CREATE
    }


def test_uncatalogued_route_matches_nothing() -> None:
    """A path outside the catalog matches no action — the proxy then falls back
    to the whole-domain ASK gate rather than injecting under a catalog action."""
    assert _matching_actions("GET", f"{_JIRA}/longtask/123") == set()


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (JiraAction.ACCESSIBLE_RESOURCES, EndpointPolicy.ALWAYS),
        (JiraAction.MYSELF, EndpointPolicy.ALWAYS),
        (JiraAction.PROJECTS_READ, EndpointPolicy.ALWAYS),
        (JiraAction.ISSUES_SEARCH, EndpointPolicy.ALWAYS),
        (JiraAction.ISSUE_READ, EndpointPolicy.ALWAYS),
        (JiraAction.COMMENTS_READ, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (JiraAction.ISSUE_CREATE, EndpointPolicy.ASK),
        (JiraAction.ISSUE_UPDATE, EndpointPolicy.ASK),
        (JiraAction.COMMENT_CREATE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(action: JiraAction, expected_policy: EndpointPolicy) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
