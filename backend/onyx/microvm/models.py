"""Data models of the Firecracker runtime (`SANDBOX_RUNTIME=firecracker`)."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class HostAgentErrorReason(str, Enum):
    """`ErrorReason` names from hostagent.proto."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TEMPLATE_MISSING = "TEMPLATE_MISSING"
    TEMPLATE_SHAPE_MISMATCH = "TEMPLATE_SHAPE_MISMATCH"
    TEMPLATE_INCOMPATIBLE = "TEMPLATE_INCOMPATIBLE"
    SCRATCH_TOO_SMALL = "SCRATCH_TOO_SMALL"
    SCRATCH_TOO_LARGE = "SCRATCH_TOO_LARGE"
    CAPACITY_MEMORY = "CAPACITY_MEMORY"
    CAPACITY_DISK = "CAPACITY_DISK"
    CAPACITY_VM_SLOTS = "CAPACITY_VM_SLOTS"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
    STALE_ATTEMPT = "STALE_ATTEMPT"
    SANDBOX_NOT_FOUND = "SANDBOX_NOT_FOUND"
    INSTANCE_MISMATCH = "INSTANCE_MISMATCH"
    VMM_FAILED = "VMM_FAILED"
    INTERNAL = "INTERNAL"
    SANDBOX_IN_DOUBT = "SANDBOX_IN_DOUBT"
    PORT_NOT_ALLOWED = "PORT_NOT_ALLOWED"
    GUEST_UNREACHABLE = "GUEST_UNREACHABLE"
    VM_NOT_RUNNING = "VM_NOT_RUNNING"
    DIAL_LIMIT = "DIAL_LIMIT"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    GUEST_KEY_REJECTED = "GUEST_KEY_REJECTED"
    MANAGED_IMAGE_MISSING = "MANAGED_IMAGE_MISSING"
    MANAGED_BUNDLE_INVALID = "MANAGED_BUNDLE_INVALID"
    MANAGED_SWAP_UNSUPPORTED = "MANAGED_SWAP_UNSUPPORTED"
    MANAGED_SLOT_BUSY = "MANAGED_SLOT_BUSY"
    MANAGED_MOUNT_FAILED = "MANAGED_MOUNT_FAILED"
    NODE_DRAINING = "NODE_DRAINING"
    EGRESS_CA_UNAVAILABLE = "EGRESS_CA_UNAVAILABLE"
    CAPTURE_NOT_FOUND = "CAPTURE_NOT_FOUND"
    CAPTURE_TOO_LARGE = "CAPTURE_TOO_LARGE"
    TRANSFER_FAILED = "TRANSFER_FAILED"
    ARCHIVE_MISMATCH = "ARCHIVE_MISMATCH"


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
    # Host-side boot ID of this VM instance.
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
    adopted: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    orphans_marked: list[str] = Field(default_factory=list)
    orphans_stopped: list[str] = Field(default_factory=list)
    # Idle past SANDBOX_FC_IDLE_TIMEOUT_SECONDS (the evictor's decision).
    idle: list[str] = Field(default_factory=list)
    slept: list[str] = Field(default_factory=list)


# Node state report (agent → api_server, `POST /microvm/node/state`). The agent
# (microvm/internal/nodereport) applies the same caps before it sends.
NODE_REPORT_MAX_BODY_BYTES = 1 << 20
NODE_REPORT_MAX_VMS = 1024
NODE_REPORT_MAX_ENDED = 1024


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


class EndedReason(str, Enum):
    # The VM process ended without a Stop (crash, guest power-off).
    EXITED = "EXITED"
    STOPPED = "STOPPED"


class ReportedEndedVm(BaseModel):
    """A VM instance that ended on the node within the agent's
    --ended-retention. The agent lists it in every report until then."""

    model_config = ConfigDict(frozen=True)

    sandbox_id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(max_length=128, pattern=r"^[A-Za-z0-9_-]*$")
    attempt: int = Field(ge=0)
    generation: int = Field(ge=0)
    reason: EndedReason
    ended_at: datetime


class NodeStateReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str = Field(min_length=1, max_length=253)
    vms: list[ReportedVm] = Field(max_length=NODE_REPORT_MAX_VMS)
    ended: list[ReportedEndedVm] = Field(
        default_factory=list, max_length=NODE_REPORT_MAX_ENDED
    )


class NodeStateReportResult(BaseModel):
    # False when another replica is reconciling this node, or the pass ran
    # out of time; the next report runs it again.
    reconciled: bool
    report: ReconcileReport | None = None


# Guest daemon exec calls (sandboxd Run/Start/Stream/Interact/Cancel/List).


class ExecCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    # argv[0] is looked up in PATH. For a script use ["bash", "-c", script].
    argv: list[str] = Field(min_length=1)
    # Default "/".
    cwd: str = ""
    # Added to the Init env.
    env: dict[str, str] = Field(default_factory=dict)
    # Open a stdin pipe for Interact. Otherwise stdin is /dev/null.
    stdin: bool = False
    # None = the daemon default (30 min); the daemon caps it.
    deadline_seconds: float | None = Field(default=None, gt=0)
    labels: dict[str, str] = Field(default_factory=dict)


