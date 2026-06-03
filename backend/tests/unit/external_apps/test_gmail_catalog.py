"""The Gmail provider catalog: every route resolves to exactly the intended
action (no collection/item/send cross-matching), and each action's
``default_policy`` matches the design (reads + draft create/update auto-approve;
draft delete/send require approval)."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.actions import path_matches
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.gmail import GmailAction
from onyx.external_apps.providers.registry import get_endpoint_catalog

_CATALOG = get_endpoint_catalog(ExternalAppType.GMAIL)


def _matching_actions(method: str, path: str) -> set[str]:
    """Every catalog action whose REST routes recognise (method, path)."""
    matched: set[str] = set()
    for endpoint in _CATALOG:
        for rule in endpoint.matches:
            assert isinstance(rule, RestRoute)  # Gmail is REST-only
            if rule.method == method and path_matches(rule.path, path):
                matched.add(endpoint.id)
                break
    return matched


@pytest.mark.parametrize(
    "method, path, expected",
    [
        # Drafts — collection, item, and the /send action stay distinct.
        ("GET", "/gmail/v1/users/me/drafts", {GmailAction.DRAFTS_READ}),
        ("GET", "/gmail/v1/users/me/drafts/r123", {GmailAction.DRAFTS_READ}),
        ("POST", "/gmail/v1/users/me/drafts", {GmailAction.DRAFTS_CREATE}),
        ("PUT", "/gmail/v1/users/me/drafts/r123", {GmailAction.DRAFTS_UPDATE}),
        ("DELETE", "/gmail/v1/users/me/drafts/r123", {GmailAction.DRAFTS_DELETE}),
        ("POST", "/gmail/v1/users/me/drafts/send", {GmailAction.DRAFTS_SEND}),
        # Threads — collection and item.
        ("GET", "/gmail/v1/users/me/threads", {GmailAction.THREADS_READ}),
        ("GET", "/gmail/v1/users/me/threads/t1", {GmailAction.THREADS_READ}),
        # Attachments.
        (
            "GET",
            "/gmail/v1/users/me/messages/m1/attachments/a1",
            {GmailAction.ATTACHMENTS_READ},
        ),
        # The pre-existing message routes still resolve unchanged.
        ("POST", "/gmail/v1/users/me/messages/send", {GmailAction.MESSAGES_SEND}),
        ("GET", "/gmail/v1/users/me/messages/m1", {GmailAction.MESSAGES_READ}),
    ],
)
def test_route_resolves_to_exactly_one_action(
    method: str, path: str, expected: set[str]
) -> None:
    assert _matching_actions(method, path) == expected


@pytest.mark.parametrize(
    "action, expected_policy",
    [
        (GmailAction.DRAFTS_READ, EndpointPolicy.ALWAYS),
        (GmailAction.DRAFTS_CREATE, EndpointPolicy.ALWAYS),
        (GmailAction.DRAFTS_UPDATE, EndpointPolicy.ALWAYS),
        (GmailAction.THREADS_READ, EndpointPolicy.ALWAYS),
        (GmailAction.ATTACHMENTS_READ, EndpointPolicy.ALWAYS),
        # Writes that delete or send real email require approval out of the box.
        (GmailAction.DRAFTS_DELETE, EndpointPolicy.ASK),
        (GmailAction.DRAFTS_SEND, EndpointPolicy.ASK),
    ],
)
def test_default_policies(action: GmailAction, expected_policy: EndpointPolicy) -> None:
    by_id = {endpoint.id: endpoint for endpoint in _CATALOG}
    assert by_id[action].default_policy == expected_policy
