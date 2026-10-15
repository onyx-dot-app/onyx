"""Real guest boundaries. Verify the Firecracker executable on the node separately."""

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from uuid import UUID, uuid4

import pytest
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

from onyx.server.features.build.sandbox.exec import ExecClient, FramedStdin
from onyx.server.features.build.sandbox.image.guest import PROTOCOL_VERSION
from onyx.server.features.build.sandbox.image.guest.security import GUEST_PYTHON
from onyx.server.features.build.sandbox.kubernetes_runtime import KubernetesRuntime
from onyx.server.features.build.sandbox.models import SandboxExecError
from onyx.server.features.build.user_library.api import UploadResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.tests.craft.k8s.networking.test_networking import (
    Sandbox,
    exec_guest,
    exec_guest_in_pod,
    exec_sandbox,
    kubectl,
    sandbox_namespace,
)
from tests.integration.tests.craft.k8s.networking.test_networking import (
    sandbox as sandbox,
)
from tests.integration.tests.craft.k8s.networking.test_networking import (
    test_direct_egress_is_blocked as test_direct_egress_is_blocked,
)
from tests.integration.tests.craft.k8s.networking.test_networking import (
    test_exact_api_exception_and_pat_injection as test_exact_api_exception_and_pat_injection,
)
from tests.integration.tests.craft.k8s.networking.test_networking import (
    test_upload_reaches_guest_filesystem as test_upload_reaches_guest_filesystem,
)
from tests.integration.tests.craft.user_library_http import (
    delete_user_library_file,
    upload_user_library_files,
)


class _HeldRestoreInput(BytesIO):
    def __init__(self) -> None:
        super().__init__(b"x")
        self.release = Event()
        self.waiting = Event()
        self.finished = Event()

    def read(self, size: int | None = -1, /) -> bytes:
        chunk = super().read(size)
        if chunk:
            return chunk
        self.waiting.set()
        try:
            if not self.release.wait(timeout=90):
                raise TimeoutError("held restore input was not released")
            return b""
        finally:
            self.finished.set()


def test_api_provisioning_preserves_single_container_runtime(
    sandbox: Sandbox, other_sandbox: Sandbox
) -> None:
    assert sandbox.owner.id != other_sandbox.owner.id
    assert sandbox.pod != other_sandbox.pod
    for instance in (sandbox, other_sandbox):
        pod = json.loads(
            kubectl(sandbox_namespace(), "get", "pod", instance.pod, "-o", "json")
        )
        assert pod["spec"]["runtimeClassName"] == "kata-fc"
        assert [container["name"] for container in pod["spec"]["containers"]] == [
            "sandbox"
        ]
        assert [container["name"] for container in pod["spec"]["initContainers"]] == [
            "sandbox-firewall"
        ]
        assert (
            "NET_ADMIN"
            not in pod["spec"]["containers"][0]["securityContext"]["capabilities"][
                "add"
            ]
        )
        assert json.loads(exec_guest(instance, "status", {})) == {
            "protocol": PROTOCOL_VERSION,
            "ready": True,
            "history_restored": True,
        }


def test_users_have_guest_kernels_distinct_from_each_other_and_nodes(
    sandbox: Sandbox, other_sandbox: Sandbox
) -> None:
    guest_boot_ids: list[UUID] = []
    for instance in (sandbox, other_sandbox):
        pod = json.loads(
            kubectl(sandbox_namespace(), "get", "pod", instance.pod, "-o", "json")
        )
        node = json.loads(
            kubectl(
                sandbox_namespace(),
                "get",
                "node",
                pod["spec"]["nodeName"],
                "-o",
                "json",
            )
        )
        boot_id = UUID(
            exec_sandbox(instance, "cat", "/proc/sys/kernel/random/boot_id").strip()
        )
        assert boot_id != UUID(node["status"]["nodeInfo"]["bootID"])
        guest_boot_ids.append(boot_id)
    assert guest_boot_ids[0] != guest_boot_ids[1]


def test_agent_has_no_capabilities_or_privilege_escalation(sandbox: Sandbox) -> None:
    status = json.loads(
        exec_sandbox(
            sandbox,
            "/opt/onyx-guest/venv/bin/python",
            "-I",
            "-c",
            "import json,os; fields=dict(line.split(':',1) for line in open('/proc/self/status')); "
            "print(json.dumps({'uid':os.getuid(),'gid':os.getgid(), **{key:fields[key].strip() "
            "for key in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb','NoNewPrivs')}}))",
        )
    )
    assert status["uid"] == status["gid"] == 1000
    for capability in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        assert int(status[capability], 16) == 0
    assert status["NoNewPrivs"] == "1"