class OutputStream(str, Enum):
    STDOUT = "STDOUT"
    STDERR = "STDERR"


class ExecCompletion(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    EXITED = "EXITED"
    # A signal that the daemon did not send (for example the OOM killer).
    SIGNALED = "SIGNALED"
    CANCELED = "CANCELED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


class ExecStarted(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_id: str
    pid: int
    started_at: datetime | None
    deadline_at: datetime | None


class ExecOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    stream: OutputStream
    # Byte offset of data[0] in this stream (the Stream resume point).
    offset: int
    data: bytes


class ExecGap(BaseModel):
    """The daemon dropped the bytes [start, end) of a stream."""

    model_config = ConfigDict(frozen=True)

    stream: OutputStream
    start: int
    end: int


class ExecResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    completion: ExecCompletion
    # Set for EXITED, -1 otherwise.
    exit_code: int
    signal: int
    finished_at: datetime | None
    stdout_bytes: int
    stderr_bytes: int


# The last event of a Run or Stream is always an ExecResult.
ExecEvent = ExecStarted | ExecOutput | ExecGap | ExecResult


class ExecState(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    RUNNING = "RUNNING"
    ENDED = "ENDED"


class ExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_id: str
    state: ExecState
    argv: list[str]
    labels: dict[str, str]
    pid: int
    started_at: datetime | None
    deadline_at: datetime | None
    stdout_bytes: int
    stderr_bytes: int
    # Set when state is ENDED.
    result: ExecResult | None


class CancelResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result: ExecResult
    # True if the execution had already ended.
    already_ended: bool


# Guest daemon file calls. Paths are relative to /workspace/sessions/<session_id>/.


class FileType(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    REGULAR = "REGULAR"
    DIRECTORY = "DIRECTORY"
    SYMLINK = "SYMLINK"
    # A device, FIFO or socket.
    OTHER = "OTHER"


class FileEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Session-relative, "/"-separated.
    path: str
    name: str
    type: FileType
    size: int
    # mode & 0o777
    mode: int
    modified_at: datetime | None
    # SYMLINK only.
    link_target: str


class WrittenFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    info: FileEntry
    # Hex SHA-256 of the bytes written.
    sha256: str


class FileListing(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: list[FileEntry]
    # A max_entries, max_depth or response size limit cut the listing.
    truncated: bool


class ZipSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    files: int
    input_bytes: int
    zip_bytes: int
    # Links, special files and unreadable entries that were left out.
    skipped: int


# Host agent session saves and managed drive.


class ArchiveLimits(BaseModel):
    """Limits of one capture or restore. 0 = the daemon default."""

    model_config = ConfigDict(frozen=True)

    max_stored_bytes: int = Field(default=0, ge=0)
    max_expanded_bytes: int = Field(default=0, ge=0)
    max_entries: int = Field(default=0, ge=0)


class PresignedRequest(BaseModel):
    """A presigned object storage request. The agent sends exactly these
    headers. The URL is a credential: never log it."""

    model_config = ConfigDict(frozen=True)

    url: SecretStr
    # "PUT" for UploadCapture, "GET" for RestoreSession.
    method: str
    headers: dict[str, str] = Field(default_factory=dict)


class VmInstance(BaseModel):
    """One VM instance on a node, and its guest daemon key."""

    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    attempt: int
    generation: int
    sandboxd_key: SecretStr


class SessionCapture(BaseModel):
    model_config = ConfigDict(frozen=True)

    capture_id: str
    # Archive size and hex SHA-256, for presign_upload.
    size_bytes: int
    sha256: str
    files: int
    directories: int
    expanded_bytes: int
    excluded: int
    skipped: int
    # Files that shrank during the capture (their tail is zero-filled).
    changed: int
    roots: list[str]
    capture_ms: int
    # The agent deletes the spool after this time.
    expires_at: datetime | None


class CaptureUpload(BaseModel):
    model_config = ConfigDict(frozen=True)

    size_bytes: int
    sha256: str
    http_status: int
    etag: str
    upload_ms: int


class SessionRestore(BaseModel):
    model_config = ConfigDict(frozen=True)

    files: int
    directories: int
    expanded_bytes: int
    # Capture roots that the restore replaced.
    roots: list[str]
    restore_ms: int


class ManagedSlot(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    A = "A"
    B = "B"


class ManagedImageInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    # SHA-256 of the bundle zip.
    image_id: str
    image_sha256: str
    size_bytes: int
    fs_uuid: str
    files: int
    content_bytes: int
    built_at: datetime | None
    # VMs on the node that have the image behind a slot.
    vms: int


class ManagedImagePut(BaseModel):
    model_config = ConfigDict(frozen=True)

    image: ManagedImageInfo
    # False when the image was already on the node.
    built: bool
    build_ms: int
    # Images that the garbage collection removed.
    removed: list[str]


class ManagedSwapResult(BaseModel):
    """SwapManaged result of one VM."""

    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    ok: bool
    # Set when ok is False.
    reason: HostAgentErrorReason | None
    message: str
    active: ManagedSlot
    # False when the image was already the active one.
    changed: bool
    ms: int
    # A guest process still has a file open on the old drive.
    previous_in_use: bool
