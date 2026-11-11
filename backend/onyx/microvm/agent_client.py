"""Typed client for the Firecracker host agent API (`craft.hostagent.v1.HostAgent`).

The agent API is `microvm/proto/hostagent/v1/hostagent.proto`; the stubs in
`generated/` come from it (`generated/regenerate.sh`). Every agent error carries
one `google.rpc.ErrorInfo` with domain `hostagent.craft.onyx.app`;
`HostAgentError.reason` is its reason, and some reasons have their own subclass.

Guest daemon key: each Create sends a new random key (`new_sandboxd_key`) in
`CreateRequest.sandboxd_key`. The agent installs it in the guest daemon before
Create returns. Never log the key.
"""

import abc
import hashlib
import secrets
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

import grpc
from google.protobuf.message import Message
from google.rpc import error_details_pb2, status_pb2
from pydantic import BaseModel, ConfigDict, SecretStr

from onyx.microvm.configs import (
    SANDBOX_FC_AGENT_CA_PATH,
    SANDBOX_FC_AGENT_CLIENT_CERT_PATH,
    SANDBOX_FC_AGENT_CLIENT_KEY_PATH,
    SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS,
    SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
    SANDBOX_FC_AGENT_TLS_SERVER_NAME,
)
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2, hostagent_pb2_grpc
from onyx.microvm.models import (
    AgentVm,
    ArchiveLimits,
    CaptureUpload,
    CreateResult,
    ManagedImageInfo,
    ManagedImagePut,
    ManagedSlot,
    NodeInfo,
    PresignedRequest,
    SessionCapture,
    SessionRestore,
    TemplateInfo,
    VmInstance,
    VmState,
)

if TYPE_CHECKING:
    from onyx.microvm.daemon_client import SandboxDaemonError

HOST_AGENT_ERROR_DOMAIN = "hostagent.craft.onyx.app"
_STATUS_DETAILS_KEY = "grpc-status-details-bin"
# The daemon accepts 32 to 512 printable ASCII bytes; hex of 32 random bytes.
_SANDBOXD_KEY_BYTES = 32
# The pass-through and agent allow 16 MiB messages (ListFiles answers up to 12 MiB).
MAX_MESSAGE_BYTES = 16 << 20
# Presigned transfers: the agent's --transfer-timeout (10 min) plus the guest side.
_TRANSFER_TIMEOUT_SECONDS = max(SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS, 15 * 60.0)
# The agent's --managed-swap-timeout per VM.
_SWAP_TIMEOUT_PER_VM_SECONDS = 30.0
_MANAGED_CHUNK_BYTES = 1 << 20


def new_sandboxd_key() -> SecretStr:
    """A new random guest daemon key for one Create attempt."""
    return SecretStr(secrets.token_hex(_SANDBOXD_KEY_BYTES))


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


class HostAgentError(Exception):
    """A failed agent call.

    `reason` is None when the call failed before the agent answered
    (connection, TLS, deadline): the agent state is then unknown.
    """

    def __init__(
        self,
        code: grpc.StatusCode,
        message: str,
        reason: HostAgentErrorReason | None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"{reason.value if reason else code.name}: {message}")
        self.code = code
        self.message = message
        self.reason = reason
        self.metadata = metadata or {}

    @property
    def reached_agent(self) -> bool:
        return self.reason is not None


class GuestKeyRejectedError(HostAgentError):
    """Create: the guest daemon refused the key. Stop the VM and create a new
    attempt with a new key."""


class GuestUnreachableError(HostAgentError):
    """Nothing in the VM accepted the connection. On Create the VM runs:
    retry the same attempt with the same key."""


class VmNotRunningError(HostAgentError):
    """The sandbox has a VM on the node, but it is not running."""


class InstanceMismatchError(HostAgentError):
    """The attempt or generation does not match the node's VM."""


class DialLimitError(HostAgentError):
    """The VM has the most open Dial streams that the agent allows."""


class MethodNotAllowedError(HostAgentError):
    """Only the agent may call this daemon method (SetKey)."""


_REASON_ERRORS: dict[HostAgentErrorReason, type[HostAgentError]] = {
    HostAgentErrorReason.GUEST_KEY_REJECTED: GuestKeyRejectedError,
    HostAgentErrorReason.GUEST_UNREACHABLE: GuestUnreachableError,
    HostAgentErrorReason.VM_NOT_RUNNING: VmNotRunningError,
    HostAgentErrorReason.INSTANCE_MISMATCH: InstanceMismatchError,
    HostAgentErrorReason.DIAL_LIMIT: DialLimitError,
    HostAgentErrorReason.METHOD_NOT_ALLOWED: MethodNotAllowedError,
}


