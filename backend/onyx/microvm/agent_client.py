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
import secrets
import threading
from datetime import timezone
from enum import Enum
from pathlib import Path
from types import TracebackType

import grpc
from google.rpc import error_details_pb2, status_pb2
from pydantic import SecretStr

from onyx.microvm.configs import (
    SANDBOX_FC_AGENT_CA_PATH,
    SANDBOX_FC_AGENT_CLIENT_CERT_PATH,
    SANDBOX_FC_AGENT_CLIENT_KEY_PATH,
    SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS,
    SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
    SANDBOX_FC_AGENT_TLS_SERVER_NAME,
)
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2, hostagent_pb2_grpc
from onyx.microvm.models import AgentVm, CreateResult, NodeInfo, TemplateInfo, VmState

HOST_AGENT_ERROR_DOMAIN = "hostagent.craft.onyx.app"
_STATUS_DETAILS_KEY = "grpc-status-details-bin"
# The daemon accepts 32 to 512 printable ASCII bytes; hex of 32 random bytes.
_SANDBOXD_KEY_BYTES = 32


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
        timeout: float | None = None,
    ) -> CreateResult:
        """Start (or return) the VM of (sandbox_id, attempt) and install
        `sandboxd_key` in its guest daemon.

        Raises GuestUnreachableError when the daemon did not take the key in
        time (retry with the same attempt and key) and GuestKeyRejectedError
        when it refused the key (stop the VM, create a new attempt).
        `timeout` defaults to `SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS`.
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
                request,
                timeout=(
                    SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS
                    if timeout is None
                    else timeout
                ),
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return CreateResult(vm=_vm_from_proto(response.vm), created=response.created)

    def stop(
        self,
        *,
        sandbox_id: str,
        attempt: int,
        generation: int,
        timeout: float | None = None,
    ) -> bool:
        """Stop one VM instance. Returns True when it was already stopped."""
        request = hostagent_pb2.StopRequest(
            sandbox_id=sandbox_id, attempt=attempt, generation=generation
        )
        try:
            # Stop waits for the VM exit (the agent's --stop-timeout is 30 s).
            response: hostagent_pb2.StopResponse = self._stub.Stop(
                request,
                timeout=(
                    SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS
                    if timeout is None
                    else timeout
                ),
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
                options: list[tuple[str, str | int]] = []
                if self._server_name:
                    options.append(("grpc.ssl_target_name_override", self._server_name))
                channel = grpc.secure_channel(address, self._credentials, options)
                self._channels[address] = channel
        return _SharedChannelClient(channel)


class _SharedChannelClient(HostAgentClient):
    """Leaves the pooled channel open on close."""

    def close(self) -> None:
        return None
