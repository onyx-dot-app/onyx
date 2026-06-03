"""Per-action ``default_policy`` on ``EndpointSpec`` and how the registry seeds it.

A provider can declare the out-of-the-box policy for each catalog action; the
create flow (and the policy views) seed from it, defaulting to ``ASK``.
"""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers import registry
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import RestRoute


class _TestAction(ExternalAppAction):
    READ = "test.read"
    WRITE = "test.write"


def _spec(
    action: _TestAction, default_policy: EndpointPolicy | None = None
) -> EndpointSpec:
    kwargs = {} if default_policy is None else {"default_policy": default_policy}
    return EndpointSpec(
        id=action,
        normalised_name=action.value,
        description="d",
        matches=(RestRoute(method="GET", path="/x"),),
        **kwargs,
    )


def test_endpoint_spec_defaults_to_ask() -> None:
    assert _spec(_TestAction.READ).default_policy == EndpointPolicy.ASK


def test_endpoint_spec_accepts_override() -> None:
    spec = _spec(_TestAction.WRITE, EndpointPolicy.ALWAYS)
    assert spec.default_policy == EndpointPolicy.ALWAYS


def test_build_action_policies_seeds_from_each_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No requested/stored values → each action falls back to its own
    ``default_policy``, not a blanket ASK."""
    catalog = [
        _spec(_TestAction.READ, EndpointPolicy.ALWAYS),
        _spec(_TestAction.WRITE),  # omitted → ASK
    ]
    monkeypatch.setattr(registry, "get_endpoint_catalog", lambda _app_type: catalog)

    built = registry.build_action_policies(
        ExternalAppType.SLACK, requested=None, existing={}
    )
    assert built[_TestAction.READ] == EndpointPolicy.ALWAYS
    assert built[_TestAction.WRITE] == EndpointPolicy.ASK


def test_build_action_policies_override_and_existing_win_over_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = [
        _spec(_TestAction.READ, EndpointPolicy.ALWAYS),
        _spec(_TestAction.WRITE, EndpointPolicy.ALWAYS),
    ]
    monkeypatch.setattr(registry, "get_endpoint_catalog", lambda _app_type: catalog)

    built = registry.build_action_policies(
        ExternalAppType.SLACK,
        requested={"test.read": EndpointPolicy.DENY},
        existing={"test.write": EndpointPolicy.ASK},
    )
    # admin override wins; else stored value wins; default only fills the gaps.
    assert built[_TestAction.READ] == EndpointPolicy.DENY
    assert built[_TestAction.WRITE] == EndpointPolicy.ASK


def test_action_policy_views_seed_from_each_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = [
        _spec(_TestAction.READ, EndpointPolicy.ALWAYS),
        _spec(_TestAction.WRITE),  # omitted → ASK
    ]
    monkeypatch.setattr(registry, "get_endpoint_catalog", lambda _app_type: catalog)

    states = {
        v.action_id: v.state
        for v in registry.action_policy_views(ExternalAppType.SLACK, stored={})
    }
    assert states[_TestAction.READ] == EndpointPolicy.ALWAYS
    assert states[_TestAction.WRITE] == EndpointPolicy.ASK
