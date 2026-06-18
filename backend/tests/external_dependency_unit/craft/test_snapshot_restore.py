"""Snapshot + restore (K8s only).

These tests exercise the real Kubernetes snapshot/restore flow:
- Pods are provisioned via ``KubernetesSandboxManager``.
- Snapshots are streamed from the pod sidecar to the API server, then persisted
  through the normal Onyx FileStore.
- Verification downloads the resulting tarball via FileStore and inspects its
  members locally with ``tmp_path``.

The file-level ``pytestmark`` gates the entire module to the K8s CI lane.
Per project memory: never run these locally — they touch the real cluster.
"""

from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import pytest
from kubernetes import client

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.snapshot_manager import SNAPSHOT_FILE_TYPE
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import default_llm_config
from tests.external_dependency_unit.craft.conftest import pod_exec
from tests.external_dependency_unit.craft.conftest import wait_for_pod_deletion

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


# ---------------------------------------------------------------------------
# Snapshot-specific helpers
#
# Generic K8s helpers (``pod_exec``, ``wait_for_pod_deletion``, ``k8s_client``
# fixture) live in conftest.py per Part V.1. What remains here is
# snapshot/FileStore plumbing plus the live-pod fixture that wires them up.
# ---------------------------------------------------------------------------


def _populate_session_workspace(
    k8s: client.CoreV1Api,
    pod_name: str,
    session_id: UUID,
    *,
    include_managed_skills: bool = False,
) -> dict[str, str]:
    """Seed the session workspace with deterministic content for inspection.

    Returns a map of ``relative path → content`` so tests can assert on it
    after a round trip through snapshot/restore.
    """
    session_path = f"/workspace/sessions/{session_id}"
    payload = {
        "outputs/web/page.tsx": "// hello from outputs\n",
        "outputs/data/manifest.json": '{"v": 1}\n',
        "attachments/notes.txt": "user uploaded notes\n",
    }

    script_lines = ["set -e", f"cd {session_path}"]
    for rel_path, content in payload.items():
        script_lines.append(f"mkdir -p $(dirname {rel_path})")
        # Use printf with single quotes; payload above is shell-safe.
        script_lines.append(f"printf '%s' '{content}' > {rel_path}")

    pod_exec(k8s, pod_name, SANDBOX_NAMESPACE, "\n".join(script_lines))

    if include_managed_skills:
        # ``managed/skills`` lives at /workspace/managed, which is read-only
        # in the sandbox container. The sidecar mounts it rw, so we route
        # this seed through the sidecar. The point: prove the snapshot does
        # not pick managed/ up via traversal of ``.opencode/skills``.
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
    """Download a snapshot blob from FileStore to ``dest``."""
    file_io = get_default_file_store().read_file(storage_path, use_tempfile=True)
    try:
        with dest.open("wb") as out_file:
            shutil.copyfileobj(file_io, out_file)
    finally:
        file_io.close()


def _put_snapshot_bytes(storage_path: str, body: bytes) -> None:
    """Upload arbitrary bytes to FileStore (used to forge corrupt
    or traversal-laden tarballs that real callers can't produce)."""
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


# ---------------------------------------------------------------------------
# Fixtures: k8s_manager, pool_session, and live_pod are provided by conftest.py.
# Tests use ``pool_session`` to share the module pod; ``live_pod`` is
# reserved for the termination test and the traversal-defence test (where
# isolation matters if the defence ever regresses). Snapshot FileStore cleanup
# is not handled by either fixture — snapshot keys include the per-test
# session_id so they don't collide.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_snapshot_includes_outputs_and_attachments_only(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    sandbox_id, session_id, pod_name = pool_session

    _populate_session_workspace(k8s_client, pod_name, session_id)

    result = k8s_manager.create_snapshot(sandbox_id, session_id, TEST_TENANT_ID)
    assert result is not None, "create_snapshot returned None for populated session"

    archive = tmp_path / "snapshot.tar.gz"
    _download_snapshot(result.storage_path, archive)

    members = _list_archive_members(archive)
    # tarfile may emit either "outputs" or "./outputs" depending on tar version;
    # normalise on a contains-check.
    assert any(m == "outputs" or m.startswith("outputs/") for m in members), (
        f"Expected outputs/ tree in archive. Members: {members}"
    )
    assert any(m == "attachments" or m.startswith("attachments/") for m in members), (
        f"Expected attachments/ tree. Members: {members}"
    )
    assert not any(
        m == ".opencode-data" or m.startswith(".opencode-data/") for m in members
    ), f".opencode-data/ must not appear in session snapshot. Members: {members}"

    # The specific seed files should round-trip.
    assert any(m.endswith("outputs/web/page.tsx") for m in members)
    assert any(m.endswith("attachments/notes.txt") for m in members)


