"""Sandbox file-ops tests in the Craft k8s integration lane."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import httpx
import pytest
from kubernetes import client

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client as http_client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import OwnedLivePod
from tests.integration.tests.craft.k8s.k8s_fixtures import pod_exec
from tests.integration.tests.craft.k8s.k8s_fixtures import PoolSession
from tests.integration.tests.craft.k8s.k8s_fixtures import SandboxHandle
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_for_pod_deletion
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_until_healthy

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
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
        k8s_manager: KubernetesSandboxManager,
        pool_session: PoolSession,
    ) -> None:
        sandbox_id, _, _ = pool_session
        wait_until_healthy(k8s_manager, sandbox_id)

    def test_health_check_returns_false_after_terminate(
        self,
        k8s_manager: KubernetesSandboxManager,
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
        pod_exec(
            k8s_client,
            handle.manager._get_pod_name(handle.sandbox_id),
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
        pod_exec(
            k8s_client,
            handle.manager._get_pod_name(handle.sandbox_id),
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

        # Wipe snapshot-eligible trees so the session is truly empty (setup
        # scaffolds outputs/web/).
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
        k8s_manager: KubernetesSandboxManager,
        k8s_client: client.CoreV1Api,
        owned_live_pod: OwnedLivePod,
    ) -> None:
        sandbox_id = owned_live_pod.sandbox_id
        pod_name = owned_live_pod.pod_name

        wait_until_healthy(k8s_manager, sandbox_id)

        k8s_manager.terminate(sandbox_id)
        wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)


class TestUploadFile:
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
        pod_name = handle.manager._get_pod_name(handle.sandbox_id)
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
        k8s_manager: KubernetesSandboxManager,
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
