"""Kubernetes sidecar snapshot/restore contract + API restore orchestration."""

from __future__ import annotations

import io
import shutil
import tarfile
from collections.abc import Callable
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import pytest
from kubernetes import client
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.db.sandbox import create_snapshot__no_commit
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.snapshot_manager import SNAPSHOT_FILE_TYPE
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.common.craft.payloads import default_llm_config
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import cleanup_api_user_sandbox_rows
from tests.integration.tests.craft.k8s.k8s_fixtures import pod_exec
from tests.integration.tests.craft.k8s.k8s_fixtures import SandboxHandle
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_for_pod_deletion

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


def _populate_session_workspace(
    k8s: client.CoreV1Api,
    pod_name: str,
    session_id: UUID,
    *,
    include_managed_skills: bool = False,
) -> dict[str, str]:
    """Seed the session workspace; returns ``{relative path: content}``."""
    session_path = f"/workspace/sessions/{session_id}"
    payload = {
        "outputs/web/page.tsx": "// hello from outputs\n",
        "outputs/data/manifest.json": '{"v": 1}\n',
        "attachments/notes.txt": "user uploaded notes\n",
    }

    script_lines = ["set -e", f"cd {session_path}"]
    for rel_path, content in payload.items():
        script_lines.append(f"mkdir -p $(dirname {rel_path})")
        script_lines.append(f"printf '%s' '{content}' > {rel_path}")

    pod_exec(k8s, pod_name, SANDBOX_NAMESPACE, "\n".join(script_lines))

    if include_managed_skills:
        # managed/ is RO in the sandbox container; seed via the sidecar.
        pod_exec(
            k8s,
            pod_name,
            SANDBOX_NAMESPACE,
            "mkdir -p /workspace/managed/skills/marker && "
            "printf '%s' 'managed-skill-content' "
            "> /workspace/managed/skills/marker/SKILL.md",
            container="sidecar",
        )

    return payload


def _download_snapshot(storage_path: str, dest: Path) -> None:
    file_io = get_default_file_store().read_file(storage_path, use_tempfile=True)
    try:
        with dest.open("wb") as out_file:
            shutil.copyfileobj(file_io, out_file)
    finally:
        file_io.close()


def _put_snapshot_bytes(storage_path: str, body: bytes) -> None:
    """Upload arbitrary bytes to FileStore (forges corrupt/traversal tarballs)."""
    get_default_file_store().save_file(
        content=io.BytesIO(body),
        display_name=Path(storage_path).name,
        file_origin=FileOrigin.SANDBOX_SNAPSHOT,
        file_type=SNAPSHOT_FILE_TYPE,
        file_id=storage_path,
    )


def _list_archive_members(tar_path: Path) -> list[str]:
    with tarfile.open(tar_path, "r:gz") as tar:
        return tar.getnames()


