"""In-process fake of the Firecracker host agent gRPC server, with a fake guest
daemon behind its pass-through."""

import threading
from concurrent import futures

import grpc
from google.rpc import error_details_pb2, status_pb2

from onyx.microvm.agent_client import (
    HOST_AGENT_ERROR_DOMAIN,
    HostAgentClient,
    HostAgentClientFactory,
    HostAgentErrorReason,
)
from onyx.microvm.daemon_client import (
    SANDBOX_ID_HEADER,
    SANDBOXD_ERROR_DOMAIN,
    SANDBOXD_KEY_HEADER,
    SandboxDaemonErrorReason,
)
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2, hostagent_pb2_grpc
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2, sandboxd_pb2_grpc

_REASON_CODES: dict[HostAgentErrorReason, grpc.StatusCode] = {
    HostAgentErrorReason.CAPACITY_MEMORY: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.CAPACITY_DISK: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.CAPACITY_VM_SLOTS: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.ATTEMPT_CONFLICT: grpc.StatusCode.ALREADY_EXISTS,
    HostAgentErrorReason.SANDBOX_NOT_FOUND: grpc.StatusCode.NOT_FOUND,
    HostAgentErrorReason.INSTANCE_MISMATCH: grpc.StatusCode.FAILED_PRECONDITION,
    HostAgentErrorReason.GUEST_UNREACHABLE: grpc.StatusCode.UNAVAILABLE,
    HostAgentErrorReason.METHOD_NOT_ALLOWED: grpc.StatusCode.PERMISSION_DENIED,
    HostAgentErrorReason.DIAL_LIMIT: grpc.StatusCode.RESOURCE_EXHAUSTED,
}


def _abort(
    context: grpc.ServicerContext,
    code: grpc.StatusCode,
    domain: str,
    reason: str,
    message: str,
) -> None:
    status = status_pb2.Status(code=code.value[0], message=message)
    status.details.add().Pack(error_details_pb2.ErrorInfo(reason=reason, domain=domain))
    context.set_trailing_metadata(
        (("grpc-status-details-bin", status.SerializeToString()),)
    )
    context.abort(code, message)


def abort_with_reason(
    context: grpc.ServicerContext, reason: HostAgentErrorReason, message: str
) -> None:
    code = _REASON_CODES.get(reason, grpc.StatusCode.FAILED_PRECONDITION)
    _abort(context, code, HOST_AGENT_ERROR_DOMAIN, reason.value, message)


def abort_daemon(
    context: grpc.ServicerContext, reason: SandboxDaemonErrorReason, message: str
) -> None:
    code = (
        grpc.StatusCode.UNAUTHENTICATED
        if reason
        in (
            SandboxDaemonErrorReason.UNAUTHENTICATED,
            SandboxDaemonErrorReason.KEY_NOT_SET,
        )
        else grpc.StatusCode.FAILED_PRECONDITION
    )
    _abort(context, code, SANDBOXD_ERROR_DOMAIN, reason.value, message)


