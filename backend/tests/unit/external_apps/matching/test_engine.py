"""Recognition uses provider catalogs without loading permission or credential state."""

import pytest
from pydantic import ValidationError

from onyx.db.enums import ActionPolicy, ExternalAppType, GatedAppKind
from onyx.db.models import ExternalApp
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
            target=GatedTarget(kind=GatedAppKind.EXTERNAL_APP, id=1, app_name="X"),
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
    app = ExternalApp(id=1, name="Slack", app_type=ExternalAppType.SLACK)
    matched = recognize_actions(app, ProxiedRequest(method="POST", path=path))
    assert matched.target.key == (GatedAppKind.EXTERNAL_APP, app.id)
    assert matched.governing_action.action_type == action_id
    assert matched.governing_action.policy == default


def test_custom_app_unknown_action_preserves_display_name() -> None:
    app = ExternalApp(id=2, name="Customer CRM", app_type=ExternalAppType.CUSTOM)
    matched = recognize_actions(app, ProxiedRequest(method="POST", path="/anything"))
    assert matched.app_name == "Customer CRM"
    assert matched.governing_action.action_type == WHOLE_DOMAIN_ACTION_TYPE
    assert matched.governing_action.policy == ActionPolicy.ASK
