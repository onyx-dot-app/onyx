"""Shared data models for the sandbox egress proxy."""

import ipaddress
from enum import Enum

from pydantic import BaseModel, ConfigDict

from onyx.external_apps.matching.engine import AllMatchedActions, GatedTarget
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class DestinationPolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_host: str | None
    api_port: int | None
    internal_networks: tuple[IPNetwork, ...]


class InjectionContext(BaseModel):
    """Per-request inputs every resolver receives.

    `matched_actions` is the actions matched for this request, `protocol_target`
    the integration of an MCP protocol request, and both are `None` on
    unmatched forwards. `sandbox.tenant_id` is what resolvers key their
    per-tenant lookups by.
    """

    model_config = ConfigDict(frozen=True)

    sandbox: ResolvedSandbox
    matched_actions: AllMatchedActions | None
    protocol_target: GatedTarget | None = None

    @property
    def target(self) -> GatedTarget | None:
        if self.matched_actions is not None:
            return self.matched_actions.target
        return self.protocol_target


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


class McpProtocolRequest(BaseModel):
    """An attributed MCP protocol request without an action approval requirement."""

    model_config = ConfigDict(frozen=True)
    target: GatedTarget
