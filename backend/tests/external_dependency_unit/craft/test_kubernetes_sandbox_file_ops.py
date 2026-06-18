"""K8s file-ops + upload contract (real K8s).

Migrated from the deleted ``test_local_sandbox_file_ops.py`` and
``test_local_sandbox_upload.py``. Every assertion goes through the public
``SandboxManager`` API — no on-disk inspection — so the test pins the
contract that production code relies on.

Module is gated to the K8s CI lane via ``pytestmark`` (mirrors
``test_kubernetes_sandbox.py``).

Run with:

    SANDBOX_BACKEND=kubernetes python -m dotenv -f .vscode/.env run -- \\
        pytest backend/tests/external_dependency_unit/craft/test_kubernetes_sandbox_file_ops.py -v
"""

from __future__ import annotations

import time
from uuid import UUID
from uuid import uuid4

import pytest
from kubernetes import client

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import FilesystemEntry
from tests.external_dependency_unit.craft._test_helpers import default_llm_config
from tests.external_dependency_unit.craft.conftest import pod_exec
from tests.external_dependency_unit.craft.conftest import wait_for_pod_deletion

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_check_returns_true_for_provisioned_sandbox(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, _, _ = pool_session
        assert k8s_manager.health_check(sandbox_id, timeout=10.0) is True

    def test_health_check_returns_false_after_terminate(
        self,
        k8s_manager: KubernetesSandboxManager,
        k8s_client: client.CoreV1Api,
    ) -> None:
        sandbox_id = uuid4()
        info = k8s_manager.provision(
            sandbox_id=sandbox_id,
            user_id=UUID("ee0dd46a-23dc-4128-abab-6712b3f4464c"),
            tenant_id="tenant_test",
            llm_config=default_llm_config(),
            onyx_pat="ci-test-pat",
        )
        assert info.status == SandboxStatus.RUNNING

        # Block until pod is healthy before terminating, otherwise the test
        # races the pod-ready path.
        for _ in range(15):
            if k8s_manager.health_check(sandbox_id, timeout=5.0):
                break
            time.sleep(2)

        k8s_manager.terminate(sandbox_id)
        wait_for_pod_deletion(
            k8s_client, k8s_manager._get_pod_name(sandbox_id), SANDBOX_NAMESPACE
        )

        assert k8s_manager.health_check(sandbox_id, timeout=5.0) is False


# ---------------------------------------------------------------------------
# List directory
# ---------------------------------------------------------------------------


class TestListDirectory:
    def test_list_directory_returns_entries(
        self,
        k8s_manager: KubernetesSandboxManager,
        k8s_client: client.CoreV1Api,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, pod_name = pool_session
        outputs_dir = f"/workspace/sessions/{session_id}/outputs"
        pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"mkdir -p {outputs_dir}/subdir && echo content > {outputs_dir}/file.txt",
        )

        result = k8s_manager.list_directory(sandbox_id, session_id, "outputs")

        assert all(isinstance(e, FilesystemEntry) for e in result)
        entry_names = {e.name for e in result}
        assert "file.txt" in entry_names
        assert "subdir" in entry_names


# ---------------------------------------------------------------------------
# Read file
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_read_file_returns_contents(
        self,
        k8s_manager: KubernetesSandboxManager,
        k8s_client: client.CoreV1Api,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, pod_name = pool_session
        outputs_dir = f"/workspace/sessions/{session_id}/outputs"
        pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"mkdir -p {outputs_dir} && printf 'Hello, World!' > {outputs_dir}/test.txt",
        )

        result = k8s_manager.read_file(sandbox_id, session_id, "outputs/test.txt")
        assert result == b"Hello, World!"

    def test_read_file_strips_path_traversal_components(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        """``read_file`` silently strips ``..`` components — a relative path
        of ``../../etc/passwd`` collapses to ``etc/passwd`` inside the
        session root, which does not exist.
        """
        sandbox_id, session_id, _ = pool_session

        with pytest.raises(ValueError, match="File not found"):
            k8s_manager.read_file(sandbox_id, session_id, "../../etc/passwd")


# ---------------------------------------------------------------------------
# Delete file
# ---------------------------------------------------------------------------


class TestDeleteFile:
    def test_delete_file_removes_file(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, _ = pool_session
        # Round-trip via upload (the only public API to create a file the
        # delete path is allowed to target).
        k8s_manager.upload_file(sandbox_id, session_id, "test.txt", b"content")

        result = k8s_manager.delete_file(sandbox_id, session_id, "attachments/test.txt")
        assert result is True

        # And the file is genuinely gone — a second delete returns False.
        again = k8s_manager.delete_file(sandbox_id, session_id, "attachments/test.txt")
        assert again is False

    def test_delete_file_returns_false_for_missing(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, _ = pool_session

        result = k8s_manager.delete_file(
            sandbox_id, session_id, "attachments/nonexistent.txt"
        )
        assert result is False

    def test_delete_file_rejects_path_traversal(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, _ = pool_session

        with pytest.raises(ValueError, match="path traversal"):
            k8s_manager.delete_file(sandbox_id, session_id, "../../../etc/passwd")

    def test_delete_file_rejects_null_byte(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        """Null bytes must be rejected — pinned previously by
        ``test_path_sanitization.test_sanitize_path_passes_null_byte_through``
        (the local manager's per-endpoint layer caught them). The k8s
        manager rejects them in ``delete_file`` directly.
        """
        sandbox_id, session_id, _ = pool_session

        with pytest.raises(ValueError):
            k8s_manager.delete_file(
                sandbox_id, session_id, "attachments/foo\x00bar.txt"
            )

    def test_delete_file_rejects_shell_metacharacters(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, _ = pool_session

        with pytest.raises(ValueError):
            k8s_manager.delete_file(
                sandbox_id, session_id, "attachments/foo;rm -rf /.txt"
            )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestCreateSnapshot:
    """The full snapshot/restore round-trip lives in test_snapshot_restore.py.
    Here we pin the no-outputs short-circuit which the local manager could
    not exercise."""

    def test_create_snapshot_returns_none_when_session_has_no_outputs(
        self,
        k8s_manager: KubernetesSandboxManager,
        k8s_client: client.CoreV1Api,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, pod_name = pool_session

        # ``setup_session_workspace`` populates outputs/web/ with the Next.js
        # scaffold, so a freshly-set-up session is never literally empty.
        # Wipe the snapshot-eligible trees first to exercise the sidecar's
        # ``status="empty"`` short-circuit. (managed/* lives outside the
        # snapshot, so we don't need to clean it.)
        session_root = f"/workspace/sessions/{session_id}"
        pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"rm -rf {session_root}/outputs {session_root}/attachments "
            "2>/dev/null; true",
        )

        result = k8s_manager.create_snapshot(
            sandbox_id, session_id, tenant_id="tenant_test"
        )

        assert result is None


# ---------------------------------------------------------------------------
# Terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    def test_terminate_cleans_up_resources(
        self,
        k8s_manager: KubernetesSandboxManager,
        k8s_client: client.CoreV1Api,
    ) -> None:
        """``terminate`` deletes the pod (no exception, no left-over pod)."""
        sandbox_id = uuid4()
        k8s_manager.provision(
            sandbox_id=sandbox_id,
            user_id=UUID("ee0dd46a-23dc-4128-abab-6712b3f4464c"),
            tenant_id="tenant_test",
            llm_config=default_llm_config(),
            onyx_pat="ci-test-pat",
        )
        for _ in range(15):
            if k8s_manager.health_check(sandbox_id, timeout=5.0):
                break
            time.sleep(2)

        k8s_manager.terminate(sandbox_id)
        wait_for_pod_deletion(
            k8s_client, k8s_manager._get_pod_name(sandbox_id), SANDBOX_NAMESPACE
        )


# ---------------------------------------------------------------------------
# Upload file
# ---------------------------------------------------------------------------


class TestUploadFile:
    def test_upload_file_creates_file(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, _ = pool_session
        content = b"Hello, World!"

        result = k8s_manager.upload_file(sandbox_id, session_id, "test.txt", content)

        assert result == "attachments/test.txt"

        # Round-trip via read_file (public API) to verify contents landed.
        readback = k8s_manager.read_file(sandbox_id, session_id, "attachments/test.txt")
        assert readback == content

    def test_upload_file_handles_collision(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, _ = pool_session

        k8s_manager.upload_file(sandbox_id, session_id, "collide.txt", b"first")
        result = k8s_manager.upload_file(
            sandbox_id, session_id, "collide.txt", b"second"
        )

        assert result == "attachments/collide_1.txt"
        assert (
            k8s_manager.read_file(sandbox_id, session_id, "attachments/collide.txt")
            == b"first"
        )
        assert (
            k8s_manager.read_file(sandbox_id, session_id, "attachments/collide_1.txt")
            == b"second"
        )

    def test_upload_first_file_injects_agents_md_attachments_section(
        self,
        k8s_manager: KubernetesSandboxManager,
        k8s_client: client.CoreV1Api,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        """First upload injects the attachments section into AGENTS.md;
        subsequent uploads don't duplicate it. Pins
        ``_ensure_agents_md_attachments_section``.
        """
        sandbox_id, session_id, pod_name = pool_session
        agents_md_path = f"/workspace/sessions/{session_id}/AGENTS.md"
        section_marker = "## Attachments (PRIORITY)"

        before = pod_exec(
            k8s_client, pod_name, SANDBOX_NAMESPACE, f"cat {agents_md_path}"
        )
        assert section_marker not in before, (
            "precondition: AGENTS.md should not yet contain the attachments section"
        )

        k8s_manager.upload_file(sandbox_id, session_id, "first.txt", b"hello")
        after_first = pod_exec(
            k8s_client, pod_name, SANDBOX_NAMESPACE, f"cat {agents_md_path}"
        )
        assert section_marker in after_first, (
            "first upload must inject the attachments section into AGENTS.md"
        )

        k8s_manager.upload_file(sandbox_id, session_id, "second.txt", b"world")
        after_second = pod_exec(
            k8s_client, pod_name, SANDBOX_NAMESPACE, f"cat {agents_md_path}"
        )
        assert after_second.count(section_marker) == 1, (
            "second upload should not duplicate the attachments section; "
            f"got {after_second.count(section_marker)} occurrences"
        )


# ---------------------------------------------------------------------------
# Upload stats
# ---------------------------------------------------------------------------


class TestGetUploadStats:
    def test_get_upload_stats_empty(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, _ = pool_session

        file_count, total_size = k8s_manager.get_upload_stats(sandbox_id, session_id)

        assert file_count == 0
        # ``du -sb`` (the impl) counts the attachments directory's own inode
        # — typically 4 KiB on ext4 / overlayfs. Allow the empty-dir overhead;
        # we just care that no user data is present, which file_count pins.
        assert total_size < 16 * 1024

    def test_get_upload_stats_with_files(
        self,
        k8s_manager: KubernetesSandboxManager,
        pool_session: tuple[UUID, UUID, str],
    ) -> None:
        sandbox_id, session_id, _ = pool_session

        k8s_manager.upload_file(sandbox_id, session_id, "file1.txt", b"hello")  # 5
        k8s_manager.upload_file(sandbox_id, session_id, "file2.txt", b"world!")  # 6

        file_count, total_size = k8s_manager.get_upload_stats(sandbox_id, session_id)

        assert file_count == 2
        # du -sb reports the byte total of all files including any directory
        # overhead. The two files contribute 11 bytes; a small constant
        # overhead from the directory entry itself is acceptable.
        assert total_size >= 11
