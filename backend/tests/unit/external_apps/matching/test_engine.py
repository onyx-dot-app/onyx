"""Recognition uses provider catalogs without loading permission or credential state."""

import json

import pytest
from pydantic import ValidationError

from onyx.db.enums import ActionPolicy, ExternalAppType, IntegrationKind
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    recognize_actions,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.models import OTHER_REQUEST_ACTION_KEY
from onyx.integrations.models import ApiShape


def test_rejects_empty_actions() -> None:
    with pytest.raises(ValidationError, match="actions must be non-empty"):
        AllMatchedActions(
            actions=(),
            target=GatedTarget(
                integration_id=1,
                kind=IntegrationKind.API,
                app_name="X",
                api_shape=ApiShape.PRESET,
            ),
        )


@pytest.mark.parametrize(
    ("path", "action_id", "default"),
    [
        ("/api/conversations.list", "slack.channels.read", ActionPolicy.ALWAYS),
        ("/api/chat.postMessage", "slack.messages.write", ActionPolicy.ASK),
        ("/api/unknown", OTHER_REQUEST_ACTION_KEY, ActionPolicy.ASK),
    ],
)
def test_recognition_preserves_action_identity_and_catalog_default(
    path: str, action_id: str, default: ActionPolicy
) -> None:
    matched = recognize_actions(
        ExternalAppType.SLACK, ProxiedRequest(method="POST", path=path)
    )
    assert matched[0].action_type == action_id
    assert matched[0].policy == default


def test_custom_app_unknown_action_is_the_other_request_action() -> None:
    matched = recognize_actions(
        ExternalAppType.CUSTOM, ProxiedRequest(method="POST", path="/anything")
    )
    assert matched[0].action_type == OTHER_REQUEST_ACTION_KEY
    assert matched[0].policy == ActionPolicy.ASK


def _linear_actions(body: object) -> list[str]:
    matched = recognize_actions(
        ExternalAppType.LINEAR,
        ProxiedRequest(method="POST", path="/graphql", body=json.dumps(body).encode()),
    )
    return [action.action_type for action in matched]


@pytest.mark.parametrize(
    "body",
    [
        {
            "query": 'query A { viewer { id } } mutation B { issueDelete(id: "x") { success } }'
        },
        {"query": "{ viewer { id } organization { id } }"},
        [
            {"query": "{ viewer { id } }"},
            {"query": 'mutation { issueDelete(id: "x") { success } }'},
        ],
        [
            {"query": "{ viewer { id } }"},
            {"extensions": {"persistedQuery": {"sha256Hash": "abc"}}},
        ],
        [{"query": "{ viewer { id } }"}, {"query": "mutation {"}],
    ],
    ids=[
        "two_operations",
        "two_root_fields",
        "batch",
        "batch_with_persisted_query",
        "batch_with_unreadable_document",
    ],
)
def test_unknown_graphql_field_next_to_a_known_one_asks(body: object) -> None:
    actions = _linear_actions(body)
    assert actions[0] == OTHER_REQUEST_ACTION_KEY
    assert "linear.viewer.read" in actions


def test_known_graphql_fields_of_one_action_do_not_ask() -> None:
    actions = _linear_actions(
        {"query": '{ issues { nodes { id } } issue(id: "x") { id } }'}
    )
    assert actions == ["linear.issues.read"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", "/repos/o/r/issues/comments/1"),
        ("POST", "/repos/o/r/issues/comments/1"),
        ("GET", "/graphql"),
    ],
)
def test_a_graphql_body_matches_only_a_post_to_the_graphql_endpoint(
    method: str, path: str
) -> None:
    matched = recognize_actions(
        ExternalAppType.GITHUB,
        ProxiedRequest(
            method=method,
            path=path,
            body=json.dumps({"query": "{ viewer { id } }"}).encode(),
        ),
    )
    assert [action.action_type for action in matched] == [WHOLE_DOMAIN_ACTION_TYPE]


def test_a_query_string_keeps_the_graphql_endpoint() -> None:
    matched = recognize_actions(
        ExternalAppType.LINEAR,
        ProxiedRequest(
            method="POST",
            path="/graphql?tenant=acme",
            body=json.dumps({"query": "{ viewer { id } }"}).encode(),
        ),
    )
    assert [action.action_type for action in matched] == ["linear.viewer.read"]
