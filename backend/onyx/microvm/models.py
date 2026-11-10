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
    # Steps that raised; the pass logged them and went on.
    failed: list[str] = Field(default_factory=list)
    refreshed: list[str] = Field(default_factory=list)
    adopted: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    orphans_marked: list[str] = Field(default_factory=list)
    orphans_stopped: list[str] = Field(default_factory=list)
    slept: list[str] = Field(default_factory=list)


# Node state report (agent → api_server, `POST /microvm/node/state`). The agent
# (microvm/internal/nodereport) applies the same caps before it sends.
NODE_REPORT_MAX_BODY_BYTES = 1 << 20
NODE_REPORT_MAX_VMS = 1024


class ReportedVm(BaseModel):
    """One VM of the agent's `List`, as the agent reports it."""

    model_config = ConfigDict(frozen=True)

    sandbox_id: str = Field(min_length=1, max_length=64)
    # Empty or not a tenant of this deployment: the pass skips the VM.
    tenant_id: str = Field(max_length=128, pattern=r"^[A-Za-z0-9_-]*$")
    attempt: int = Field(ge=0)
    generation: int = Field(ge=0)
    state: VmState
    template: str = Field(max_length=256)
    vcpus: int = Field(ge=0)
    mem_mib: int = Field(ge=0)
    scratch_gib: int = Field(ge=0)
    pid: int = Field(ge=0)
    started_at: datetime | None = None

    def to_agent_vm(self) -> AgentVm:
        return AgentVm(
            sandbox_id=self.sandbox_id,
            attempt=self.attempt,
            generation=self.generation,
            template=self.template,
            vcpus=self.vcpus,
            mem_mib=self.mem_mib,
            scratch_gib=self.scratch_gib,
            state=self.state,
            pid=self.pid,
            tenant_id=self.tenant_id,
            started_at=self.started_at,
        )


class NodeStateReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str = Field(min_length=1, max_length=253)
    vms: list[ReportedVm] = Field(max_length=NODE_REPORT_MAX_VMS)


class NodeStateReportResult(BaseModel):
    # False when another replica is reconciling this node, or the pass ran
    # out of time; the next report runs it again.
    reconciled: bool
    report: ReconcileReport | None = None
