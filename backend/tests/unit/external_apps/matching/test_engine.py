"""Recognition uses provider catalogs without loading permission or credential state."""

import pytest
from pydantic import ValidationError

from onyx.db.enums import ActionPolicy, ExternalAppType, IntegrationKind
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
    app = ExternalApp(id=1, name="Slack", app_type=ExternalAppType.SLACK)
    matched = recognize_actions(app, ProxiedRequest(method="POST", path=path))
    assert matched[0].action_type == action_id
    assert matched[0].policy == default


def test_custom_app_unknown_action_is_the_whole_domain_action() -> None:
    app = ExternalApp(id=2, name="Customer CRM", app_type=ExternalAppType.CUSTOM)
    matched = recognize_actions(app, ProxiedRequest(method="POST", path="/anything"))
    assert matched[0].action_type == WHOLE_DOMAIN_ACTION_TYPE
    assert matched[0].policy == ActionPolicy.ASK