class FakeHostAgent(hostagent_pb2_grpc.HostAgentServicer):
    """One node. VMs live in memory; tests change the knobs between calls."""

    def __init__(
        self,
        *,
        mem_available_mib: int = 16_384,
        template: str = "tpl-1",
        template_mem_mib: int = 2048,
    ) -> None:
        self.lock = threading.Lock()
        self.mem_available_mib = mem_available_mib
        self.templates = [
            hostagent_pb2.TemplateInfo(
                version=template,
                vcpus=2,
                mem_mib=template_mem_mib,
                scratch_gib=4,
                guest_kernel="6.18.25",
                firecracker_version="v1.17.0",
            )
        ]
        self.vms: dict[str, hostagent_pb2.VM] = {}
        self.refuse_create: HostAgentErrorReason | None = None
        self.next_generation = 1_000
        self.create_calls = 0
        self.stop_calls: list[tuple[str, int, int]] = []
        # (sandbox_id, attempt, sandboxd_key) of every Create.
        self.create_requests: list[tuple[str, int, str]] = []
        # The key each guest daemon holds (its SetKey state).
        self.daemon_keys: dict[str, str] = {}
        # The next N key installs time out (GUEST_UNREACHABLE).
        self.guest_unreachable_creates = 0
        # The next N Creates start the VM, then fail with no reason (a lost
        # answer, e.g. a deadline): the caller cannot know the VM runs.
        self.lost_create_answers = 0
        self.init_requests: list[tuple[sandboxd_pb2.InitRequest, str]] = []

    def add_vm(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        attempt: int,
        state: hostagent_pb2.VMState = hostagent_pb2.VM_STATE_RUNNING,
        daemon_key: str | None = None,
    ) -> hostagent_pb2.VM:
        with self.lock:
            if daemon_key is not None:
                self.daemon_keys[sandbox_id] = daemon_key
            self.next_generation += 1
            vm = hostagent_pb2.VM(
                sandbox_id=sandbox_id,
                attempt=attempt,
                generation=self.next_generation,
                template=self.templates[0].version,
                vcpus=2,
                mem_mib=self.templates[0].mem_mib,
                scratch_gib=4,
                state=state,
                pid=4242,
                tenant_id=tenant_id,
            )
            self.vms[sandbox_id] = vm
            return vm

    def Create(  # noqa: N802
        self, request: hostagent_pb2.CreateRequest, context: grpc.ServicerContext
    ) -> hostagent_pb2.CreateResponse:
        with self.lock:
            self.create_calls += 1
            self.create_requests.append(
                (request.sandbox_id, request.attempt, request.sandboxd_key)
            )
            if self.refuse_create is not None:
                abort_with_reason(context, self.refuse_create, "refused by the test")
            existing = self.vms.get(request.sandbox_id)
            if existing is not None:
                # Like the real agent: the same attempt returns the VM, even
                # an exited one; only a newer attempt replaces an exited VM.
                if existing.attempt == request.attempt:
                    if existing.state != hostagent_pb2.VM_STATE_EXITED:
                        self._install_key(context, request)
                    return hostagent_pb2.CreateResponse(vm=existing, created=False)
                if (
                    existing.state != hostagent_pb2.VM_STATE_EXITED
                    or request.attempt < existing.attempt
                ):
                    abort_with_reason(
                        context, HostAgentErrorReason.ATTEMPT_CONFLICT, "other attempt"
                    )
                del self.vms[request.sandbox_id]
            if self.mem_available_mib < request.mem_mib:
                abort_with_reason(
                    context, HostAgentErrorReason.CAPACITY_MEMORY, "not enough memory"
                )
            self.next_generation += 1
            vm = hostagent_pb2.VM(
                sandbox_id=request.sandbox_id,
                attempt=request.attempt,
                generation=self.next_generation,
                template=request.template,
                vcpus=request.vcpus,
                mem_mib=request.mem_mib,
                scratch_gib=request.scratch_gib,
                state=hostagent_pb2.VM_STATE_RUNNING,
                pid=4242,
                tenant_id=request.tenant_id,
            )
            self.vms[request.sandbox_id] = vm
            self.mem_available_mib -= request.mem_mib
            # A new VM boots a new daemon with no key.
            self.daemon_keys.pop(request.sandbox_id, None)
            if self.lost_create_answers > 0:
                self.lost_create_answers -= 1
                self.daemon_keys[request.sandbox_id] = request.sandboxd_key
                context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "answer lost")
            self._install_key(context, request)
            return hostagent_pb2.CreateResponse(vm=vm, created=True)

    def _install_key(
        self, context: grpc.ServicerContext, request: hostagent_pb2.CreateRequest
    ) -> None:
        """The agent's SetKey over vsock: the first key stays."""
        if not request.sandboxd_key:
            return
        if self.guest_unreachable_creates > 0:
            self.guest_unreachable_creates -= 1
            abort_with_reason(
                context, HostAgentErrorReason.GUEST_UNREACHABLE, "daemon not ready"
            )
        held = self.daemon_keys.setdefault(request.sandbox_id, request.sandboxd_key)
        if held != request.sandboxd_key:
            abort_with_reason(
                context, HostAgentErrorReason.GUEST_KEY_REJECTED, "KEY_ALREADY_SET"
            )

    def Stop(  # noqa: N802
        self, request: hostagent_pb2.StopRequest, context: grpc.ServicerContext
    ) -> hostagent_pb2.StopResponse:
        with self.lock:
            self.stop_calls.append(
                (request.sandbox_id, request.attempt, request.generation)
            )
            vm = self.vms.get(request.sandbox_id)
            if vm is None:
                abort_with_reason(
                    context, HostAgentErrorReason.SANDBOX_NOT_FOUND, "no such VM"
                )
                raise AssertionError("unreachable")
            if vm.attempt != request.attempt or vm.generation != request.generation:
                abort_with_reason(
                    context, HostAgentErrorReason.INSTANCE_MISMATCH, "other instance"
                )
            del self.vms[request.sandbox_id]
            self.daemon_keys.pop(request.sandbox_id, None)
            self.mem_available_mib += vm.mem_mib
            return hostagent_pb2.StopResponse(already_stopped=False)

    def List(  # noqa: N802
        self,
        request: hostagent_pb2.ListRequest,  # noqa: ARG002
        context: grpc.ServicerContext,  # noqa: ARG002
    ) -> hostagent_pb2.ListResponse:
        with self.lock:
            return hostagent_pb2.ListResponse(vms=list(self.vms.values()))

    def NodeInfo(  # noqa: N802
        self,
        request: hostagent_pb2.NodeInfoRequest,  # noqa: ARG002
        context: grpc.ServicerContext,  # noqa: ARG002
    ) -> hostagent_pb2.NodeInfoResponse:
        with self.lock:
            return hostagent_pb2.NodeInfoResponse(
                mem_total_mib=65_536,
                mem_available_mib=self.mem_available_mib,
                vm_count=len(self.vms),
                templates=self.templates,
                cpu_model="fake",
                firecracker_version="v1.17.0",
                host_kernel="6.18",
                agent_version="test",
                disk_free_mib=100_000,
            )

    def CloseConnections(  # noqa: N802
        self,
        request: hostagent_pb2.CloseConnectionsRequest,  # noqa: ARG002
        context: grpc.ServicerContext,  # noqa: ARG002
    ) -> hostagent_pb2.CloseConnectionsResponse:
        return hostagent_pb2.CloseConnectionsResponse(closed=3)