_VM_STATES: dict[int, VmState] = {
    hostagent_pb2.VM_STATE_STARTING: VmState.STARTING,
    hostagent_pb2.VM_STATE_RUNNING: VmState.RUNNING,
    hostagent_pb2.VM_STATE_EXITED: VmState.EXITED,
}


def _vm_from_proto(vm: hostagent_pb2.VM) -> AgentVm:
    started_at = (
        vm.started_at.ToDatetime(tzinfo=timezone.utc)
        if vm.HasField("started_at")
        else None
    )
    return AgentVm(
        sandbox_id=vm.sandbox_id,
        attempt=vm.attempt,
        generation=vm.generation,
        template=vm.template,
        vcpus=vm.vcpus,
        mem_mib=vm.mem_mib,
        scratch_gib=vm.scratch_gib,
        state=_VM_STATES.get(vm.state, VmState.UNSPECIFIED),
        pid=vm.pid,
        tenant_id=vm.tenant_id,
        started_at=started_at,
    )


def error_info(err: grpc.RpcError) -> error_details_pb2.ErrorInfo | None:
    """The first google.rpc.ErrorInfo detail of a failed call."""
    if not isinstance(err, grpc.Call):
        return None
    for key, value in err.trailing_metadata() or ():
        if key != _STATUS_DETAILS_KEY or not isinstance(value, bytes):
            continue
        status = status_pb2.Status.FromString(value)
        for detail in status.details:
            info = error_details_pb2.ErrorInfo()
            if detail.Unpack(info):
                return info
    return None


def host_agent_error(
    err: grpc.RpcError, info: error_details_pb2.ErrorInfo | None
) -> HostAgentError:
    """The typed error of a failed agent call (or pass-through call)."""
    # Every RpcError a channel raises is also a grpc.Call.
    if not isinstance(err, grpc.Call):
        return HostAgentError(grpc.StatusCode.UNKNOWN, str(err), None)
    code = err.code()
    message = err.details() or ""
    if info is None or info.domain != HOST_AGENT_ERROR_DOMAIN:
        return HostAgentError(code, message, None)
    try:
        reason = HostAgentErrorReason(info.reason)
    except ValueError:
        reason = HostAgentErrorReason.INTERNAL
    cls = _REASON_ERRORS.get(reason, HostAgentError)
    return cls(code, message, reason, dict(info.metadata))


def _error_from_rpc(err: grpc.RpcError) -> HostAgentError:
    return host_agent_error(err, error_info(err))


def _session_error(err: grpc.RpcError) -> "HostAgentError | SandboxDaemonError":
    """Session saves pass guest daemon errors through with their own domain."""
    # daemon_client imports this module.
    from onyx.microvm.daemon_client import _error_from_rpc as daemon_error

    return daemon_error(err)


def proto_time(msg: Message, field: str) -> datetime | None:
    """A Timestamp field as an aware UTC datetime; None when unset."""
    if not msg.HasField(field):
        return None
    # The field name is a parameter.
    ts = getattr(msg, field)  # ods: ignore[getattr]
    return ts.ToDatetime(tzinfo=timezone.utc)


_MANAGED_SLOTS: dict[int, ManagedSlot] = {
    hostagent_pb2.MANAGED_SLOT_A: ManagedSlot.A,
    hostagent_pb2.MANAGED_SLOT_B: ManagedSlot.B,
}


def _limits_proto(limits: ArchiveLimits | None) -> hostagent_pb2.ArchiveLimits:
    limits = limits or ArchiveLimits()
    return hostagent_pb2.ArchiveLimits(
        max_stored_bytes=limits.max_stored_bytes,
        max_expanded_bytes=limits.max_expanded_bytes,
        max_entries=limits.max_entries,
    )


def _presigned_proto(request: PresignedRequest) -> hostagent_pb2.PresignedRequest:
    return hostagent_pb2.PresignedRequest(
        url=request.url.get_secret_value(),
        method=request.method,
        headers=request.headers,
    )


