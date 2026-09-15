"""Unit tests for catalog action effects.

The effect kind decides which actions leave receipts, so the catalog
declarations and the persisted-JSONB compatibility default are load-bearing.
"""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from onyx.db.enums import ActionEffect, ExternalAppType
from onyx.external_apps.matching.engine import apply_credential_gate

if TYPE_CHECKING:
    from onyx.db.models import ExternalApp
    from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.engine import MatchedAction
from onyx.external_apps.providers.registry import get_endpoint_catalog


def _effects(app_type: ExternalAppType) -> dict[str, ActionEffect]:
    return {spec.id.value: spec.effect for spec in get_endpoint_catalog(app_type)}


def test_slack_effects_follow_the_action_semantics() -> None:
    effects = _effects(ExternalAppType.SLACK)
    assert effects["slack.messages.write"] is ActionEffect.WRITE
    assert effects["slack.files.write"] is ActionEffect.WRITE
    assert effects["slack.dm.open"] is ActionEffect.WRITE
    assert effects["slack.messages.read"] is ActionEffect.READ
    assert effects["slack.search.read"] is ActionEffect.READ


def test_every_catalog_declares_write_actions() -> None:
    """Every resolvable catalog mixes reads and writes: an all-read or
    all-write catalog is a sign a declaration sweep went wrong."""
    for app_type in ExternalAppType:
        if app_type is ExternalAppType.CUSTOM:
            continue  # the one type without a code-owned catalog
        effects = {spec.effect for spec in get_endpoint_catalog(app_type)}
        assert effects == {ActionEffect.READ, ActionEffect.WRITE}, app_type


def test_whole_domain_fallback_counts_as_write() -> None:
    """An unmatched request under a connected app's domain has an unknown
    effect, so it must record as a write, never slip through as a read."""
    request = SimpleNamespace(method="POST", path="/anything")
    app = SimpleNamespace(app_type=ExternalAppType.CUSTOM, name="Custom", id=1)
    matched = apply_credential_gate(
        cast("ExternalApp", app),
        cast("ProxiedRequest", request),
        None,
        is_available=True,
    )
    assert matched is not None
    assert matched.governing_action.effect is ActionEffect.WRITE


def test_matched_action_defaults_read_for_persisted_rows() -> None:
    """Approval rows persisted before effects existed parse without the field."""
    parsed = MatchedAction.model_validate(
        {
            "action_type": "slack.messages.write",
            "display_name": "Post a message",
            "description": "Post a message.",
            "policy": "ASK",
        }
    )
    assert parsed.effect is ActionEffect.READ
