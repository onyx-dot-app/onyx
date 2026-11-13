"""Developer VM commands that run inside an api-server pod (`craft_fc_vm.py`).

`craft_fc_vm.py` sends this file through `kubectl exec -i ... python -c BOOT`.
Stdin: one JSON request line, then `payload_bytes` bytes of payload. The pod
already has the agent mTLS files, Postgres, Redis and the agent network path.
Every result line starts with `RESULT_PREFIX`; other output is log noise.

It acts only on the sandbox of the user named in the request.
"""

import codecs
import json
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from onyx.microvm.agent_client import HostAgentClientFactory
    from onyx.microvm.models import PlacedVm
    from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
        FirecrackerHarnessSandbox,
    )

RESULT_PREFIX = "@@craft-fc "
MOUNT_PATHS = {
    "skills": "/mnt/skills",
    "user-uploads": "/mnt/user-uploads",
    "spaces": "/mnt/spaces",
}
EXEC_DEADLINE_SECONDS = 600.0


class HelperError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def emit(**fields: Any) -> None:
    sys.stdout.write(RESULT_PREFIX + json.dumps(fields, default=str) + "\n")
    sys.stdout.flush()


def _tenant_for(email: str, requested: str | None) -> str:
    from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA

    if requested:
        return requested
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA
    from ee.onyx.db.user_tenant_mapping import get_tenant_id_for_email

    return get_tenant_id_for_email(email)


class Target:
    """The user's sandbox and, when one runs, its VM."""

    def __init__(self, email: str, tenant_id: str | None) -> None:
        from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
        from onyx.db.engine.sql_engine import get_session_with_tenant
        from onyx.db.users import get_user_by_email
        from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id

        self.email = email
        self.tenant_id = _tenant_for(email, tenant_id)
        with get_session_with_tenant(tenant_id=self.tenant_id) as db:
            user = get_user_by_email(email, db)
            if user is None:
                raise HelperError(
                    "NO_USER", f"no user {email} in tenant {self.tenant_id}"
                )
            sandbox = get_sandbox_by_user_id(db, user.id)
            if sandbox is None:
                raise HelperError(
                    "NO_SANDBOX",
                    f"{email} has no sandbox yet; open Craft once as this user",
                )
            self.sandbox_id: UUID = sandbox.id
            self.attempt_floor: int = sandbox.provisioning_attempt_number or 1
        self.shared_cache = get_shared_cache_backend()
        self.tenant_cache = get_cache_backend(tenant_id=self.tenant_id)
        self._factory: "HostAgentClientFactory | None" = None

    def harness(self) -> "FirecrackerHarnessSandbox":
        from onyx.server.features.build.sandbox.harness_factory import (
            get_harness_sandbox,
        )

        sandbox = get_harness_sandbox()
        from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
            FirecrackerHarnessSandbox,
        )

        if not isinstance(sandbox, FirecrackerHarnessSandbox):
            raise HelperError(
                "NOT_FIRECRACKER", "the deployment has no Firecracker harness"
            )
        return sandbox

    def factory(self) -> "HostAgentClientFactory":
        from onyx.microvm.agent_client import MtlsHostAgentClientFactory

        if self._factory is None:
            self._factory = MtlsHostAgentClientFactory()
        return self._factory

    def wake(self) -> None:
        from onyx.server.features.build.sandbox.models import HarnessSandboxRef

        self.harness().ensure_running(
            HarnessSandboxRef(
                tenant_id=self.tenant_id,
                sandbox_id=self.sandbox_id,
                session_id=uuid4(),
                attempt=max(self.attempt_floor, 1),
            )
        )

    def describe(self) -> dict[str, Any]:
        """Placement record joined with the agent's view of the VM."""
        from onyx.microvm.placement import find_vm
        from onyx.microvm.registry import get_registered_node, get_sandbox_placement
        from onyx.server.features.build.sandbox.firecracker.harness_state import (
            has_marks,
        )

        info: dict[str, Any] = {
            "user": self.email,
            "tenant_id": self.tenant_id,
            "sandbox_id": str(self.sandbox_id),
            "placed": False,
        }
        placement = get_sandbox_placement(self.tenant_cache, self.sandbox_id)
        if placement is None:
            return info
        now = int(time.time())
        info.update(
            placed=True,
            node=placement.node_id,
            attempt=placement.attempt,
            generation=placement.generation,
            idle_s=max(now - placement.last_active, 0),
            busy_marks=has_marks(self.tenant_cache, self.sandbox_id),
        )
        node = get_registered_node(self.shared_cache, placement.node_id)
        if node is None:
            info["state"] = "node_not_registered"
            return info
        vm = find_vm(
            self.factory().client(node.address).list_vms(),
            self.sandbox_id,
            placement.generation,
        )
        if vm is None:
            info["state"] = "missing_on_node"
            return info
        info.update(
            state=vm.state.value,
            template=vm.template,
            vcpus=vm.vcpus,
            mem_mib=vm.mem_mib,
            age_s=(now - int(vm.started_at.timestamp())) if vm.started_at else None,
        )
        return info

    def placed(self, wake: bool) -> "PlacedVm":
        """The running VM as a PlacedVm; wakes it only when asked."""
        from onyx.microvm.models import PlacedVm
        from onyx.microvm.placement import find_vm
        from onyx.microvm.registry import (
            get_registered_node,
            get_sandbox_daemon_key,
            get_sandbox_placement,
        )

        if wake:
            self.wake()
        placement = get_sandbox_placement(self.tenant_cache, self.sandbox_id)
        node = (
            None
            if placement is None
            else get_registered_node(self.shared_cache, placement.node_id)
        )
        if placement is None or node is None:
            raise HelperError(
                "NO_VM", f"{self.email} has no running VM; run again with --wake"
            )
        vm = find_vm(
            self.factory().client(node.address).list_vms(),
            self.sandbox_id,
            placement.generation,
        )
        if vm is None or vm.attempt != placement.attempt or not vm.state.is_live():
            raise HelperError(
                "NO_VM", f"{self.email} has no running VM; run again with --wake"
            )
        key = get_sandbox_daemon_key(
            self.tenant_cache, self.sandbox_id, attempt=vm.attempt
        )
        if key is None:
            raise HelperError("NO_KEY", "the VM has no stored daemon key")
        return PlacedVm(node=node, vm=vm, created=False, sandboxd_key=key)


