"""Typed client for the guest daemon (`craft.sandboxd.v1.Sandboxd`), through the
host agent pass-through.

The API is `microvm/proto/sandboxd/v1/sandboxd.proto`. Every call carries
`x-sandbox-id` (the agent routes on it). Every call except Health, Init
included, also carries the VM's key in `x-sandboxd-key`. The agent installs
the key at Create; this client never calls SetKey.

Errors: a daemon error is a `SandboxDaemonError` (domain
`sandboxd.craft.onyx.app`). An error of the pass-through itself (the VM is not
running, the daemon is unreachable) is a `HostAgentError`.
"""

import secrets
from datetime import datetime, timezone
from enum import Enum

import grpc
from pydantic import SecretStr

from onyx.microvm.agent_client import HostAgentError, error_info, host_agent_error
from onyx.microvm.configs import SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2, sandboxd_pb2_grpc
from onyx.microvm.models import DaemonHealth, DaemonInitResult

SANDBOXD_ERROR_DOMAIN = "sandboxd.craft.onyx.app"
SANDBOX_ID_HEADER = "x-sandbox-id"
SANDBOXD_KEY_HEADER = "x-sandboxd-key"
# Init attaches drives and grows the scratch file system.
_INIT_TIMEOUT_SECONDS = max(SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS, 60.0)
_ENTROPY_BYTES = 64


class SandboxDaemonErrorReason(str, Enum):
    """`ErrorReason` names from sandboxd.proto."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    EXECUTION_NOT_FOUND = "EXECUTION_NOT_FOUND"
    STDIN_NOT_OPEN = "STDIN_NOT_OPEN"
    EXECUTION_ENDED = "EXECUTION_ENDED"
    START_FAILED = "START_FAILED"
    TOO_MANY_EXECUTIONS = "TOO_MANY_EXECUTIONS"
    INIT_FAILED = "INIT_FAILED"
    INTERNAL = "INTERNAL"
    KEY_NOT_SET = "KEY_NOT_SET"
    KEY_ALREADY_SET = "KEY_ALREADY_SET"


# The daemon will not accept this VM's key: nothing can use the VM.
_UNUSABLE_REASONS: frozenset[SandboxDaemonErrorReason] = frozenset(
    {SandboxDaemonErrorReason.KEY_NOT_SET, SandboxDaemonErrorReason.UNAUTHENTICATED}
)


class SandboxDaemonError(Exception):
    def __init__(
        self,
        code: grpc.StatusCode,
        message: str,
        reason: SandboxDaemonErrorReason,
    ) -> None:
        super().__init__(f"{reason.value}: {message}")
        self.code = code
        self.message = message
        self.reason = reason

    @property
    def vm_unusable(self) -> bool:
        """True when the daemon has no key or another key. Stop the VM and
        create a new attempt."""
        return self.reason in _UNUSABLE_REASONS


class SandboxDaemonKeyNotSetError(SandboxDaemonError):
    """The agent did not install a key: the VM is unusable."""


def _error_from_rpc(err: grpc.RpcError) -> SandboxDaemonError | HostAgentError:
    info = error_info(err)
    if (
        info is None
        or info.domain != SANDBOXD_ERROR_DOMAIN
        or not isinstance(err, grpc.Call)
    ):
        # The pass-through's own error, or no answer.
        return host_agent_error(err, info)
    try:
        reason = SandboxDaemonErrorReason(info.reason)
    except ValueError:
        reason = SandboxDaemonErrorReason.INTERNAL
    cls = (
        SandboxDaemonKeyNotSetError
        if reason is SandboxDaemonErrorReason.KEY_NOT_SET
        else SandboxDaemonError
    )
    return cls(err.code(), err.details() or "", reason)


class SandboxDaemonClient:
    """The guest daemon of one VM. Shares the agent's channel; never closes it."""

    def __init__(
        self, channel: grpc.Channel, *, sandbox_id: str, sandboxd_key: SecretStr
    ) -> None:
        self._stub = sandboxd_pb2_grpc.SandboxdStub(channel)
        self._sandbox_id = sandbox_id
        self._key = sandboxd_key

    def _routing(self) -> tuple[tuple[str, str], ...]:
        return ((SANDBOX_ID_HEADER, self._sandbox_id),)

    def _authed(self) -> tuple[tuple[str, str], ...]:
        return (
            (SANDBOX_ID_HEADER, self._sandbox_id),
            (SANDBOXD_KEY_HEADER, self._key.get_secret_value()),
        )

    def health(self, timeout: float | None = None) -> DaemonHealth:
        """Needs no key."""
        try:
            r: sandboxd_pb2.HealthResponse = self._stub.Health(
                sandboxd_pb2.HealthRequest(),
                metadata=self._routing(),
                timeout=(
                    SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS if timeout is None else timeout
                ),
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return DaemonHealth(
            initialized=r.initialized,
            key_set=r.key_set,
            version=r.version,
            generation=r.generation,
            sandbox_id=r.sandbox_id,
            running_executions=r.running_executions,
        )

    def init(
        self,
        *,
        generation: int,
        scratch_gib: int,
        env: dict[str, str],
        session_ids: list[str],
    ) -> DaemonInitResult:
        """Run after every boot or restore, after the agent's CloseConnections.

        Raises SandboxDaemonError; `vm_unusable` is True on KEY_NOT_SET.
        """
        request = sandboxd_pb2.InitRequest(
            entropy=secrets.token_bytes(_ENTROPY_BYTES),
            env=env,
            session_ids=session_ids,
            generation=generation,
            sandbox_id=self._sandbox_id,
            scratch_bytes=scratch_gib << 30,
        )
        request.host_time.FromDatetime(datetime.now(timezone.utc))
        try:
            r: sandboxd_pb2.InitResponse = self._stub.Init(
                request, metadata=self._authed(), timeout=_INIT_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise _error_from_rpc(e) from e
        return DaemonInitResult(
            version=r.version,
            clock_step_seconds=r.clock_step.ToTimedelta().total_seconds(),
            entropy_credited=r.entropy_credited,
            attached=r.attached,
            relay_reset=r.relay_reset,
        )