def test_snapshot_includes_outputs_and_attachments_only(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    sandbox_id, session_id, pod_name = pool_session

    _populate_session_workspace(k8s_client, pod_name, session_id)

    result = k8s_manager.create_snapshot(
        sandbox_id, session_id, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    )
    assert result is not None, "create_snapshot returned None for populated session"

    archive = tmp_path / "snapshot.tar.gz"
    _download_snapshot(result.storage_path, archive)

    members = _list_archive_members(archive)
    # tarfile may emit "outputs" or "./outputs" depending on version.
    assert any(m == "outputs" or m.startswith("outputs/") for m in members), (
        f"Expected outputs/ tree in archive. Members: {members}"
    )
    assert any(m == "attachments" or m.startswith("attachments/") for m in members), (
        f"Expected attachments/ tree. Members: {members}"
    )
    assert not any(
        m == ".opencode-data" or m.startswith(".opencode-data/") for m in members
    ), f".opencode-data/ must not appear in session snapshot. Members: {members}"

    assert any(m.endswith("outputs/web/page.tsx") for m in members)
    assert any(m.endswith("attachments/notes.txt") for m in members)


def test_snapshot_excludes_managed_skills_agents_md_opencode_json(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    sandbox_id, session_id, pod_name = pool_session

    _populate_session_workspace(
        k8s_client, pod_name, session_id, include_managed_skills=True
    )

    result = k8s_manager.create_snapshot(
        sandbox_id, session_id, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    )
    assert result is not None

    archive = tmp_path / "snapshot.tar.gz"
    _download_snapshot(result.storage_path, archive)

    members = _list_archive_members(archive)
    # Match the session-root path only: outputs/web/ ships its own legitimate AGENTS.md.
    for forbidden in ("AGENTS.md", "opencode.json"):
        assert not any(m in (forbidden, f"./{forbidden}") for m in members), (
            f"{forbidden} must not appear at snapshot root. Members: {members}"
        )
    assert not any("managed/skills" in m for m in members), (
        f"managed/skills/* must not appear in snapshot. Members: {members}"
    )
    assert not any("SKILL.md" in m for m in members), (
        f"managed skill bundle leaked. Members: {members}"
    )


def test_restore_from_snapshot_recreates_workspace(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, pod_name = pool_session

    payload = _populate_session_workspace(k8s_client, pod_name, session_id)
    result = k8s_manager.create_snapshot(
        sandbox_id, session_id, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    )
    assert result is not None

    pre_hashes = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"cd /workspace/sessions/{session_id} && "
        f"find outputs attachments -type f | sort | "
        f"xargs sha256sum",
    )

    # Empty workspace at restore time; equivalent to terminate + re-provision.
    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)

    missing = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"[ -d /workspace/sessions/{session_id} ] && echo PRESENT || echo MISSING",
    )
    assert "MISSING" in missing

    k8s_manager.restore_snapshot(
        sandbox_id=sandbox_id,
        session_id=session_id,
        snapshot_storage_path=result.storage_path,
        nextjs_port=None,
        llm_config=default_llm_config(),
        skills_section="No skills available.",
    )

    post_hashes = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"cd /workspace/sessions/{session_id} && "
        f"find outputs attachments -type f | sort | "
        f"xargs sha256sum",
    )
    assert pre_hashes.strip() == post_hashes.strip(), (
        f"Restored files differ.\nBEFORE:\n{pre_hashes}\nAFTER:\n{post_hashes}"
    )

    notes = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"cat /workspace/sessions/{session_id}/attachments/notes.txt",
    )
    assert notes.strip() == payload["attachments/notes.txt"].strip()


def test_restore_re_pushes_skills(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    k8s_admin_user: DATestUser,
    running_sandbox: Callable[..., SandboxHandle],
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    handle = running_sandbox(with_session=True)
    assert handle.session_id is not None
    sandbox_id = handle.sandbox_id
    session_id = handle.session_id
    pod_name = handle.manager._get_pod_name(sandbox_id)

    _populate_session_workspace(k8s_client, pod_name, session_id)
    result = k8s_manager.create_snapshot(
        sandbox_id, session_id, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    )
    assert result is not None
    create_snapshot__no_commit(
        db_session,
        session_id=session_id,
        storage_path=result.storage_path,
        size_bytes=result.size_bytes,
    )
    db_session.commit()

    skill = SkillManager.create_custom(
        k8s_admin_user,
        slug=f"restore-repush-{uuid4().hex[:6]}",
        is_public=True,
    )
    try:
        # managed/ is RO in the sandbox container; wipe via the sidecar.
        pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            "rm -rf /workspace/managed/skills && mkdir -p /workspace/managed",
            container="sidecar",
        )

        k8s_manager.cleanup_session_workspace(sandbox_id, session_id)
        response = BuildSessionManager.restore(handle.api_user, session_id)
        assert response["session_loaded_in_sandbox"] is True

        listing = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"ls -1 /workspace/managed/skills/{skill.slug}/",
        )
        assert "SKILL.md" in listing, (
            f"API restore should rehydrate skills after snapshot restore. Got: {listing}"
        )

        resolved = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"ls -1 /workspace/sessions/{session_id}/.opencode/skills/{skill.slug}/",
        )
        assert "SKILL.md" in resolved
    finally:
        SkillManager.delete_custom(skill, k8s_admin_user)


def test_restore_with_missing_snapshot_creates_fresh_workspace(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, pod_name = pool_session

    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)

    # No snapshot: callers use setup_session_workspace, which must produce a fresh tree.
    k8s_manager.setup_session_workspace(
        sandbox_id=sandbox_id,
        session_id=session_id,
        llm_config=default_llm_config(),
        nextjs_port=None,
        skills_section="No skills available.",
    )

    listing = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"ls -1 /workspace/sessions/{session_id}/",
    )
    assert "outputs" in listing
    assert "AGENTS.md" in listing


