"""Data models of the Firecracker runtime (`SANDBOX_RUNTIME=firecracker`)."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class RegisteredNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    # host:port of the agent's mTLS listener.
    address: str


class IndexedPlacement(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    sandbox_id: UUID


class VmState(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    EXITED = "EXITED"

    def is_live(self) -> bool:
        """The VM holds resources (and its session files) on the node."""
        return self in (VmState.STARTING, VmState.RUNNING)


class AgentVm(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    attempt: int
    # Host-side boot ID of this VM instance (ENG-4606).
    generation: int
    template: str
    vcpus: int
    mem_mib: int
    scratch_gib: int
    state: VmState
    pid: int
    tenant_id: str
    started_at: datetime | None


class TemplateInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    vcpus: int
    mem_mib: int
    scratch_gib: int
    guest_kernel: str
    firecracker_version: str


class NodeInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    mem_total_mib: int
    mem_available_mib: int
    vm_count: int
    templates: list[TemplateInfo]
    cpu_model: str
    firecracker_version: str
    host_kernel: str
    agent_version: str
    disk_free_mib: int

    def template(self, version: str) -> TemplateInfo | None:
        return next((t for t in self.templates if t.version == version), None)


class CreateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    vm: AgentVm
    # False when the agent returned an existing VM for the same attempt.
    created: bool


class DaemonHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    initialized: bool
    key_set: bool
    version: str
    generation: int
    sandbox_id: str
    running_executions: int


class DaemonInitResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    clock_step_seconds: float
    entropy_credited: bool
    attached: bool
    relay_reset: bool


class VmRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    sandbox_id: UUID
    # The sandbox's provisioning attempt number (the existing attempt fence).
    attempt: int
    # Template version; vcpus and mem_mib come from the node's template.
    template: str
    # None = the template's scratch size.
    scratch_gib: int | None = None


class PlacedVm(BaseModel):
    model_config = ConfigDict(frozen=True)

    node: RegisteredNode
    vm: AgentVm
    # False when the VM existed before this call.
    created: bool
    # The guest daemon key of vm.attempt (x-sandboxd-key). Never log it.
    sandboxd_key: SecretStr


class NodeRefusal(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    reason: str
    detail: str


class ReconcileReport(BaseModel):
    nodes: int = 0
    unreachable_nodes: list[str] = Field(default_factory=list)
    # Steps that raised; the pass logged them and went on.
    failed: list[str] = Field(default_factory=list)
    refreshed: list[str] = Field(default_factory=list)
    adopted: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    orphans_marked: list[str] = Field(default_factory=list)
    orphans_stopped: list[str] = Field(default_factory=list)
    slept: list[str] = Field(default_factory=list)
