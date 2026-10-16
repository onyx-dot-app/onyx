"""Session provisioning API tests in the Craft k8s integration lane."""

from __future__ import annotations

import os
import subprocess
import textwrap
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from kubernetes import client

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import (
    SANDBOX_NAMESPACE,
)
from onyx.server.features.build.sandbox.manager import (
    SandboxManager,
)
from onyx.server.features.build.session.models import DetailedSessionResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client as http_client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    OwnedLivePod,
    cleanup_api_user_sandbox,
    kubernetes_runtime,
    register_suite_sandbox,
)


def test_create_session_provisions_running_sandbox_pod_via_api(
    k8s_manager: SandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    api_user = UserManager.create(name=f"craft-k8s-session-smoke-{uuid4().hex[:8]}")
    sandbox_id: UUID | None = None
    try:
        response = http_client.post(
            f"{API_SERVER_URL}/build/sessions",
            json={"headless": True},
            headers=api_user.headers,
            cookies=api_user.cookies,
        )
        assert response.status_code == 200, (
            f"POST /build/sessions failed: {response.status_code} "
            f"{response.reason_phrase}; body={response.text[:2000]!r}; "
            f"user_id={api_user.id}"
        )
        session = DetailedSessionResponse.model_validate(response.json())
        sandbox = session.sandbox
        assert sandbox is not None
        sandbox_id = UUID(sandbox.id)
        register_suite_sandbox(sandbox_id)
        assert sandbox.status == SandboxStatus.RUNNING
        pod_name = kubernetes_runtime(k8s_manager).pod_name(sandbox_id)
        pod = k8s_client.read_namespaced_pod(
            name=pod_name,
            namespace=SANDBOX_NAMESPACE,
        )
        assert pod.status is not None
        assert pod.status.phase == "Running"
        assert pod.spec is not None
        assert pod.spec.runtime_class_name == "kata-fc"
    finally:
        cleanup_api_user_sandbox(k8s_manager, k8s_client, UUID(api_user.id), sandbox_id)


def test_api_pod_preserves_repeated_managed_archive_input(
    k8s_client: client.CoreV1Api,
    owned_live_pod: OwnedLivePod,
    record_property: Callable[[str, object], None],
) -> None:
    before = k8s_client.read_namespaced_pod(
        name=owned_live_pod.pod_name, namespace=SANDBOX_NAMESPACE
    )
    if before.metadata is None or before.spec is None or before.status is None:
        pytest.fail(
            "Owned sandbox identity is incomplete before transfer", pytrace=False
        )
    before_uid = before.metadata.uid
    before_runtime_class = before.spec.runtime_class_name
    before_containers = [
        (status.name, status.container_id)
        for status in before.status.container_statuses or []
    ]
    assert before_uid
    assert before_runtime_class == "kata-fc"
    assert len(before_containers) == 1
    assert before_containers[0][0] == "sandbox"
    assert before_containers[0][1]
    contract = textwrap.dedent(
        """\
        import signal

        signal.alarm(110)

        import hashlib
        import sys
        import time
        from uuid import UUID

        from onyx.server.features.build.sandbox.image.guest.security import GUEST_PYTHON
        from onyx.server.features.build.sandbox.manager import SandboxManager, _StatusOk, _build_targz

        iteration = 0
        try:
            manager = SandboxManager()
            sandbox_id = UUID(sys.argv[1])
            payload = hashlib.shake_256(b"onyx-push-managed-proof-v1").digest(1024 * 1024)
            archive = _build_targz({"payload.bin": payload})
            if len(archive) < len(payload):
                raise ValueError("managed archive compressed below file size")
            mount = f"/workspace/managed/document-preview/transport-proof-{sandbox_id.hex}"
            expected = "1048576 2f5a08e97472f6373ff0a2a5c67f77e52d31190aeb7aa7bfb3b637c0bdec4238\\n"
            child = (
                "import hashlib, pathlib, sys; data = pathlib.Path(sys.argv[1]).read_bytes(); "
                "print(len(data), hashlib.sha256(data).hexdigest())"
            )
            deadline = time.monotonic() + 100.0
            for iteration in range(1, 65):
                print(f"ONYX_API_MANAGED_ITERATION={iteration}", flush=True)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("API managed input loop budget expired")
                print("ONYX_API_MANAGED_PHASE=push", flush=True)
                receipt = manager._guest_json(
                    sandbox_id, "push-managed", _StatusOk, {"mount_path": mount},
                    stdin=archive, timeout=min(20.0, remaining),
                )
                if receipt.status != "ok":
                    raise ValueError("managed input status mismatch")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("API managed input loop budget expired")
                print("ONYX_API_MANAGED_PHASE=readback", flush=True)
                output = manager._run(
                    sandbox_id, [GUEST_PYTHON, "-I", "-c", child, f"{mount}/payload.bin"],
                    timeout=min(20.0, remaining),
                )
                if output != expected:
                    raise ValueError("managed file receipt mismatch")
            print(f"ONYX_API_MANAGED_ARCHIVE_BYTES={len(archive)}", flush=True)
            print("ONYX_API_MANAGED_OK=64", flush=True)
        except Exception as error:
            print(f"ONYX_API_MANAGED_EXCEPTION={type(error).__name__}", flush=True)
            sys.exit(1)
        """
    )
    try:
        result = subprocess.run(
            [
                "kubectl",
                "--context",
                os.environ["SANDBOX_TEST_KUBE_CONTEXT"],
                "--namespace",
                os.environ["HELM_RELEASE_NAMESPACE"],
                "exec",
                "deployment/onyx-api-server",
                "--",
                "python",
                "-c",
                contract,
                str(owned_live_pod.sandbox_id),
            ],
            capture_output=True,
            text=True,
            timeout=120.0,
            check=False,
        )
        stdout = result.stdout
        outcome = str(result.returncode)
    except subprocess.TimeoutExpired as error:
        captured = error.stdout or b""
        stdout = (
            captured.decode(errors="replace")
            if isinstance(captured, bytes)
            else captured
        )
        outcome = "TimeoutExpired"
    iterations = {
        f"ONYX_API_MANAGED_ITERATION={number}": number for number in range(1, 65)
    }
    iteration = 0
    archive_bytes = 0
    phase = "unreported"
    phases = {
        "ONYX_API_MANAGED_PHASE=push": "push",
        "ONYX_API_MANAGED_PHASE=readback": "readback",
    }
    exception_class = "unreported"
    lines = stdout.splitlines()
    for line in lines:
        if line in iterations:
            iteration = iterations[line]
            phase = "unreported"
        elif line in phases:
            phase = phases[line]
        elif line.startswith("ONYX_API_MANAGED_ARCHIVE_BYTES="):
            candidate = line.removeprefix("ONYX_API_MANAGED_ARCHIVE_BYTES=")
            if candidate.isascii() and candidate.isdecimal() and len(candidate) <= 8:
                size = int(candidate)
                if 1048576 <= size <= 2097152:
                    archive_bytes = size
        elif line.startswith("ONYX_API_MANAGED_EXCEPTION="):
            candidate = line.removeprefix("ONYX_API_MANAGED_EXCEPTION=")
            if (
                candidate.isidentifier()
                and candidate.isascii()
                and len(candidate) <= 80
            ):
                exception_class = candidate
    if outcome != "0" or "ONYX_API_MANAGED_OK=64" not in lines or archive_bytes == 0:
        pytest.fail(
            f"In-cluster managed archive input failed with exit {outcome} "
            f"at iteration {iteration}/64 with exception {exception_class}; phase={phase}",
            pytrace=False,
        )
    after = k8s_client.read_namespaced_pod(
        name=owned_live_pod.pod_name, namespace=SANDBOX_NAMESPACE
    )
    if after.metadata is None or after.spec is None or after.status is None:
        pytest.fail(
            "Owned sandbox identity is incomplete after transfer", pytrace=False
        )
    after_uid = after.metadata.uid
    after_runtime_class = after.spec.runtime_class_name
    after_deletion_timestamp = after.metadata.deletion_timestamp
    after_containers = [
        (status.name, status.container_id)
        for status in after.status.container_statuses or []
    ]
    assert after_uid == before_uid
    assert after_deletion_timestamp is None
    assert after_runtime_class == before_runtime_class
    assert after_containers == before_containers
    record_property("api_managed_completed_transfers", 64)
    record_property("api_managed_file_bytes", 1048576)
    record_property(
        "api_managed_file_sha256",
        "2f5a08e97472f6373ff0a2a5c67f77e52d31190aeb7aa7bfb3b637c0bdec4238",
    )
    record_property("api_managed_archive_bytes", archive_bytes)
    record_property("api_managed_pod_uid", after_uid)
    record_property("api_managed_container_id", after_containers[0][1])