def test_opencode_history_snapshot_restores_into_reprovisioned_pod(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    live_pod: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, _session_id, pod_name = live_pod
    marker_path = "/workspace/opencode-data/cache/history-roundtrip.txt"

    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "mkdir -p /workspace/opencode-data/cache && "
        f"printf '%s' 'restored-opencode-history' > {marker_path}",
    )

    assert k8s_manager.create_opencode_history_snapshot(
        sandbox_id,
        POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
    )

    k8s_manager.terminate(sandbox_id)
    wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)

    # Throwaway user; reap its row explicitly (live_pod only reaps the original).
    reprovision_user_id = uuid4()
    k8s_manager.provision(
        sandbox_id=sandbox_id,
        user_id=reprovision_user_id,
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        llm_config=default_llm_config(),
        onyx_pat="test-onyx-pat",
    )
    try:
        restored = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"cat {marker_path}",
        )
        assert restored == "restored-opencode-history"
    finally:
        cleanup_api_user_sandbox_rows(reprovision_user_id)


def test_restore_uses_data_filter_to_block_traversal(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    live_pod: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    """A forged ``../escape.txt`` tar entry must be rejected before extraction."""
    sandbox_id, session_id, pod_name = live_pod

    # On live_pod so any regression that writes /workspace/escape.txt stays on a fresh pod.
    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)

    archive_local = tmp_path / "traversal.tar.gz"
    with tarfile.open(archive_local, "w:gz") as tar:
        good = tmp_path / "good.txt"
        good.write_text("safe content\n")
        tar.add(good, arcname="outputs/good.txt")

        evil_info = tarfile.TarInfo(name="../escape.txt")
        evil_payload = b"PWNED\n"
        evil_info.size = len(evil_payload)
        tar.addfile(evil_info, fileobj=io.BytesIO(evil_payload))

    storage_path = f"{POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE}/snapshots/{session_id}/traversal.tar.gz"
    _put_snapshot_bytes(storage_path, archive_local.read_bytes())

    with pytest.raises(Exception) as excinfo:
        k8s_manager.restore_snapshot(
            sandbox_id=sandbox_id,
            session_id=session_id,
            snapshot_storage_path=storage_path,
            nextjs_port=None,
            llm_config=default_llm_config(),
            skills_section="No skills available.",
        )

    err_text = str(excinfo.value).lower()
    assert any(
        token in err_text for token in ("traversal", "escape", "invalid snapshot")
    ), f"Restore should clearly reject traversal. Got: {excinfo.value}"

    sessions_root_listing = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "ls -1 /workspace/sessions/ /workspace/ 2>&1 || true",
    )
    assert "escape.txt" not in sessions_root_listing, (
        "Traversal entry escaped the session workspace! "
        f"Listing: {sessions_root_listing}"
    )

    escape_probe = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "[ -e /workspace/escape.txt ] && echo PRESENT || echo MISSING",
    )
    assert "MISSING" in escape_probe, (
        f"/workspace/escape.txt should not exist post-restore. Probe: {escape_probe}."
    )

    # The good member must not be extracted before the traversal member is rejected.
    good_probe = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"[ -e /workspace/sessions/{session_id}/outputs/good.txt ] "
        "&& echo PRESENT || echo MISSING",
    )
    assert "MISSING" in good_probe, (
        "Traversal archive should be rejected before partial extraction. "
        f"Probe: {good_probe}."
    )


def test_snapshot_corruption_detected_on_restore(
    k8s_manager: KubernetesSandboxManager,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, _pod_name = pool_session

    # Valid gzip header, garbage body.
    corrupt_bytes = b"\x1f\x8b\x08\x00" + b"\x00" * 8 + b"truncated-mid-stream"
    storage_path = f"{POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE}/snapshots/{session_id}/corrupt.tar.gz"
    _put_snapshot_bytes(storage_path, corrupt_bytes)

    with pytest.raises(Exception) as excinfo:
        k8s_manager.restore_snapshot(
            sandbox_id=sandbox_id,
            session_id=session_id,
            snapshot_storage_path=storage_path,
            nextjs_port=None,
            llm_config=default_llm_config(),
            skills_section="No skills available.",
        )

    err_text = str(excinfo.value).lower()
    assert any(
        token in err_text
        for token in ("corrupt", "checksum", "invalid snapshot", "integrity")
    ), (
        "Error message should clearly identify snapshot corruption. "
        f"Got: {excinfo.value}"
    )