def test_repeated_concurrent_provision_keeps_live_history(sandbox: Sandbox) -> None:
    boot_id = exec_sandbox(sandbox, "cat", "/proc/sys/kernel/random/boot_id").strip()
    marker = f"/workspace/opencode-data/reuse-{uuid4().hex}.txt"
    exec_sandbox(sandbox, "sh", "-c", 'printf history-proof > "$1"', "sh", marker)

    def create_session() -> int:
        response = client.post(
            f"{API_SERVER_URL}/build/sessions",
            json={"headless": True},
            headers=sandbox.owner.headers,
            cookies=sandbox.owner.cookies,
        )
        assert response.status_code in {200, 409, 503}, response.text
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as requests:
        statuses = list(requests.map(lambda _: create_session(), range(2)))
    assert 200 in statuses
    assert exec_sandbox(sandbox, "cat", marker) == "history-proof"
    assert (
        exec_sandbox(sandbox, "cat", "/proc/sys/kernel/random/boot_id").strip()
        == boot_id
    )


def test_guest_rejects_invalid_protocol_requests(sandbox: Sandbox) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        exec_guest(sandbox, "status", {"unexpected": True})
    with pytest.raises(subprocess.CalledProcessError):
        exec_guest(sandbox, "unknown-operation", {})
    assert json.loads(exec_guest(sandbox, "status", {}))["ready"] is True


@pytest.mark.parametrize(
    ("operation", "metadata"),
    [
        ("release-history", {}),
        ("push-managed", {"mount_path": "/workspace/managed/skills"}),
    ],
)
def test_agent_cannot_invoke_privileged_guest_operations(
    sandbox: Sandbox, operation: str, metadata: dict[str, object]
) -> None:
    with pytest.raises(subprocess.CalledProcessError) as failed:
        exec_sandbox(
            sandbox,
            *KubernetesRuntime.guest_command(operation, metadata),
        )
    assert "requires root" in failed.value.stderr


def test_agent_cannot_replace_helper_interpreter_or_ancestors(sandbox: Sandbox) -> None:
    paths = json.loads(
        exec_sandbox(
            sandbox,
            "/opt/onyx-guest/venv/bin/python",
            "-I",
            "-c",
            "import importlib.util,json,os,pathlib; roots=[pathlib.Path('/opt/onyx-guest/venv/bin/python'), "
            "pathlib.Path(importlib.util.find_spec('onyx_guest').origin)]; "
            "paths={path for root in roots for path in (root,root.resolve(),*root.parents,*root.resolve().parents)}; "
            "print(json.dumps([{'path':str(path),'uid':path.stat().st_uid,'writable':os.access(path,os.W_OK)} "
            "for path in paths]))",
        )
    )
    assert paths
    assert all(path["uid"] == 0 and not path["writable"] for path in paths), paths


def test_managed_library_is_readable_and_immutable_to_agent(sandbox: Sandbox) -> None:
    filename = f"guest-managed-{uuid4().hex}.txt"
    content = b"managed guest content"
    response = upload_user_library_files(
        sandbox.owner, [(filename, content, "text/plain")]
    )
    response.raise_for_status()
    uploaded = UploadResponse.model_validate(response.json())
    assert len(uploaded.entries) == 1
    path = f"/workspace/managed/user_library/{filename}"
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                assert exec_sandbox(sandbox, "cat", path).encode() == content
                break
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        output = exec_sandbox(
            sandbox,
            "sh",
            "-c",
            'if printf overwrite > "$1" 2>/dev/null; then echo writable; else echo denied; fi',
            "sh",
            path,
        )
        assert output.strip() == "denied"
        assert exec_sandbox(sandbox, "cat", path).encode() == content
    finally:
        delete_user_library_file(
            sandbox.owner, uploaded.entries[0].id
        ).raise_for_status()


