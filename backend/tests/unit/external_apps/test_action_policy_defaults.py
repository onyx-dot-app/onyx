"""Per-action ``default_policy`` on ``EndpointSpec``.

A provider declares the out-of-the-box policy for each catalog action (defaults
to ``ASK``).
"""

from __future__ import annotations

from onyx.db.enums import ActionPolicy
from onyx.external_apps.providers.actions import (
    EndpointSpec,
    ExternalAppAction,
    RestRoute,
)


class _TestAction(ExternalAppAction):
    READ = "test.read"
    WRITE = "test.write"


def _spec(
    action: _TestAction, default_policy: ActionPolicy | None = None
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
    assert _spec(_TestAction.READ).default_policy == ActionPolicy.ASK


def test_endpoint_spec_accepts_override() -> None:
    spec = _spec(_TestAction.WRITE, ActionPolicy.ALWAYS)
    assert spec.default_policy == ActionPolicy.ALWAYS