def test_snapshot_excludes_managed_skills_agents_md_opencode_json(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    sandbox_id, session_id, pod_name = pool_session

    # ``setup_session_workspace`` already wrote AGENTS.md + opencode.json
    # at the session root. We additionally seed managed/skills/ at the
    # pod-global location.
    _populate_session_workspace(
        k8s_client, pod_name, session_id, include_managed_skills=True
    )

    result = k8s_manager.create_snapshot(sandbox_id, session_id, TEST_TENANT_ID)
    assert result is not None

    archive = tmp_path / "snapshot.tar.gz"
    _download_snapshot(result.storage_path, archive)

    members = _list_archive_members(archive)
    # AGENTS.md, opencode.json live at the session root — they must not be
    # captured. Match the session-root path only (the snapshot tars from the
    # session dir, so the root would show up as ``AGENTS.md`` or
    # ``./AGENTS.md``). The scaffolded Next.js project under outputs/web/
    # ships its own AGENTS.md which is legitimate user code and must remain.
    # Likewise the .opencode/skills symlink (which targets
    # /workspace/managed/skills) must not leak the managed tree.
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
    result = k8s_manager.create_snapshot(sandbox_id, session_id, TEST_TENANT_ID)
    assert result is not None

    # Capture the file hashes before tearing down the workspace.
    pre_hashes = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"cd /workspace/sessions/{session_id} && "
        f"find outputs attachments -type f | sort | "
        f"xargs sha256sum",
    )

    # Tear down the session workspace (simulates terminate + re-provision
    # without recycling the entire pod). For a true "new pod" round-trip
    # we would terminate the sandbox here, but provisioning is slow and
    # the restore path is identical — what matters is that the workspace
    # is empty at the time of restore.
    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)

    # Verify it's gone.
    missing = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"[ -d /workspace/sessions/{session_id} ] && echo PRESENT || echo MISSING",
    )
    assert "MISSING" in missing

    # Restore.
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

    # Spot-check one file's content end-to-end.
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
    pool_session: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, pod_name = pool_session

    _populate_session_workspace(k8s_client, pod_name, session_id)
    result = k8s_manager.create_snapshot(sandbox_id, session_id, TEST_TENANT_ID)
    assert result is not None

    # Wipe the managed/skills tree to simulate a fresh post-restore state.
    # In production the caller (sessions_api) follows up restore_snapshot
    # with hydrate_sandbox_skills; this test verifies that push works
    # against a snapshot-restored workspace. The wipe must run in the
    # sidecar — ``/workspace/managed`` is read-only in the sandbox container.
    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "rm -rf /workspace/managed/skills && mkdir -p /workspace/managed",
        container="sidecar",
    )

    # Restore the session.
    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)
    k8s_manager.restore_snapshot(
        sandbox_id=sandbox_id,
        session_id=session_id,
        snapshot_storage_path=result.storage_path,
        nextjs_port=None,
        llm_config=default_llm_config(),
        skills_section="No skills available.",
    )

    # Push a synthetic skill via the manager (this is the same code path
    # that ``hydrate_sandbox_skills`` exercises after a successful restore).
    fileset = {
        "marker-skill/SKILL.md": (b"---\nname: marker-skill\ndescription: test\n---\n"),
        "marker-skill/run.sh": b"#!/bin/sh\necho ok\n",
    }
    k8s_manager.push_to_sandbox(
        sandbox_id=sandbox_id,
        mount_path="/workspace/managed/skills",
        files=fileset,
    )

    listing = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "ls -1 /workspace/managed/skills/marker-skill/",
    )
    assert "SKILL.md" in listing, (
        f"Restored workspace should accept skill push. Got: {listing}"
    )
    assert "run.sh" in listing

    # The session's .opencode/skills symlink should resolve to the
    # repopulated managed/skills tree.
    resolved = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"ls -1 /workspace/sessions/{session_id}/.opencode/skills/marker-skill/",
    )
    assert "SKILL.md" in resolved


