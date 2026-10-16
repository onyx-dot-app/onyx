"""Sandbox file-ops tests in the Craft k8s integration lane."""

from __future__ import annotations

import os
import subprocess
import textwrap
from collections.abc import Callable
from uuid import UUID

import httpx
import pytest
from kubernetes import client

from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.sandbox.manager import (
    SandboxManager,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client as http_client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    OwnedLivePod,
    PoolSession,
    SandboxHandle,
    kubernetes_runtime,
    pod_exec,
    wait_for_pod_deletion,
    wait_until_healthy,
)


def _artifact_response(user: DATestUser, session_id: UUID, path: str) -> httpx.Response:
    return http_client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}/artifacts/{path}",
        headers=user.headers,
        cookies=user.cookies,
    )


class TestHealthCheck:
    def test_health_check_returns_true_for_provisioned_sandbox(
        self,
        k8s_manager: SandboxManager,
        pool_session: PoolSession,
    ) -> None:
        sandbox_id, _, _ = pool_session
        wait_until_healthy(k8s_manager, sandbox_id)

    def test_http_health_survives_exec_transport_failure(
        self,
        pool_session: PoolSession,
    ) -> None:
        """Only exec is fault-injected; Kubernetes readiness and HTTP remain real."""
        sandbox_id, _, pod_name = pool_session
        contract = textwrap.dedent(
            """\
            print("ONYX_HTTP_HEALTH_STAGE=imports", flush=True)
            try:
                import socket
                import sys
                from uuid import UUID

                from onyx.server.features.build.sandbox.kubernetes_runtime import KubernetesRuntime
                from onyx.server.features.build.sandbox.manager import SandboxManager
                from onyx.server.features.build.sandbox.models import SandboxExecError

                sandbox_id = UUID(sys.argv[1])
                pod_name = sys.argv[2]
                print("ONYX_HTTP_HEALTH_STAGE=manager", flush=True)
                manager = SandboxManager()
                print("ONYX_HTTP_HEALTH_STAGE=baseline", flush=True)
                assert manager.health_check(sandbox_id, timeout=10.0)
                print("ONYX_HTTP_HEALTH_STAGE=pod_before", flush=True)
                runtime = manager._runtime
                assert isinstance(runtime, KubernetesRuntime)
                before = runtime.get_pod(sandbox_id)
                assert before is not None
                assert before.metadata.name == pod_name
                assert before.metadata.uid

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unavailable:
                    unavailable.bind(("127.0.0.1", 0))
                    original_host = runtime._exec.configuration.host
                    runtime._exec.configuration.host = (
                        f"http://127.0.0.1:{unavailable.getsockname()[1]}"
                    )
                    try:
                        print("ONYX_HTTP_HEALTH_STAGE=exec_fault", flush=True)
                        try:
                            runtime._exec.run(pod_name, ["true"], timeout=1.0)
                        except SandboxExecError:
                            pass
                        else:
                            raise AssertionError("Exec transport did not fail")
                        print("ONYX_HTTP_HEALTH_STAGE=health_during_fault", flush=True)
                        assert manager.health_check(sandbox_id, timeout=10.0)
                        print("ONYX_HTTP_HEALTH_STAGE=pod_after", flush=True)
                        after = runtime.get_pod(sandbox_id)
                        assert after is not None
                        assert after.metadata.name == pod_name
                        assert after.metadata.uid == before.metadata.uid
                        assert after.metadata.deletion_timestamp is None
                    finally:
                        runtime._exec.configuration.host = original_host
                print("ONYX_HTTP_HEALTH_STAGE=done", flush=True)
            except Exception as error:
                print(f"ONYX_HTTP_HEALTH_EXCEPTION={type(error).__name__}", flush=True)
                raise
            """
        )
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
                str(sandbox_id),
                pod_name,
            ],
            capture_output=True,
            text=True,
            timeout=60.0,
            check=False,
        )
        stages = (
            "imports",
            "manager",
            "baseline",
            "pod_before",
            "exec_fault",
            "health_during_fault",
            "pod_after",
            "done",
        )
        markers = {f"ONYX_HTTP_HEALTH_STAGE={stage}": stage for stage in stages}
        observed_stages = [
            markers[line] for line in result.stdout.splitlines() if line in markers
        ]
        last_stage = observed_stages[-1] if observed_stages else "unreported"
        exception_class = "unreported"
        for line in result.stdout.splitlines():
            if line.startswith("ONYX_HTTP_HEALTH_EXCEPTION="):
                candidate = line.removeprefix("ONYX_HTTP_HEALTH_EXCEPTION=")
                exception_class = (
                    candidate
                    if candidate.isidentifier() and len(candidate) <= 80
                    else "unknown"
                )
        if result.returncode != 0 or last_stage != "done":
            pytest.fail(
                f"In-cluster HTTP health contract failed with exit {result.returncode} "
                f"at stage {last_stage} with exception {exception_class}",
                pytrace=False,
            )

    def test_health_check_returns_false_after_terminate(
        self,
        k8s_manager: SandboxManager,
        k8s_client: client.CoreV1Api,
        owned_live_pod: OwnedLivePod,
    ) -> None:
        sandbox_id = owned_live_pod.sandbox_id
        pod_name = owned_live_pod.pod_name

        wait_until_healthy(k8s_manager, sandbox_id)

        k8s_manager.terminate(sandbox_id)
        wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)

        # Pod is gone, so health_check hits a kube-API 404 (no pod-IP HTTP).
        assert k8s_manager.health_check(sandbox_id, timeout=5.0) is False


