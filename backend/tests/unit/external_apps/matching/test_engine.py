"""Pure unit tests for the matching engine. The DB-driven ``recognize_actions``
path is covered in ``external_dependency_unit/craft/test_action_matching.py``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.external_apps.matching.engine import apply_credential_gate
from onyx.external_apps.matching.engine import MatchedAction
from onyx.external_apps.matching.engine import WHOLE_DOMAIN_ACTION_TYPE
from onyx.external_apps.matching.request import ProxiedRequest


def test_rejects_empty_actions() -> None:
    """An AllMatchedActions with no actions is a programmer error — every gate
    consumer reads ``actions[0]``."""
    with pytest.raises(ValidationError, match="actions must be non-empty"):
        AllMatchedActions(actions=(), app_name="X", external_app_id=1)


# ── apply_credential_gate: the pure credential/synthesize fork ─────────


def _app(app_type: ExternalAppType = ExternalAppType.SLACK) -> ExternalApp:
    app = ExternalApp(app_type=app_type)
    app.id = 1
    return app


def _request() -> ProxiedRequest:
    return ProxiedRequest(method="POST", path="/api/x")


def _matched_actions(*policies: EndpointPolicy) -> AllMatchedActions:
    return AllMatchedActions(
        actions=tuple(
            MatchedAction(
                action_type=f"a{i}", display_name="A", description="d", policy=p
            )
            for i, p in enumerate(policies)
        ),
        app_name="Slack",
        external_app_id=1,
    )


def test_apply_gate_serveable_passes_recognition_through() -> None:
    matched_actions = _matched_actions(EndpointPolicy.ALWAYS)
    assert (
        apply_credential_gate(_app(), _request(), matched_actions, is_available=True)
        is matched_actions
    )


def test_apply_gate_serveable_no_catalog_synthesizes_whole_domain_ask() -> None:
    matched_actions = apply_credential_gate(_app(), _request(), None, is_available=True)
    assert matched_actions is not None
    assert matched_actions.governing_action.action_type == WHOLE_DOMAIN_ACTION_TYPE
    assert matched_actions.governing_action.policy == EndpointPolicy.ASK
    assert matched_actions.app_name == "Slack"
    assert matched_actions.external_app_id == 1


def test_apply_gate_not_serveable_no_catalog_forwards_bare() -> None:
    assert apply_credential_gate(_app(), _request(), None, is_available=False) is None


def test_apply_gate_not_serveable_without_deny_forwards_bare() -> None:
    matched_actions = _matched_actions(EndpointPolicy.ALWAYS, EndpointPolicy.ASK)
    assert (
        apply_credential_gate(_app(), _request(), matched_actions, is_available=False)
        is None
    )


def test_apply_gate_not_serveable_keeps_only_deny() -> None:
    matched_actions = _matched_actions(EndpointPolicy.DENY, EndpointPolicy.ASK)
    gated = apply_credential_gate(
        _app(), _request(), matched_actions, is_available=False
    )
    assert gated is not None
    assert [a.policy for a in gated.actions] == [EndpointPolicy.DENY]