class StreamText:
    """UTF-8 text per output stream; a character split across chunks stays whole."""

    def __init__(self, on_output: Callable[[str, str], None]) -> None:
        self.on_output = on_output
        self.decoders: dict[str, codecs.IncrementalDecoder] = {}

    def feed(self, stream: str, data: bytes) -> None:
        decoder = self.decoders.setdefault(
            stream, codecs.getincrementaldecoder("utf-8")(errors="replace")
        )
        if out := decoder.decode(data):
            self.on_output(stream, out)

    def flush(self) -> None:
        for stream, decoder in self.decoders.items():
            if out := decoder.decode(b"", final=True):
                self.on_output(stream, out)


def _run(
    target: Target,
    placed: "PlacedVm",
    argv: list[str],
    cwd: str,
    on_output: Callable[[str, str], None],
) -> dict[str, Any]:
    from onyx.microvm.lifecycle import sandbox_daemon, touch_sandbox_vm
    from onyx.microvm.models import ExecCommand, ExecGap, ExecOutput, ExecResult

    touch_sandbox_vm(target.tenant_cache, placed)
    daemon = sandbox_daemon(target.factory(), placed)
    result: dict[str, Any] = {}
    text = StreamText(on_output)
    for event in daemon.run(
        ExecCommand(argv=argv, cwd=cwd, deadline_seconds=EXEC_DEADLINE_SECONDS)
    ):
        if isinstance(event, ExecOutput):
            text.feed(event.stream.value.lower(), event.data)
        elif isinstance(event, ExecGap):
            on_output("stderr", f"[{event.end - event.start} bytes dropped]\n")
        elif isinstance(event, ExecResult):
            result = {
                "completion": event.completion.value,
                "exit_code": event.exit_code,
                "signal": event.signal,
            }
    text.flush()
    return result


def cmd_vms(target: Target, _req: dict[str, Any], _payload: bytes) -> None:
    emit(t="vms", vms=[target.describe()])


def cmd_where(target: Target, _req: dict[str, Any], _payload: bytes) -> None:
    emit(t="where", **target.describe())