def _managed_image(msg: hostagent_pb2.ManagedImageInfo) -> ManagedImageInfo:
    return ManagedImageInfo(
        image_id=msg.image_id,
        image_sha256=msg.image_sha256,
        size_bytes=msg.size_bytes,
        fs_uuid=msg.fs_uuid,
        files=msg.files,
        content_bytes=msg.content_bytes,
        built_at=proto_time(msg, "built_at"),
        vms=msg.vms,
    )


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


def _swap_result(msg: hostagent_pb2.SwapResult) -> ManagedSwapResult:
    reason: HostAgentErrorReason | None = None
    if not msg.ok:
        try:
            reason = HostAgentErrorReason(hostagent_pb2.ErrorReason.Name(msg.reason))
        except ValueError:
            reason = HostAgentErrorReason.INTERNAL
    return ManagedSwapResult(
        sandbox_id=msg.sandbox_id,
        ok=msg.ok,
        reason=reason,
        message=msg.message,
        active=_MANAGED_SLOTS.get(msg.active, ManagedSlot.UNSPECIFIED),
        changed=msg.changed,
        ms=msg.ms,
        previous_in_use=msg.previous_in_use,
    )


class HostAgentClient:
    """One agent. Thread-safe; closing it closes the channel."""

    def __init__(self, channel: grpc.Channel) -> None:
        self._channel = channel
        self._stub = hostagent_pb2_grpc.HostAgentStub(channel)

    def __enter__(self) -> "HostAgentClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._channel.close()

    @property
    def channel(self) -> grpc.Channel:
        """The agent channel. The guest daemon pass-through shares it."""
        return self._channel

    def create(
        self,
        *,
        sandbox_id: str,
        attempt: int,
        template: str,
        vcpus: int,
        mem_mib: int,
        scratch_gib: int,
        tenant_id: str,
        sandboxd_key: SecretStr,
    ) -> CreateResult:
        """Start (or return) the VM of (sandbox_id, attempt) and install
        `sandboxd_key` in its guest daemon.

        Raises GuestUnreachableError when the daemon did not take the key in
        time (retry with the same attempt and key) and GuestKeyRejectedError
        when it refused the key (stop the VM, create a new attempt).
        """
        request = hostagent_pb2.CreateRequest(
            sandbox_id=sandbox_id,
            attempt=attempt,
            template=template,
            vcpus=vcpus,
            mem_mib=mem_mib,
            scratch_gib=scratch_gib,
            tenant_id=tenant_id,
            sandboxd_key=sandboxd_key.get_secret_value(),
        )
        try:
            response: hostagent_pb2.CreateResponse = self._stub.Create(
                request, timeout=SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return CreateResult(vm=_vm_from_proto(response.vm), created=response.created)

    def stop(self, *, sandbox_id: str, attempt: int, generation: int) -> bool:
        """Stop one VM instance. Returns True when it was already stopped."""
        request = hostagent_pb2.StopRequest(
            sandbox_id=sandbox_id, attempt=attempt, generation=generation
        )
        try:
            # Stop waits for the VM exit (the agent's --stop-timeout is 30 s).
            response: hostagent_pb2.StopResponse = self._stub.Stop(
                request, timeout=SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return response.already_stopped

    def list_vms(self) -> list[AgentVm]:
        try:
            response: hostagent_pb2.ListResponse = self._stub.List(
                hostagent_pb2.ListRequest(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return [_vm_from_proto(vm) for vm in response.vms]

    def node_info(self) -> NodeInfo:
        try:
            r: hostagent_pb2.NodeInfoResponse = self._stub.NodeInfo(
                hostagent_pb2.NodeInfoRequest(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return NodeInfo(
            mem_total_mib=r.mem_total_mib,
            mem_available_mib=r.mem_available_mib,
            vm_count=r.vm_count,
            templates=[
                TemplateInfo(
                    version=t.version,
                    vcpus=t.vcpus,
                    mem_mib=t.mem_mib,
                    scratch_gib=t.scratch_gib,
                    guest_kernel=t.guest_kernel,
                    firecracker_version=t.firecracker_version,
                )
                for t in r.templates
            ],
            cpu_model=r.cpu_model,
            firecracker_version=r.firecracker_version,
            host_kernel=r.host_kernel,
            agent_version=r.agent_version,
            disk_free_mib=r.disk_free_mib,
        )

    def close_connections(
        self, *, sandbox_id: str, attempt: int, generation: int
    ) -> int:
        """Close the VM's egress relay connections. Returns how many closed."""
        request = hostagent_pb2.CloseConnectionsRequest(
            sandbox_id=sandbox_id, attempt=attempt, generation=generation
        )
        try:
            response: hostagent_pb2.CloseConnectionsResponse = (
                self._stub.CloseConnections(
                    request, timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS
                )
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return response.closed

    # Session saves. Order: capture_session → presign_upload(size_bytes,
    # sha256) → upload_capture → finalize → commit → prune. Guest daemon
    # errors raise as SandboxDaemonError.

    def capture_session(
        self,
        vm: VmInstance,
        *,
        session_id: str,
        roots: list[str] | None = None,
        exclude_names: list[str] | None = None,
        limits: ArchiveLimits | None = None,
    ) -> SessionCapture:
        """Archive the session's capture roots and spool it on the node.
        Empty roots / exclude_names mean the daemon defaults."""
        request = hostagent_pb2.CaptureSessionRequest(
            sandbox_id=vm.sandbox_id,
            attempt=vm.attempt,
            generation=vm.generation,
            sandboxd_key=vm.sandboxd_key.get_secret_value(),
            session_id=session_id,
            roots=roots or [],
            exclude_names=exclude_names or [],
            limits=_limits_proto(limits),
        )
        try:
            r: hostagent_pb2.CaptureSessionResponse = self._stub.CaptureSession(
                request, timeout=_TRANSFER_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise _session_error(e) from e
        return SessionCapture(
            capture_id=r.capture_id,
            size_bytes=r.size_bytes,
            sha256=r.sha256,
            files=r.files,
            directories=r.directories,
            expanded_bytes=r.expanded_bytes,
            excluded=r.excluded,
            skipped=r.skipped,
            changed=r.changed,
            roots=list(r.roots),
            capture_ms=r.capture_ms,
            expires_at=proto_time(r, "expires_at"),
        )

    def upload_capture(
        self, *, capture_id: str, request: PresignedRequest
    ) -> CaptureUpload:
        """PUT a spooled capture. On failure the spool stays until its TTL,
        so a retry with a new URL works. CAPTURE_NOT_FOUND: capture again."""
        try:
            r: hostagent_pb2.UploadCaptureResponse = self._stub.UploadCapture(
                hostagent_pb2.UploadCaptureRequest(
                    capture_id=capture_id, request=_presigned_proto(request)
                ),
                timeout=_TRANSFER_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return CaptureUpload(
            size_bytes=r.size_bytes,
            sha256=r.sha256,
            http_status=r.http_status,
            etag=r.etag,
            upload_ms=r.upload_ms,
        )

    def discard_capture(self, *, capture_id: str) -> bool:
        """Delete a spooled capture. Returns False when there was none."""
        try:
            r: hostagent_pb2.DiscardCaptureResponse = self._stub.DiscardCapture(
                hostagent_pb2.DiscardCaptureRequest(capture_id=capture_id),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return r.discarded

    def restore_session(
        self,
        vm: VmInstance,
        *,
        session_id: str,
        request: PresignedRequest,
        size_bytes: int,
        sha256: str,
        roots: list[str] | None = None,
        limits: ArchiveLimits | None = None,
    ) -> SessionRestore:
        """Download an archive with a presigned GET into the session. The
        daemon checks size and SHA-256 before it replaces any file."""
        proto = hostagent_pb2.RestoreSessionRequest(
            sandbox_id=vm.sandbox_id,
            attempt=vm.attempt,
            generation=vm.generation,
            sandboxd_key=vm.sandboxd_key.get_secret_value(),
            session_id=session_id,
            request=_presigned_proto(request),
            size_bytes=size_bytes,
            sha256=sha256,
            roots=roots or [],
            limits=_limits_proto(limits),
        )
        try:
            r: hostagent_pb2.RestoreSessionResponse = self._stub.RestoreSession(
                proto, timeout=_TRANSFER_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise _session_error(e) from e
        return SessionRestore(
            files=r.files,
            directories=r.directories,
            expanded_bytes=r.expanded_bytes,
            roots=list(r.roots),
            restore_ms=r.restore_ms,
        )

    # Managed drive (read-only /workspace/managed).

    def put_managed_image(self, bundle_zip: bytes) -> ManagedImagePut:
        """Upload a managed bundle zip and build its image on the node. The
        image ID is the zip's SHA-256; a repeat put does not build again."""
        header = hostagent_pb2.ManagedBundleHeader(
            sha256=hashlib.sha256(bundle_zip).hexdigest(),
            size_bytes=len(bundle_zip),
        )

        def requests() -> Iterator[hostagent_pb2.PutManagedImageRequest]:
            yield hostagent_pb2.PutManagedImageRequest(header=header)
            for start in range(0, len(bundle_zip), _MANAGED_CHUNK_BYTES):
                yield hostagent_pb2.PutManagedImageRequest(
                    data=bundle_zip[start : start + _MANAGED_CHUNK_BYTES]
                )

        try:
            r: hostagent_pb2.PutManagedImageResponse = self._stub.PutManagedImage(
                requests(), timeout=_TRANSFER_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return ManagedImagePut(
            image=_managed_image(r.image),
            built=r.built,
            build_ms=r.build_ms,
            removed=list(r.removed),
        )

    def swap_managed(
        self, *, image_id: str, targets: list[VmInstance]
    ) -> list[ManagedSwapResult]:
        """Put a managed image into running VMs, one at a time. Each target
        has its own result, in request order; a failed VM raises nothing."""
        request = hostagent_pb2.SwapManagedRequest(
            image_id=image_id,
            targets=[
                hostagent_pb2.SwapTarget(
                    sandbox_id=t.sandbox_id,
                    attempt=t.attempt,
                    generation=t.generation,
                    sandboxd_key=t.sandboxd_key.get_secret_value(),
                )
                for t in targets
            ],
        )
        try:
            r: hostagent_pb2.SwapManagedResponse = self._stub.SwapManaged(
                request,
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS
                + _SWAP_TIMEOUT_PER_VM_SECONDS * len(targets),
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return [_swap_result(x) for x in r.results]


class HostAgentClientFactory(abc.ABC):
    """Clients for agent addresses (`host:port`)."""

    @abc.abstractmethod
    def client(self, address: str) -> HostAgentClient:
        raise NotImplementedError


class HostAgentConfigError(Exception):
    """The mTLS settings are missing or cannot be read."""


class MtlsHostAgentClientFactory(HostAgentClientFactory):
    """mTLS channels, one per address, shared between calls."""

    def __init__(
        self,
        *,
        cert_path: str = SANDBOX_FC_AGENT_CLIENT_CERT_PATH,
        key_path: str = SANDBOX_FC_AGENT_CLIENT_KEY_PATH,
        ca_path: str = SANDBOX_FC_AGENT_CA_PATH,
        server_name: str = SANDBOX_FC_AGENT_TLS_SERVER_NAME,
    ) -> None:
        self._cert_path = cert_path
        self._key_path = key_path
        self._ca_path = ca_path
        self._server_name = server_name
        self._lock = threading.Lock()
        self._credentials: grpc.ChannelCredentials | None = None
        self._channels: dict[str, grpc.Channel] = {}

    def _load_credentials(self) -> grpc.ChannelCredentials:
        if not (self._cert_path and self._key_path and self._ca_path):
            raise HostAgentConfigError(
                "SANDBOX_FC_AGENT_CLIENT_CERT_PATH, SANDBOX_FC_AGENT_CLIENT_KEY_PATH "
                "and SANDBOX_FC_AGENT_CA_PATH must be set"
            )
        try:
            return grpc.ssl_channel_credentials(
                root_certificates=Path(self._ca_path).read_bytes(),
                private_key=Path(self._key_path).read_bytes(),
                certificate_chain=Path(self._cert_path).read_bytes(),
            )
        except OSError as e:
            raise HostAgentConfigError(f"cannot read the agent mTLS files: {e}") from e

    def client(self, address: str) -> HostAgentClient:
        with self._lock:
            channel = self._channels.get(address)
            if channel is None:
                if self._credentials is None:
                    self._credentials = self._load_credentials()
                options: list[tuple[str, str | int]] = [
                    ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
                    ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
                ]
                if self._server_name:
                    options.append(("grpc.ssl_target_name_override", self._server_name))
                channel = grpc.secure_channel(address, self._credentials, options)
                self._channels[address] = channel
        return _SharedChannelClient(channel)


class _SharedChannelClient(HostAgentClient):
    """Leaves the pooled channel open on close."""

    def close(self) -> None:
        return None