class TestListDirectory:
    def test_list_directory_api_returns_entries(
        self,
        k8s_client: client.CoreV1Api,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        # Listing the session root fails ``ls -laL`` on the user_library symlink;
        # list a subpath under outputs/ instead.
        outputs_dir = f"/workspace/sessions/{handle.session_id}/outputs"
        runtime = kubernetes_runtime(handle.manager)
        pod_exec(
            k8s_client,
            runtime.pod_name(handle.sandbox_id),
            SANDBOX_NAMESPACE,
            f"mkdir -p {outputs_dir}/subdir && echo content > {outputs_dir}/file.txt",
        )

        result = BuildSessionManager.list_files(
            handle.api_user,
            handle.session_id,
            "outputs",
        )

        entry_names = {entry.name for entry in result.entries}
        assert "file.txt" in entry_names
        assert "subdir" in entry_names


class TestReadFile:
    def test_download_artifact_api_returns_contents(
        self,
        k8s_client: client.CoreV1Api,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        outputs_dir = f"/workspace/sessions/{handle.session_id}/outputs"
        runtime = kubernetes_runtime(handle.manager)
        pod_exec(
            k8s_client,
            runtime.pod_name(handle.sandbox_id),
            SANDBOX_NAMESPACE,
            f"mkdir -p {outputs_dir} && printf 'Hello, World!' > {outputs_dir}/test.txt",
        )

        result = BuildSessionManager.download_artifact(
            handle.api_user,
            handle.session_id,
            "outputs/test.txt",
        )
        assert result == b"Hello, World!"


class TestDeleteFile:
    def test_delete_file_api_removes_file(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        upload = BuildSessionManager.upload_file(
            handle.api_user,
            handle.session_id,
            "test.txt",
            b"content",
        )
        path = str(upload.path)

        BuildSessionManager.delete_file(handle.api_user, handle.session_id, path)

        response = _artifact_response(handle.api_user, handle.session_id, path)
        assert response.status_code == 404


class TestCreateSnapshot:
    def test_create_snapshot_returns_none_when_session_has_no_outputs(
        self,
        k8s_client: client.CoreV1Api,
        pool_session: PoolSession,
        pool_api_user: DATestUser,
    ) -> None:
        _sandbox_id, session_id, pod_name = pool_session

        session_root = f"/workspace/sessions/{session_id}"
        pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"rm -rf {session_root}/outputs {session_root}/attachments "
            "2>/dev/null; true",
        )

        assert BuildSessionManager.create_snapshot(pool_api_user, session_id) is None


class TestTerminate:
    def test_terminate_cleans_up_resources(
        self,
        k8s_manager: SandboxManager,
        k8s_client: client.CoreV1Api,
        owned_live_pod: OwnedLivePod,
    ) -> None:
        sandbox_id = owned_live_pod.sandbox_id
        pod_name = owned_live_pod.pod_name

        wait_until_healthy(k8s_manager, sandbox_id)

        k8s_manager.terminate(sandbox_id)
        wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)


class TestUploadFile:
    def test_binary_upload_download_round_trip(
        self,
        pool_api_user: DATestUser,
        pool_session: PoolSession,
    ) -> None:
        _, session_id, _ = pool_session
        content = bytes(range(256)) * 4096
        uploaded = BuildSessionManager.upload_file(
            pool_api_user, session_id, "binary-proof.bin", content
        )
        downloaded = BuildSessionManager.download_artifact(
            pool_api_user, session_id, uploaded.path
        )
        assert downloaded == content

    def test_upload_file_api_creates_file(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        content = b"Hello, World!"

        result = BuildSessionManager.upload_file(
            handle.api_user,
            handle.session_id,
            "test.txt",
            content,
        )

        assert result.path == "attachments/test.txt"

        readback = BuildSessionManager.download_artifact(
            handle.api_user,
            handle.session_id,
            "attachments/test.txt",
        )
        assert readback == content

    def test_upload_file_api_handles_collision(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        BuildSessionManager.upload_file(
            handle.api_user,
            handle.session_id,
            "collide.txt",
            b"first",
        )
        result = BuildSessionManager.upload_file(
            handle.api_user,
            handle.session_id,
            "collide.txt",
            b"second",
        )

        assert result.path == "attachments/collide_1.txt"
        assert (
            BuildSessionManager.download_artifact(
                handle.api_user,
                handle.session_id,
                "attachments/collide.txt",
            )
            == b"first"
        )
        assert (
            BuildSessionManager.download_artifact(
                handle.api_user,
                handle.session_id,
                "attachments/collide_1.txt",
            )
            == b"second"
        )

    def test_upload_first_file_injects_agents_md_attachments_section(
        self,
        k8s_client: client.CoreV1Api,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        pod_name = kubernetes_runtime(handle.manager).pod_name(handle.sandbox_id)
        agents_md_path = f"/workspace/sessions/{handle.session_id}/AGENTS.md"
        section_marker = "## Attachments (PRIORITY)"

        before = pod_exec(
            k8s_client, pod_name, SANDBOX_NAMESPACE, f"cat {agents_md_path}"
        )
        assert section_marker not in before, (
            "precondition: AGENTS.md should not yet contain the attachments section"
        )

        BuildSessionManager.upload_file(
            handle.api_user,
            handle.session_id,
            "first.txt",
            b"hello",
        )
        after_first = pod_exec(
            k8s_client, pod_name, SANDBOX_NAMESPACE, f"cat {agents_md_path}"
        )
        assert section_marker in after_first, (
            "first upload must inject the attachments section into AGENTS.md"
        )
        assert "## Skills" not in after_first
        assert after_first.index(section_marker) < after_first.index(
            "## Connectable apps"
        )

        BuildSessionManager.upload_file(
            handle.api_user,
            handle.session_id,
            "second.txt",
            b"world",
        )
        after_second = pod_exec(
            k8s_client, pod_name, SANDBOX_NAMESPACE, f"cat {agents_md_path}"
        )
        assert after_second.count(section_marker) == 1, (
            "second upload should not duplicate the attachments section; "
            f"got {after_second.count(section_marker)} occurrences"
        )


class TestUploadStats:
    def test_get_upload_stats_counts_and_sizes_attachments(
        self,
        k8s_manager: SandboxManager,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """``get_upload_stats`` reports the real (count, total_bytes) of a
        session's attachments, queried in-pod via kube-exec."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        session_id = handle.session_id

        # No attachments directory exists until the first upload.
        assert k8s_manager.get_upload_stats(handle.sandbox_id, session_id) == (0, 0)

        first = b"hello"
        second = b"world!!"
        BuildSessionManager.upload_file(handle.api_user, session_id, "a.txt", first)
        BuildSessionManager.upload_file(handle.api_user, session_id, "b.txt", second)

        # find -type f counts the two files; du -sb sums their bytes exactly
        assert k8s_manager.get_upload_stats(handle.sandbox_id, session_id) == (
            2,
            len(first) + len(second),
        )
