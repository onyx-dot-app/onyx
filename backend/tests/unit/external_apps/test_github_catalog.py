"""The GitHub provider catalog: REST routes and the `gh` CLI's GraphQL
operations resolve to exactly the intended action, and default policies match
the design (reads auto-approve; issue/comment writes require approval).

The DB-driven ``recognize_actions`` path is covered in
``external_dependency_unit/craft/test_action_matching.py``; here we exercise the
pure rule layer (including GraphQL body parsing) directly."""

from __future__ import annotations

import json

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.github import GitHubAction
from onyx.external_apps.providers.registry import get_endpoint_catalog

_CATALOG = get_endpoint_catalog(ExternalAppType.GITHUB)


def _matching_actions(method: str, path: str, body: bytes | None = None) -> set[str]:
    """Every catalog action whose rules recognise the request — through the real
    matcher, so GraphQL bodies are parsed exactly as the proxy parses them."""
    context = MatchContext(ProxiedRequest(method=method, path=path, body=body))
    return {
        endpoint.id
        for endpoint in _CATALOG
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    }


def _graphql(query: str) -> bytes:
    return json.dumps({"query": query}).encode("utf-8")


@pytest.mark.parametrize(
    "method, path, expected",
    [
        # REST routes resolve unchanged.
        ("GET", "/user", {GitHubAction.USER_READ}),
        ("GET", "/user/repos", {GitHubAction.REPOS_READ}),
        ("GET", "/repos/onyx/onyx", {GitHubAction.REPOS_READ}),
        ("GET", "/repos/onyx/onyx/issues", {GitHubAction.ISSUES_READ}),
        ("GET", "/repos/onyx/onyx/issues/12", {GitHubAction.ISSUES_READ}),
        ("GET", "/repos/onyx/onyx/pulls", {GitHubAction.PULLS_READ}),
        ("GET", "/search/issues", {GitHubAction.SEARCH_READ}),
        ("POST", "/repos/onyx/onyx/issues", {GitHubAction.ISSUES_CREATE}),
        (
            "POST",
            "/repos/onyx/onyx/issues/12/comments",
            {GitHubAction.COMMENTS_CREATE},
        ),
        # Git data + repo content surface (the gh / API-driven workflows).
        ("GET", "/repos/onyx/onyx/branches", {GitHubAction.REFS_READ}),
        # Slash-bearing ref / branch names via the trailing wildcard.
        ("GET", "/repos/onyx/onyx/branches/feature/x", {GitHubAction.REFS_READ}),
        ("GET", "/repos/onyx/onyx/git/ref/heads/main", {GitHubAction.REFS_READ}),
        (
            "GET",
            "/repos/onyx/onyx/contents/backend/onyx/main.py",
            {GitHubAction.CONTENTS_READ},
        ),
        ("GET", "/repos/onyx/onyx/git/trees/abc123", {GitHubAction.GIT_DATA_READ}),
        ("GET", "/repos/onyx/onyx/commits", {GitHubAction.GIT_DATA_READ}),
        ("GET", "/repos/onyx/onyx/commits/abc123", {GitHubAction.GIT_DATA_READ}),
        ("GET", "/repos/onyx/onyx/releases", {GitHubAction.RELEASES_READ}),
        ("GET", "/repos/onyx/onyx/releases/latest", {GitHubAction.RELEASES_READ}),
        # Writes.
        (
            "PUT",
            "/repos/onyx/onyx/contents/backend/onyx/main.py",
            {GitHubAction.CONTENTS_WRITE},
        ),
        (
            "DELETE",
            "/repos/onyx/onyx/contents/backend/onyx/main.py",
            {GitHubAction.CONTENTS_WRITE},
        ),
        ("POST", "/repos/onyx/onyx/git/refs", {GitHubAction.REFS_WRITE}),
        ("POST", "/repos/onyx/onyx/pulls", {GitHubAction.PULLS_CREATE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


@pytest.mark.parametrize(
    "query, expected",
    [
        # gh resolves the current user via `viewer`.
        ("query { viewer { login } }", {GitHubAction.USER_READ}),
        # gh repo/pr/issue view+list all read through the `repository` root field.
        (
            "query($o:String!,$r:String!){ repository(owner:$o, name:$r)"
            " { pullRequests(first:30) { nodes { number } } } }",
            {GitHubAction.REPO_GRAPHQL_READ},
        ),
        (
            'query { repository(owner:"onyx", name:"onyx")'
            " { issue(number:12) { title } } }",
            {GitHubAction.REPO_GRAPHQL_READ},
        ),
        # GraphQL search backs `gh search` / status views.
        (
            'query { search(query:"x", type:ISSUE, first:5) { issueCount } }',
            {GitHubAction.SEARCH_READ},
        ),
        # Writes may go out as GraphQL mutations.
        (
            'mutation { createIssue(input:{repositoryId:"x", title:"t"})'
            " { issue { number } } }",
            {GitHubAction.ISSUES_CREATE},
        ),
        (
            'mutation { addComment(input:{subjectId:"x", body:"b"})'
            " { clientMutationId } }",
            {GitHubAction.COMMENTS_CREATE},
        ),
        # `gh repo list OWNER` reads via `repositoryOwner`.
        (
            'query { repositoryOwner(login:"onyx") { login } }',
            {GitHubAction.REPO_GRAPHQL_READ},
        ),
        # `gh pr create` may use the `createPullRequest` mutation.
        (
            "mutation { createPullRequest(input:{}) { pullRequest { number } } }",
            {GitHubAction.PULLS_CREATE},
        ),
    ],
)
def test_graphql_op_resolves_to_exactly_one_action(
    query: str, expected: set[str]
) -> None:
    assert _matching_actions("POST", "/graphql", _graphql(query)) == expected


def test_uncatalogued_graphql_op_matches_nothing() -> None:
    """A root field outside the catalog matches no action — the proxy then falls
    back to the whole-domain ASK gate rather than injecting under a catalog action."""
    query = 'query { organization(login:"onyx") { login } }'
    assert _matching_actions("POST", "/graphql", _graphql(query)) == set()


def test_rest_request_does_not_trigger_graphql_match() -> None:
    """A plain REST GET (no body) must not match any GraphQLOp rule."""
    assert _matching_actions("GET", "/user") == {GitHubAction.USER_READ}


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (GitHubAction.USER_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.REPOS_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.ISSUES_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.PULLS_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.SEARCH_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.REPO_GRAPHQL_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.REFS_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.CONTENTS_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.GIT_DATA_READ, EndpointPolicy.ALWAYS),
        (GitHubAction.RELEASES_READ, EndpointPolicy.ALWAYS),
        # Writes require approval out of the box.
        (GitHubAction.ISSUES_CREATE, EndpointPolicy.ASK),
        (GitHubAction.COMMENTS_CREATE, EndpointPolicy.ASK),
        (GitHubAction.CONTENTS_WRITE, EndpointPolicy.ASK),
        (GitHubAction.REFS_WRITE, EndpointPolicy.ASK),
        (GitHubAction.PULLS_CREATE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(
    action: GitHubAction, expected_policy: EndpointPolicy
) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