def cmd_exec(target: Target, req: dict[str, Any], _payload: bytes) -> None:
    placed = target.placed(bool(req.get("wake")))
    result = _run(
        target,
        placed,
        ["bash", "-c", req["command"]],
        req.get("cwd") or "",
        lambda stream, data: emit(t="out", s=stream, d=data),
    )
    emit(t="result", **result)


def cmd_skills_push(target: Target, req: dict[str, Any], payload: bytes) -> None:
    from onyx.microvm.models import VmInstance

    mount = req.get("mount") or "skills"
    if mount not in MOUNT_PATHS:
        raise HelperError("BAD_MOUNT", f"unknown mount {mount}")
    placed = target.placed(bool(req.get("wake")))
    agent = target.factory().client(placed.node.address)
    put = agent.put_managed_image(payload)
    swapped = agent.swap_managed(
        image_id=put.image.image_id,
        targets=[
            VmInstance(
                sandbox_id=placed.vm.sandbox_id,
                attempt=placed.vm.attempt,
                generation=placed.vm.generation,
                sandboxd_key=placed.sandboxd_key,
            )
        ],
        mount=mount,
    )[0]
    if not swapped.ok:
        reason = swapped.reason.value if swapped.reason else "UNKNOWN"
        raise HelperError(reason, f"swap failed: {reason}: {swapped.message}")
    listing: list[str] = []
    _run(
        target,
        placed,
        ["ls", "-la", MOUNT_PATHS[mount]],
        "",
        lambda _stream, data: listing.append(data),
    )
    emit(
        t="pushed",
        sandbox_id=placed.vm.sandbox_id,
        node=placed.node.node_id,
        image_id=put.image.image_id,
        built=put.built,
        build_ms=put.build_ms,
        files=put.image.files,
        mount=mount,
        path=MOUNT_PATHS[mount],
        active=swapped.active.value,
        changed=swapped.changed,
        swap_ms=swapped.ms,
        previous_in_use=swapped.previous_in_use,
        listing="".join(listing),
    )


def cmd_reset(target: Target, req: dict[str, Any], _payload: bytes) -> None:
    from onyx.microvm.lifecycle import SandboxCheckpointer, stop_sandbox_vm
    from onyx.microvm.models import AgentVm

    class SkipSave(SandboxCheckpointer):
        def save_checkpoint(
            self,
            *,
            tenant_id: str,  # noqa: ARG002
            sandbox_id: UUID,  # noqa: ARG002
            vm: AgentVm,  # noqa: ARG002
            renew_lease: Callable[[], None],  # noqa: ARG002
        ) -> bool:
            return True

    harness = target.harness()
    checkpointer: SandboxCheckpointer | None = (
        SkipSave() if req.get("force") else harness.session_checkpointer()
    )
    if checkpointer is None:
        raise HelperError(
            "NO_SAVES",
            "session saves are off in this deployment; use --force to stop without a save",
        )
    outcome = stop_sandbox_vm(
        target.shared_cache,
        target.tenant_cache,
        target.factory(),
        checkpointer,
        tenant_id=target.tenant_id,
        sandbox_id=target.sandbox_id,
    )
    emit(t="reset", sandbox_id=str(target.sandbox_id), outcome=outcome.value)


COMMANDS: dict[str, Callable[[Target, dict[str, Any], bytes], None]] = {
    "vms": cmd_vms,
    "where": cmd_where,
    "exec": cmd_exec,
    "skills-push": cmd_skills_push,
    "reset": cmd_reset,
}


def main() -> int:
    stream = sys.stdin.buffer
    req = json.loads(stream.readline())
    size = int(req.get("payload_bytes", 0))
    payload = stream.read(size) if size else b""
    if len(payload) != size:
        emit(t="error", code="SHORT_PAYLOAD", message="stdin ended early")
        return 2
    from onyx.db.engine.sql_engine import SqlEngine

    SqlEngine.init_engine(pool_size=2, max_overflow=0)
    try:
        handler = COMMANDS[req["command_name"]]
        handler(Target(req["user"], req.get("tenant_id")), req, payload)
    except HelperError as e:
        emit(t="error", code=e.code, message=str(e))
        return 3
    except Exception as e:  # noqa: BLE001 - report any failure as one result line
        emit(t="error", code=type(e).__name__, message=str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
