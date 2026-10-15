"""Restore a generated Next preview after its owned Firecracker VM disappears."""

from __future__ import annotations

import hashlib
import io
import json
import shlex
import tarfile
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from kubernetes import client

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import BuildSessionStatus, SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.sandbox.manager import SandboxManager
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from shared_configs.contextvars import get_current_tenant_id
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    OwnedLivePod,
    pod_exec,
    session_webapp_logs,
    start_session_webapp,
    wait_for_pod_deletion,
)
from tests.integration.tests.craft.webapp_preview import (
    WEBAPP_INSTALLED,
    proxy_get,
    wait_for_webapp_ready,
    webapp_install_check_command,
)


def test_owned_pod_loss_restores_generated_next_preview_and_opencode_identity(
    k8s_manager: SandboxManager,
    k8s_client: client.CoreV1Api,
    owned_live_pod: OwnedLivePod,
) -> None:
    owned = owned_live_pod
    session = BuildSessionManager.create(owned.api_user, headless=False)
    assert session.status == BuildSessionStatus.ACTIVE
    assert session.session_loaded_in_sandbox is True
    assert session.nextjs_port is not None
    assert session.sandbox is not None
    assert session.sandbox.id == str(owned.sandbox_id)
    assert session.sandbox.status == SandboxStatus.RUNNING
    session_id = UUID(session.id)
    tenant_id = get_current_tenant_id()
    file_store = get_default_file_store()
    snapshots = SnapshotManager(file_store)
    snapshot_storage_path: str | None = None
    nonce = uuid4().hex
    saved_heading = f"Craft restored preview {nonce}"
    unsaved_heading = f"Unsnapshotted preview {nonce}"
    saved_route_bytes = f"Craft restored Next response {nonce}\n".encode()
    unsaved_route_bytes = f"Unsnapshotted Next response {nonce}\n".encode()
    artifact_path = "outputs/restored-preview.txt"
    artifact_bytes = f"Craft restored artifact {nonce}\n".encode()
    history_path = f"/workspace/opencode-data/cache/restored-preview-{nonce}.txt"
    history_member = f".opencode-data/cache/restored-preview-{nonce}.txt"
    history_text = f"Craft restored OpenCode history {nonce}\n"
    unsaved_history_text = f"Unsnapshotted OpenCode history {nonce}\n"
    saved_files: dict[str, bytes] = {
        "outputs/web/app/layout.tsx": (
            'import type { ReactNode } from "react";\n'
            "export default function Layout({children}: {children: ReactNode}) {\n"
            "  return <html><body>{children}</body></html>;\n"
            "}\n"
        ).encode(),
        "outputs/web/app/page.tsx": (
            "export default function Page() {\n"
            f"  return <main><h1>{saved_heading}</h1></main>;\n"
            "}\n"
        ).encode(),
        "outputs/web/app/restore-proof/route.ts": (
            "export function GET(): Response {\n"
            f"  return new Response({json.dumps(saved_route_bytes.decode())}, {{\n"
            '    headers: { "Content-Type": "text/plain; charset=utf-8" },\n'
            "  });\n"
            "}\n"
        ).encode(),
        artifact_path: artifact_bytes,
    }
    unsaved_files: dict[str, bytes] = {
        "outputs/web/app/page.tsx": saved_files["outputs/web/app/page.tsx"].replace(
            saved_heading.encode(), unsaved_heading.encode()
        ),
        "outputs/web/app/restore-proof/route.ts": saved_files[
            "outputs/web/app/restore-proof/route.ts"
        ].replace(
            json.dumps(saved_route_bytes.decode()).encode(),
            json.dumps(unsaved_route_bytes.decode()).encode(),
        ),
        artifact_path: f"Unsnapshotted artifact {nonce}\n".encode(),
    }

    try:
        assert (
            pod_exec(
                k8s_client,
                owned.pod_name,
                SANDBOX_NAMESPACE,
                "id -u && id -g",
            )
            == "1000\n1000\n"
        )
        start_session_webapp(k8s_client, owned.pod_name, session_id)
        for path, content in saved_files.items():
            k8s_manager._guest(
                owned.sandbox_id,
                "write-file",
                {"session_id": str(session_id), "path": path},
                stdin=content,
            )
        pod_exec(
            k8s_client,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            "mkdir -p /workspace/opencode-data/cache && "
            f"printf %s {shlex.quote(history_text)} > {shlex.quote(history_path)}",
        )
        for path in ("outputs/web/package.json", "outputs/web/bun.lock"):
            saved_files[path] = k8s_manager._guest(
                owned.sandbox_id,
                "read-file",
                {"session_id": str(session_id), "path": path},
            )
            assert saved_files[path], f"The webapp bootstrap left {path} empty"
        wait_for_webapp_ready(
            owned.api_user,
            str(session_id),
            diagnostics=lambda: session_webapp_logs(
                k8s_client, owned.pod_name, session_id
            ),
        )
        before_page = proxy_get(owned.api_user, str(session_id))
        assert before_page.status_code == 200, before_page.text[:500]
        assert f"<h1>{saved_heading}</h1>" in before_page.text
        before_route = proxy_get(owned.api_user, str(session_id), "restore-proof")
        assert before_route.status_code == 200, before_route.text[:500]
        assert before_route.content == saved_route_bytes
        assert (
            BuildSessionManager.download_artifact(
                owned.api_user, session_id, artifact_path
            )
            == artifact_bytes
        )

        before_pod = k8s_client.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
        assert before_pod.metadata is not None
        assert isinstance(before_pod.metadata.uid, str)
        before_pod_uid = before_pod.metadata.uid
        assert before_pod.spec is not None
        assert before_pod.spec.runtime_class_name == "kata-fc"
        before_boot_id = UUID(
            pod_exec(
                k8s_client,
                owned.pod_name,
                SANDBOX_NAMESPACE,
                "cat /proc/sys/kernel/random/boot_id",
            ).strip()
        )
        with get_session_with_current_tenant() as db_session:
            stored_session = get_build_session(
                session_id, UUID(owned.api_user.id), db_session
            )
            assert stored_session is not None
            before_opencode_id = stored_session.opencode_session_id
            assert before_opencode_id is not None
        assert (
            k8s_manager.ensure_opencode_session(
                owned.sandbox_id, session_id, before_opencode_id
            )
            == before_opencode_id
        )

        snapshot = BuildSessionManager.create_snapshot(owned.api_user, session_id)
        assert snapshot is not None
        snapshot_storage_path = snapshot.storage_path
        with file_store.read_file(
            snapshot_storage_path, use_tempfile=True
        ) as snapshot_file:
            snapshot_bytes = snapshot_file.read()
        assert len(snapshot_bytes) == snapshot.size_bytes
        with tarfile.open(fileobj=io.BytesIO(snapshot_bytes), mode="r:gz") as archive:
            for path, content in saved_files.items():
                member = archive.getmember(path)
                assert member.isfile(), path
                archived_file = archive.extractfile(member)
                assert archived_file is not None, path
                with archived_file:
                    assert archived_file.read() == content, path
            excluded_entries = [
                name
                for name in archive.getnames()
                if set(PurePosixPath(name).parts)
                & {"node_modules", ".next", ".nextjs-port", "nextjs.pid"}
            ]
            assert excluded_entries == [], excluded_entries
        snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()

        history = BuildSessionManager.create_opencode_history_snapshot(
            owned.api_user, session_id
        )
        assert history.created is True
        history_storage_path = snapshots.opencode_history_storage_path(
            tenant_id, str(owned.sandbox_id)
        )
        with file_store.read_file(
            history_storage_path, use_tempfile=True
        ) as history_file:
            history_bytes = history_file.read()
        assert len(history_bytes) == file_store.get_file_size(history_storage_path)
        with tarfile.open(fileobj=io.BytesIO(history_bytes), mode="r:gz") as archive:
            marker = archive.getmember(history_member)
            assert marker.isfile()
            archived_history = archive.extractfile(marker)
            assert archived_history is not None
            with archived_history:
                assert archived_history.read() == history_text.encode()
        history_sha256 = hashlib.sha256(history_bytes).hexdigest()
        print(
            json.dumps(
                {
                    "phase": "durable-before-pod-loss",
                    "session_id": str(session_id),
                    "sandbox_id": str(owned.sandbox_id),
                    "oldPodUID": before_pod_uid,
                    "oldGuestBootID": str(before_boot_id),
                    "oldOpenCodeSessionID": before_opencode_id,
                    "snapshot_sha256": snapshot_sha256,
                    "snapshot_size_bytes": len(snapshot_bytes),
                    "history_sha256": history_sha256,
                    "history_size_bytes": len(history_bytes),
                },
                sort_keys=True,
            ),
            flush=True,
        )

        for path, content in unsaved_files.items():
            assert content != saved_files[path], path
            k8s_manager._guest(
                owned.sandbox_id,
                "write-file",
                {"session_id": str(session_id), "path": path},
                stdin=content,
            )
            assert (
                k8s_manager._guest(
                    owned.sandbox_id,
                    "read-file",
                    {"session_id": str(session_id), "path": path},
                )
                == content
            ), path
        pod_exec(
            k8s_client,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            f"printf %s {shlex.quote(unsaved_history_text)} > {shlex.quote(history_path)}",
        )
        assert (
            pod_exec(
                k8s_client,
                owned.pod_name,
                SANDBOX_NAMESPACE,
                f"cat {shlex.quote(history_path)}",
            )
            == unsaved_history_text
        )
        k8s_client.delete_namespaced_pod(
            owned.pod_name,
            SANDBOX_NAMESPACE,
            body=client.V1DeleteOptions(
                preconditions=client.V1Preconditions(uid=before_pod_uid)
            ),
        )
        wait_for_pod_deletion(k8s_client, owned.pod_name)

        restored = BuildSessionManager.restore(owned.api_user, session_id)
        assert restored.status == BuildSessionStatus.ACTIVE
        assert restored.session_loaded_in_sandbox is True
        assert restored.sandbox is not None
        assert restored.sandbox.id == str(owned.sandbox_id)
        assert restored.sandbox.status == SandboxStatus.RUNNING
        after_pod = k8s_client.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
        assert after_pod.metadata is not None
        assert isinstance(after_pod.metadata.uid, str)
        after_pod_uid = after_pod.metadata.uid
        assert after_pod_uid != before_pod_uid
        assert after_pod.spec is not None
        assert after_pod.spec.runtime_class_name == "kata-fc"
        after_boot_id = UUID(
            pod_exec(
                k8s_client,
                owned.pod_name,
                SANDBOX_NAMESPACE,
                "cat /proc/sys/kernel/random/boot_id",
            ).strip()
        )
        assert after_boot_id != before_boot_id
        print(
            json.dumps(
                {
                    "phase": "replacement-created",
                    "session_id": str(session_id),
                    "sandbox_id": str(owned.sandbox_id),
                    "oldPodUID": before_pod_uid,
                    "newPodUID": after_pod_uid,
                    "oldGuestBootID": str(before_boot_id),
                    "newGuestBootID": str(after_boot_id),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        wait_for_webapp_ready(
            owned.api_user,
            str(session_id),
            diagnostics=lambda: session_webapp_logs(
                k8s_client, owned.pod_name, session_id
            ),
        )
        after_page = proxy_get(owned.api_user, str(session_id))
        assert after_page.status_code == 200, after_page.text[:500]
        assert f"<h1>{saved_heading}</h1>" in after_page.text
        assert unsaved_heading not in after_page.text
        after_route = proxy_get(owned.api_user, str(session_id), "restore-proof")
        assert after_route.status_code == 200, after_route.text[:500]
        assert after_route.content == saved_route_bytes
        assert after_route.content != unsaved_route_bytes
        restored_artifact = BuildSessionManager.download_artifact(
            owned.api_user, session_id, artifact_path
        )
        assert restored_artifact == artifact_bytes
        assert (
            pod_exec(
                k8s_client,
                owned.pod_name,
                SANDBOX_NAMESPACE,
                webapp_install_check_command(session_id),
            ).strip()
            == WEBAPP_INSTALLED
        )
        for path, content in saved_files.items():
            assert (
                k8s_manager._guest(
                    owned.sandbox_id,
                    "read-file",
                    {"session_id": str(session_id), "path": path},
                )
                == content
            ), path
        assert (
            pod_exec(
                k8s_client,
                owned.pod_name,
                SANDBOX_NAMESPACE,
                f"cat {shlex.quote(history_path)}",
            )
            == history_text
        )
        after_opencode_id = k8s_manager.ensure_opencode_session(
            owned.sandbox_id, session_id, before_opencode_id
        )
        assert after_opencode_id == before_opencode_id
        with get_session_with_current_tenant() as db_session:
            stored_session = get_build_session(
                session_id, UUID(owned.api_user.id), db_session
            )
            assert stored_session is not None
            assert stored_session.opencode_session_id == before_opencode_id
        print(
            json.dumps(
                {
                    "phase": "restored-preview-verified",
                    "session_id": str(session_id),
                    "sandbox_id": str(owned.sandbox_id),
                    "oldPodUID": before_pod_uid,
                    "newPodUID": after_pod_uid,
                    "oldGuestBootID": str(before_boot_id),
                    "newGuestBootID": str(after_boot_id),
                    "oldOpenCodeSessionID": before_opencode_id,
                    "newOpenCodeSessionID": after_opencode_id,
                    "snapshot_sha256": snapshot_sha256,
                    "history_sha256": history_sha256,
                    "route_sha256": hashlib.sha256(after_route.content).hexdigest(),
                    "artifact_sha256": hashlib.sha256(restored_artifact).hexdigest(),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        try:
            if snapshot_storage_path is not None:
                snapshots.delete_snapshot(snapshot_storage_path)
        finally:
            snapshots.delete_opencode_history_snapshot(tenant_id, str(owned.sandbox_id))
