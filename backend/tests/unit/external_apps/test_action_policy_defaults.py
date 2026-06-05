"""Per-action ``default_policy`` on ``EndpointSpec`` and how the registry uses it.

A provider declares the out-of-the-box policy for each catalog action (defaults
to ``ASK``). The write path persists only deviations from that default
(``resolve_action_overrides``); the policy views resolve missing rows back to it.
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


def test_resolve_overrides_persists_nothing_when_all_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No requested/stored values → no rows. Each action resolves to its
    ``default_policy`` at read time, so nothing is materialized."""
    catalog = [
        _spec(_TestAction.READ, EndpointPolicy.ALWAYS),
        _spec(_TestAction.WRITE),  # omitted → ASK
    ]
    monkeypatch.setattr(registry, "get_endpoint_catalog", lambda _app_type: catalog)

    assert (
        registry.resolve_action_overrides(
            ExternalAppType.SLACK, requested=None, existing={}
        )
        == {}
    )


def test_resolve_overrides_keeps_deviations_prunes_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only values differing from the catalog default survive: a requested pick
    equal to the default is pruned, one that differs is kept, and an existing
    override is preserved (merged under the request)."""
    catalog = [
        _spec(_TestAction.READ, EndpointPolicy.ALWAYS),
        _spec(_TestAction.WRITE, EndpointPolicy.ASK),
    ]
    monkeypatch.setattr(registry, "get_endpoint_catalog", lambda _app_type: catalog)

    resolved = registry.resolve_action_overrides(
        ExternalAppType.SLACK,
        # READ default is ALWAYS → DENY deviates (kept); setting it to ALWAYS
        # would prune.
        requested={"test.read": EndpointPolicy.DENY},
        existing={"test.write": EndpointPolicy.DENY},  # deviates from ASK → kept
    )
    assert resolved == {
        "test.read": EndpointPolicy.DENY,
        "test.write": EndpointPolicy.DENY,
    }


def test_resolve_overrides_prunes_request_equal_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = [_spec(_TestAction.READ, EndpointPolicy.ALWAYS)]
    monkeypatch.setattr(registry, "get_endpoint_catalog", lambda _app_type: catalog)

    resolved = registry.resolve_action_overrides(
        ExternalAppType.SLACK,
        requested={"test.read": EndpointPolicy.ALWAYS},  # == default → pruned
        existing={},
    )
    assert resolved == {}


def test_resolve_overrides_drops_orphan_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing override for an action no longer in the catalog is dropped
    on the next write (self-healing cleanup of orphaned rows)."""
    catalog = [_spec(_TestAction.READ, EndpointPolicy.ALWAYS)]
    monkeypatch.setattr(registry, "get_endpoint_catalog", lambda _app_type: catalog)

    resolved = registry.resolve_action_overrides(
        ExternalAppType.SLACK,
        requested=None,
        existing={"test.removed": EndpointPolicy.DENY},
    )
    assert resolved == {}


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