def test_bootstrap_holds_serve_until_valid_history_release() -> None:
    namespace = sandbox_namespace()
    template = json.loads(
        kubectl(namespace, "get", "podtemplate", "sandbox-pod", "-o", "json")
    )
    name = f"guest-history-gate-{uuid4().hex[:12]}"
    pod = {"apiVersion": "v1", "kind": "Pod", **template["template"]}
    pod["metadata"] = {**pod["metadata"], "name": name, "namespace": namespace}
    pod["spec"]["containers"][0].setdefault("env", []).append(
        {"name": "OPENCODE_SERVER_PASSWORD", "value": "history-gate-test"}
    )
    kubectl(namespace, "create", "-f", "-", stdin=json.dumps(pod))
    try:
        deadline = time.monotonic() + 180
        while True:
            try:
                status = json.loads(exec_guest_in_pod(name, "status", {}))
                if status["ready"]:
                    break
            except subprocess.CalledProcessError:
                pass
            assert time.monotonic() < deadline, "Guest bootstrap did not become ready"
            time.sleep(1)
        assert status == {
            "protocol": PROTOCOL_VERSION,
            "ready": True,
            "history_restored": False,
        }
        probe: dict[str, object] = {
            "argv": [
                "/bin/sh",
                "-c",
                "touch /run/onyx/history-restored 2>/dev/null && echo writable || echo denied",
            ],
            "timeout_seconds": 10,
            "has_stdin": False,
        }
        probe_started = time.monotonic()
        try:
            permission = exec_guest_in_pod(name, "run", probe)
        except subprocess.CalledProcessError as error:
            error.add_note(
                f"Guest permission probe took {time.monotonic() - probe_started:.3f}s; "
                f"stdout={error.stdout!r}; stderr={error.stderr!r}"
            )
            raise
        assert permission.strip() == "denied"
        timeout_probe = """
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from onyx_guest.input import FramedInput
from onyx_guest.supervisor import HISTORY_RESTORED, release_history

def expire(_signum, _frame):
    raise TimeoutError('history restore probe alarm')

def effective_capabilities():
    fields = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
    return int(fields['CapEff'].strip(), 16)

assert os.getuid() == os.geteuid() == 0
assert effective_capabilities() == 0x1c1
assert not HISTORY_RESTORED.exists()
signal.signal(signal.SIGALRM, expire)
deadline = time.monotonic() + 1.0
signal.setitimer(signal.ITIMER_REAL, 1.0)
try:
    release_history(
        restore=True,
        source=FramedInput(os.fdopen(0, 'rb', buffering=0, closefd=False)),
        deadline=deadline,
    )
except (TimeoutError, subprocess.TimeoutExpired) as error:
    timeout_kind = type(error).__name__
else:
    raise AssertionError('history restore completed with held input')
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)

try:
    remaining_child = os.waitpid(-1, os.WNOHANG)
except ChildProcessError:
    pass
else:
    raise AssertionError(f'history restore child was not reaped: {remaining_child}')
assert not HISTORY_RESTORED.exists()
assert os.getuid() == os.geteuid() == 0
assert effective_capabilities() == 0x1c1
print(json.dumps({
    'probe': 'history-restore-timeout',
    'timeout': timeout_kind,
    'child_reaped': True,
    'history_restored': False,
    'uid': os.getuid(),
    'euid': os.geteuid(),
    'cap_eff': effective_capabilities(),
}), file=sys.stderr, flush=True)
raise SystemExit(7)
"""
        configuration = k8s_client.Configuration()
        k8s_config.load_kube_config(
            context=os.environ["SANDBOX_TEST_KUBE_CONTEXT"],
            client_configuration=configuration,
        )
        held_input = _HeldRestoreInput()
        try:
            with pytest.raises(SandboxExecError) as timed_out_restore:
                ExecClient(configuration, namespace).run(
                    name,
                    [GUEST_PYTHON, "-I", "-c", timeout_probe],
                    stdin=FramedStdin(held_input),
                    timeout=45,
                )
            assert held_input.waiting.is_set()
            assert not held_input.closed
            assert timed_out_restore.value.returncode == 7
            diagnostic = json.loads(timed_out_restore.value.stderr)
            assert diagnostic.pop("timeout") in {"TimeoutError", "TimeoutExpired"}
            assert diagnostic == {
                "probe": "history-restore-timeout",
                "child_reaped": True,
                "history_restored": False,
                "uid": 0,
                "euid": 0,
                "cap_eff": 0x1C1,
            }
        finally:
            held_input.release.set()
            released = not held_input.waiting.is_set() or held_input.finished.wait(
                timeout=10
            )
            held_input.close()
            assert released, "held restore source read did not finish"
        with pytest.raises(subprocess.CalledProcessError) as rejected_archive:
            exec_guest_in_pod(name, "restore-history", {}, stdin=b"invalid archive")
        assert "OpenCode history archive is unreadable" in rejected_archive.value.stderr
        assert not json.loads(exec_guest_in_pod(name, "status", {}))["history_restored"]
        current = json.loads(kubectl(namespace, "get", "pod", name, "-o", "json"))
        assert not any(
            condition["type"] == "Ready" and condition["status"] == "True"
            for condition in current["status"].get("conditions", [])
        )
        exec_guest_in_pod(name, "release-history", {})
        exec_guest_in_pod(name, "release-history", {})
        exec_guest_in_pod(
            name, "restore-history", {}, stdin=b"ignored after history release"
        )
        assert json.loads(exec_guest_in_pod(name, "status", {}))["history_restored"]
        kubectl(
            namespace,
            "wait",
            "--for=condition=Ready",
            f"pod/{name}",
            "--timeout=120s",
            timeout=130,
        )
    finally:
        kubectl(namespace, "delete", "pod", name, "--ignore-not-found", "--wait=false")
