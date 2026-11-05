"""In-process fake of the Firecracker host agent gRPC server."""

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
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2, hostagent_pb2_grpc

_REASON_CODES: dict[HostAgentErrorReason, grpc.StatusCode] = {
    HostAgentErrorReason.CAPACITY_MEMORY: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.CAPACITY_DISK: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.CAPACITY_VM_SLOTS: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.ATTEMPT_CONFLICT: grpc.StatusCode.ALREADY_EXISTS,
    HostAgentErrorReason.SANDBOX_NOT_FOUND: grpc.StatusCode.NOT_FOUND,
    HostAgentErrorReason.INSTANCE_MISMATCH: grpc.StatusCode.FAILED_PRECONDITION,
}


def abort_with_reason(
    context: grpc.ServicerContext, reason: HostAgentErrorReason, message: str
) -> None:
    code = _REASON_CODES.get(reason, grpc.StatusCode.FAILED_PRECONDITION)
    status = status_pb2.Status(code=code.value[0], message=message)
    status.details.add().Pack(
        error_details_pb2.ErrorInfo(reason=reason.value, domain=HOST_AGENT_ERROR_DOMAIN)
    )
    context.set_trailing_metadata(
        (("grpc-status-details-bin", status.SerializeToString()),)
    )
    context.abort(code, message)


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

    def add_vm(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        attempt: int,
        state: hostagent_pb2.VMState = hostagent_pb2.VM_STATE_RUNNING,
    ) -> hostagent_pb2.VM:
        with self.lock:
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
            if self.refuse_create is not None:
                abort_with_reason(context, self.refuse_create, "refused by the test")
            existing = self.vms.get(request.sandbox_id)
            if existing is not None and existing.state != hostagent_pb2.VM_STATE_EXITED:
                if existing.attempt == request.attempt:
                    return hostagent_pb2.CreateResponse(vm=existing, created=False)
                abort_with_reason(
                    context, HostAgentErrorReason.ATTEMPT_CONFLICT, "other attempt"
                )
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
            return hostagent_pb2.CreateResponse(vm=vm, created=True)

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


class RunningFakeAgent:
    def __init__(
        self,
        agent: FakeHostAgent,
        server_credentials: grpc.ServerCredentials | None = None,
    ) -> None:
        self.agent = agent
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        hostagent_pb2_grpc.add_HostAgentServicer_to_server(agent, self.server)
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