class FakeSandboxd(sandboxd_pb2_grpc.SandboxdServicer):
    """The guest daemons behind the agent pass-through (x-sandbox-id routing)."""

    def __init__(self, agent: FakeHostAgent) -> None:
        self.agent = agent

    def _route(self, context: grpc.ServicerContext) -> tuple[str, str | None]:
        md = dict(context.invocation_metadata())
        sandbox_id = md.get(SANDBOX_ID_HEADER)
        if not isinstance(sandbox_id, str):
            abort_with_reason(
                context, HostAgentErrorReason.INVALID_ARGUMENT, "no x-sandbox-id"
            )
            raise AssertionError("unreachable")
        vm = self.agent.vms.get(sandbox_id)
        if vm is None or vm.state != hostagent_pb2.VM_STATE_RUNNING:
            abort_with_reason(
                context, HostAgentErrorReason.VM_NOT_RUNNING, "no running VM"
            )
        key = md.get(SANDBOXD_KEY_HEADER)
        return sandbox_id, key if isinstance(key, str) else None

    def _check_key(
        self, context: grpc.ServicerContext, sandbox_id: str, key: str | None
    ) -> None:
        held = self.agent.daemon_keys.get(sandbox_id)
        if held is None:
            abort_daemon(context, SandboxDaemonErrorReason.KEY_NOT_SET, "no key")
        if key != held:
            abort_daemon(context, SandboxDaemonErrorReason.UNAUTHENTICATED, "bad key")

    def Health(  # noqa: N802
        self,
        request: sandboxd_pb2.HealthRequest,  # noqa: ARG002
        context: grpc.ServicerContext,
    ) -> sandboxd_pb2.HealthResponse:
        with self.agent.lock:
            sandbox_id, _ = self._route(context)
            return sandboxd_pb2.HealthResponse(
                version="fake",
                sandbox_id=sandbox_id,
                key_set=sandbox_id in self.agent.daemon_keys,
            )

    def SetKey(  # noqa: N802
        self,
        request: sandboxd_pb2.SetKeyRequest,  # noqa: ARG002
        context: grpc.ServicerContext,
    ) -> sandboxd_pb2.SetKeyResponse:
        abort_with_reason(
            context, HostAgentErrorReason.METHOD_NOT_ALLOWED, "only the agent"
        )
        raise AssertionError("unreachable")

    def Init(  # noqa: N802
        self, request: sandboxd_pb2.InitRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.InitResponse:
        with self.agent.lock:
            sandbox_id, key = self._route(context)
            self._check_key(context, sandbox_id, key)
            self.agent.init_requests.append((request, sandbox_id))
            return sandboxd_pb2.InitResponse(
                version="fake", attached=True, relay_reset=True
            )


class RunningFakeAgent:
    def __init__(
        self,
        agent: FakeHostAgent,
        server_credentials: grpc.ServerCredentials | None = None,
    ) -> None:
        self.agent = agent
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        hostagent_pb2_grpc.add_HostAgentServicer_to_server(agent, self.server)
        sandboxd_pb2_grpc.add_SandboxdServicer_to_server(
            FakeSandboxd(agent), self.server
        )
        if server_credentials is None:
            port = self.server.add_insecure_port("127.0.0.1:0")
        else:
            port = self.server.add_secure_port("127.0.0.1:0", server_credentials)
        self.address = f"127.0.0.1:{port}"
        self.server.start()

    def stop(self) -> None:
        self.server.stop(grace=None)


class _KeepOpenClient(HostAgentClient):
    def close(self) -> None:
        return None


class InsecureClientFactory(HostAgentClientFactory):
    """Plain-text channels for the fake agents, one per address."""

    def __init__(self) -> None:
        self._channels: dict[str, grpc.Channel] = {}

    def client(self, address: str) -> HostAgentClient:
        channel = self._channels.get(address)
        if channel is None:
            channel = grpc.insecure_channel(address)
            self._channels[address] = channel
        return _KeepOpenClient(channel)

    def close(self) -> None:
        for channel in self._channels.values():
            channel.close()
