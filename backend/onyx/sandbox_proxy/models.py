"""Shared data models for the sandbox egress proxy."""

import ipaddress
from enum import Enum

from pydantic import BaseModel, ConfigDict

from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class DestinationPolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_host: str | None
    api_port: int | None
    internal_networks: tuple[IPNetwork, ...]


class InjectionContext(BaseModel):
    """Per-request inputs every resolver receives.

    `matched_actions` is the actions matched for this request (carrying
    `external_app_id`), or `None` on off-catalog forwards. `sandbox.tenant_id` is
    what resolvers key their per-tenant lookups by.
    """

    model_config = ConfigDict(frozen=True)

    sandbox: ResolvedSandbox
    matched_actions: AllMatchedActions | None


class InjectionOutcome(Enum):
    PASS_THROUGH = "pass_through"
    CLAIMED = "claimed"
    INJECTED = "injected"
    BLOCKED = "blocked"


class InjectionResult(BaseModel):
    """Outcome of one dispatch. `block_detail` is agent-facing prose for the
    403 body, present only on BLOCKED when the resolver supplied one."""

    model_config = ConfigDict(frozen=True)

    outcome: InjectionOutcome
    block_detail: str | None = None


class McpRpcKind(str, Enum):
    PLUMBING = "PLUMBING"  # forward ungated (creds injected)
    TOOL_CALL = "TOOL_CALL"  # gate per tool name
    UNCLASSIFIABLE = "UNCLASSIFIABLE"  # fail closed — deny


class McpRpcClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: McpRpcKind
    # Tool names of every `tools/call` in the (possibly batched) body, in order.
    tool_names: tuple[str, ...] = ()