def test_restore_with_missing_snapshot_creates_fresh_workspace(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, pod_name = pool_session

    # Wipe the workspace so we can verify the fresh-setup path.
    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)

    # No snapshot exists — the caller (sessions_api) handles the
    # "no snapshot" path by calling ``setup_session_workspace`` rather than
    # ``restore_snapshot``. This test pins that contract: setup_session_workspace
    # must not raise and must produce a fresh outputs/ tree.
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
        TEST_TENANT_ID,
    )

    k8s_manager.terminate(sandbox_id)
    wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)

    k8s_manager.provision(
        sandbox_id=sandbox_id,
        user_id=uuid4(),
        tenant_id=TEST_TENANT_ID,
        llm_config=default_llm_config(),
        onyx_pat="test-onyx-pat",
    )

    restored = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"cat {marker_path}",
    )
    assert restored == "restored-opencode-history"


def test_restore_uses_data_filter_to_block_traversal(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    live_pod: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    """Forge a tarball with a ``../escape.txt`` entry and verify the restore
    cannot write outside the session workspace.

    Defence-in-depth here is provided by the in-pod sidecar before extracting:
    it validates snapshot members, rejects links/special files/traversal, and
    only materializes entries under the snapshot-owned session roots. (The test
    name retains its historical "data_filter" wording for stability.)

    The new sidecar contract is stricter than the old GNU tar path:
    traversal must be rejected before extraction, not silently normalized
    or skipped.
    """
    sandbox_id, session_id, pod_name = live_pod

    # Wipe the workspace so we can detect any traversal artefacts cleanly.
    # Stays on ``live_pod`` (not ``pool_session``) so that any regression
    # which lets ``/workspace/escape.txt`` actually get written is
    # contained to a fresh pod, not poisoning every later test in the
    # module.
    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)

    # Build a tarball locally with one well-behaved entry plus one traversal
    # entry. We use the local tmp_path to assemble it, then upload via FileStore.
    archive_local = tmp_path / "traversal.tar.gz"
    with tarfile.open(archive_local, "w:gz") as tar:
        # Well-behaved entry — should land inside the session dir.
        good = tmp_path / "good.txt"
        good.write_text("safe content\n")
        tar.add(good, arcname="outputs/good.txt")

        # Malicious entry — relative traversal trying to land outside the
        # extraction root. Build a TarInfo with a hand-crafted name so the
        # archive really does contain ``../escape.txt``.
        evil_info = tarfile.TarInfo(name="../escape.txt")
        evil_payload = b"PWNED\n"
        evil_info.size = len(evil_payload)
        tar.addfile(evil_info, fileobj=io.BytesIO(evil_payload))

    storage_path = f"{TEST_TENANT_ID}/snapshots/{session_id}/traversal.tar.gz"
    _put_snapshot_bytes(storage_path, archive_local.read_bytes())

    # Attempt to restore. Traversal must be rejected before extraction.
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

    # The session's parent dir must not have gained an ``escape.txt``.
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

    # And a direct stat of the would-be escape target must fail.
    escape_probe = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "[ -e /workspace/escape.txt ] && echo PRESENT || echo MISSING",
    )
    assert "MISSING" in escape_probe, (
        f"/workspace/escape.txt should not exist post-restore. Probe: {escape_probe}."
    )

    # The good member in the same archive should not have been extracted
    # before rejecting the traversal member.
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

    # Forge a truncated gzip blob — valid gzip header, garbage body.
    corrupt_bytes = b"\x1f\x8b\x08\x00" + b"\x00" * 8 + b"truncated-mid-stream"
    storage_path = f"{TEST_TENANT_ID}/snapshots/{session_id}/corrupt.tar.gz"
    _put_snapshot_bytes(storage_path, corrupt_bytes)

    # Restore should raise a SnapshotCorruption-class error (or at minimum
    # an error whose message identifies the blob as corrupt). The API-side
    # upload checksum covers transit to the sidecar; tar validation covers
    # corrupt archive contents.
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
