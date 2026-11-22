"""Recognition uses provider catalogs without loading permission or credential state."""

import json

import pytest
from pydantic import ValidationError

from onyx.db.enums import ActionPolicy, ExternalAppType, IntegrationKind
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    AllMatchedActions,
    GatedTarget,
    recognize_actions,
)
from onyx.external_apps.matching.request import ProxiedRequest


def test_rejects_empty_actions() -> None:
    with pytest.raises(ValidationError, match="actions must be non-empty"):
        AllMatchedActions(
            actions=(),
            target=GatedTarget(
                integration_id=1, kind=IntegrationKind.API, app_name="X"
            ),
        )


@pytest.mark.parametrize(
    ("path", "action_id", "default"),
    [
        ("/api/conversations.list", "slack.channels.read", ActionPolicy.ALWAYS),
        ("/api/chat.postMessage", "slack.messages.write", ActionPolicy.ASK),
        ("/api/unknown", WHOLE_DOMAIN_ACTION_TYPE, ActionPolicy.ASK),
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


def test_custom_app_unknown_action_is_the_whole_domain_action() -> None:
    matched = recognize_actions(
        ExternalAppType.CUSTOM, ProxiedRequest(method="POST", path="/anything")
    )
    assert matched[0].action_type == WHOLE_DOMAIN_ACTION_TYPE
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
    ],
    ids=["two_operations", "two_root_fields", "batch"],
)
def test_unknown_graphql_field_next_to_a_known_one_asks(body: object) -> None:
    actions = _linear_actions(body)
    assert actions[0] == WHOLE_DOMAIN_ACTION_TYPE
    assert "linear.viewer.read" in actions


def test_known_graphql_fields_of_one_action_do_not_ask() -> None:
    actions = _linear_actions(
        {"query": '{ issues { nodes { id } } issue(id: "x") { id } }'}
    )
    assert actions == ["linear.issues.read"]
