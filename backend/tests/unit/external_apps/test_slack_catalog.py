"""The Slack provider catalog: REST routes resolve to exactly the intended
action, and default policies match the design (reads auto-approve; message and
file writes require approval).

Exercises the pure rule layer directly, mirroring ``test_github_catalog``."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.external_apps.providers.slack import SlackAction
from onyx.external_apps.providers.slack import SlackProvider

_CATALOG = get_endpoint_catalog(ExternalAppType.SLACK)


def _matching_actions(method: str, path: str) -> set[str]:
    context = MatchContext(ProxiedRequest(method=method, path=path, body=None))
    return {
        endpoint.id
        for endpoint in _CATALOG
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    }


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("POST", "/api/conversations.list", {SlackAction.CHANNELS_READ}),
        ("POST", "/api/conversations.info", {SlackAction.CHANNELS_READ}),
        ("POST", "/api/conversations.history", {SlackAction.MESSAGES_READ}),
        ("POST", "/api/conversations.replies", {SlackAction.MESSAGES_READ}),
        ("POST", "/api/users.list", {SlackAction.USERS_READ}),
        ("POST", "/api/users.info", {SlackAction.USERS_READ}),
        ("POST", "/api/search.messages", {SlackAction.SEARCH_READ}),
        ("POST", "/api/chat.postMessage", {SlackAction.MESSAGES_WRITE}),
        ("POST", "/api/conversations.open", {SlackAction.DM_OPEN}),
        ("GET", "/api/files.getUploadURLExternal", {SlackAction.FILES_WRITE}),
        ("POST", "/api/files.getUploadURLExternal", {SlackAction.FILES_WRITE}),
        ("POST", "/api/files.completeUploadExternal", {SlackAction.FILES_WRITE}),
        # The raw-bytes POST to the pre-signed files.slack.com upload URL must
        # fall under FILES_WRITE, not the whole-domain "Perform action" fallback.
        ("POST", "/upload/v1/CwABgAB123", {SlackAction.FILES_WRITE}),
    ],
)
def test_rest_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (SlackAction.CHANNELS_READ, EndpointPolicy.ALWAYS),
        (SlackAction.MESSAGES_READ, EndpointPolicy.ALWAYS),
        (SlackAction.USERS_READ, EndpointPolicy.ALWAYS),
        (SlackAction.SEARCH_READ, EndpointPolicy.ALWAYS),
        (SlackAction.MESSAGES_WRITE, EndpointPolicy.ASK),
        (SlackAction.DM_OPEN, EndpointPolicy.ASK),
        (SlackAction.FILES_WRITE, EndpointPolicy.ASK),
    ],
)
def test_default_policies(action: SlackAction, expected_policy: EndpointPolicy) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy


def test_files_write_scope_and_upstream_pattern() -> None:
    spec = SlackProvider.spec
    assert "files:write" in spec.oauth.scope.split(",")
    assert (
        "https://files\\.slack\\.com/upload/v1/.*"
        in spec.descriptor.upstream_url_patterns
    )
