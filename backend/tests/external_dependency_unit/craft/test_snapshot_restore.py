"""Snapshot + restore (K8s only).

These tests exercise the real Kubernetes snapshot/restore flow:
- Pods are provisioned via ``KubernetesSandboxManager``.
- Snapshots are uploaded to the SANDBOX_S3_BUCKET via AWS CLI inside the pod
  (NOT via the FileStore abstraction — the K8s backend bypasses it for
  bandwidth reasons; see ``create_snapshot`` docstring).
- Verification downloads the resulting tarball via boto3 against the same
  bucket and inspects its members locally with ``tmp_path``.

The file-level ``pytestmark`` gates the entire module to the K8s CI lane.
Per project memory: never run these locally — they touch the real cluster.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path
from typing import Any
from uuid import UUID

import boto3
import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_S3_BUCKET
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
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
# snapshot/S3 plumbing plus the live-pod fixture that wires them up.
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
        ".opencode-data/session.json": '{"id": "deadbeef"}\n',
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


def _s3_client() -> Any:
    """Return a boto3 S3 client configured for the sandbox bucket.

    The K8s manager bypasses the FileStore for snapshots and uses AWS CLI
    in-pod, so the test verifies via boto3 directly against the same bucket.

    In CI the in-pod sidecar talks to MinIO via the cluster-internal DNS
    name (``AWS_ENDPOINT_URL`` env), but the test process runs on the host
    and must use the host-accessible endpoint exposed by docker-compose
    (``S3_ENDPOINT_URL``). Construct the client explicitly so it doesn't
    inherit the in-cluster endpoint from ``AWS_ENDPOINT_URL``.
    """
    endpoint_url = os.environ.get("S3_ENDPOINT_URL")
    access_key = os.environ.get("S3_AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("S3_AWS_SECRET_ACCESS_KEY")
    region = os.environ.get("AWS_REGION") or "us-east-1"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


def _download_snapshot(storage_path: str, dest: Path) -> None:
    """Download a snapshot blob from SANDBOX_S3_BUCKET to ``dest``."""
    _s3_client().download_file(SANDBOX_S3_BUCKET, storage_path, str(dest))


def _delete_snapshot(storage_path: str) -> None:
    try:
        _s3_client().delete_object(Bucket=SANDBOX_S3_BUCKET, Key=storage_path)
    except Exception:
        pass


def _put_snapshot_bytes(storage_path: str, body: bytes) -> None:
    """Upload arbitrary bytes to the snapshot bucket (used to forge corrupt
    or traversal-laden tarballs that real callers can't produce)."""
    _s3_client().put_object(Bucket=SANDBOX_S3_BUCKET, Key=storage_path, Body=body)


def _list_archive_members(tar_path: Path) -> list[str]:
    with tarfile.open(tar_path, "r:gz") as tar:
        return tar.getnames()


# ---------------------------------------------------------------------------
# Fixtures: k8s_manager and live_pod are provided by conftest.py.
#
# Note: snapshot S3 cleanup is NOT handled by the shared ``live_pod``
# fixture. Tests that create snapshots must clean them up individually
# (see ``_delete_snapshot``).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_snapshot_includes_outputs_and_attachments_and_opencode_data(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    live_pod: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    sandbox_id, session_id, pod_name = live_pod

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
    assert any(
        m == ".opencode-data" or m.startswith(".opencode-data/") for m in members
    ), f"Expected .opencode-data/ tree. Members: {members}"

    # The specific seed files should round-trip.
    assert any(m.endswith("outputs/web/page.tsx") for m in members)
    assert any(m.endswith("attachments/notes.txt") for m in members)
    assert any(m.endswith(".opencode-data/session.json") for m in members)


def test_snapshot_excludes_managed_skills_agents_md_opencode_json(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    live_pod: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    sandbox_id, session_id, pod_name = live_pod

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
    live_pod: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, pod_name = live_pod

    payload = _populate_session_workspace(k8s_client, pod_name, session_id)
    result = k8s_manager.create_snapshot(sandbox_id, session_id, TEST_TENANT_ID)
    assert result is not None

    # Capture the file hashes before tearing down the workspace.
    pre_hashes = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"cd /workspace/sessions/{session_id} && "
        f"find outputs attachments .opencode-data -type f | sort | "
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
        tenant_id=TEST_TENANT_ID,
        nextjs_port=None,
        llm_config=default_llm_config(),
        skills_section="No skills available.",
    )

    post_hashes = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"cd /workspace/sessions/{session_id} && "
        f"find outputs attachments .opencode-data -type f | sort | "
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
    live_pod: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, pod_name = live_pod

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
        tenant_id=TEST_TENANT_ID,
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
    live_pod: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, pod_name = live_pod

    # Wipe the workspace so we can verify the fresh-setup path.
    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)

    # No snapshot exists in S3 — the caller (sessions_api) handles the
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
    assert "opencode.json" in listing


def test_snapshot_failure_does_not_block_pod_termination(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    live_pod: tuple[UUID, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_id, session_id, pod_name = live_pod

    _populate_session_workspace(k8s_client, pod_name, session_id)

    # The K8s backend uses AWS CLI inside the pod (bypassing FileStore),
    # so the equivalent of "monkeypatch save_file to raise" is to break
    # ``create_snapshot`` directly. The orchestration contract (see
    # ``cleanup_idle_sandboxes_task``) is: snapshot failure is caught and
    # termination still proceeds.
    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("simulated S3 outage")

    monkeypatch.setattr(
        KubernetesSandboxManager,
        "create_snapshot",
        _boom,
    )

    # Mimic the orchestration block from cleanup_idle_sandboxes_task in a
    # narrow form: try snapshot, swallow on failure, then terminate.
    snapshot_failed = False
    try:
        k8s_manager.create_snapshot(sandbox_id, session_id, TEST_TENANT_ID)
    except Exception:
        snapshot_failed = True

    assert snapshot_failed, "monkeypatched create_snapshot should have raised"

    # Termination should still succeed.
    k8s_manager.terminate(sandbox_id)
    wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)

    # Pod is gone.
    try:
        pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)
        assert pod.metadata.deletion_timestamp is not None
    except ApiException as e:
        assert e.status == 404


def test_restore_uses_data_filter_to_block_traversal(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    live_pod: tuple[UUID, UUID, str],
    tmp_path: Path,
) -> None:
    """Forge a tarball with a ``../escape.txt`` entry and verify the restore
    cannot write outside the session workspace.

    Defence-in-depth here is provided by **GNU tar inside the pod**, not by
    Python's ``tarfile.extractall(filter="data")``. The K8s backend pipes
    ``s5cmd cat | tar -xzf - -C /workspace/sessions/<session_id>``; GNU
    tar strips leading ``../`` components when extracting (refusing to
    write above the ``-C`` directory) and the ``-C`` flag pins the
    extraction root. The local sandbox backend uses Python's
    ``tarfile.extractall(filter="data")`` instead — same observable
    outcome, different mechanism. (The test name retains its historical
    "data_filter" wording for stability; the actual K8s defence is
    in-pod GNU tar.)

    The test tolerates two outcomes: restore raises (tar rejected the
    entry), or restore succeeds with the traversal entry confined. Either
    way the would-be ``escape.txt`` must NOT exist above the session
    directory afterwards.
    """
    sandbox_id, session_id, pod_name = live_pod

    # Wipe the workspace so we can detect any traversal artefacts cleanly.
    k8s_manager.cleanup_session_workspace(sandbox_id, session_id)

    # Build a tarball locally with one well-behaved entry plus one traversal
    # entry. We use the local tmp_path to assemble it, then upload via S3.
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
    _s3_client().upload_file(str(archive_local), SANDBOX_S3_BUCKET, storage_path)

    # Attempt to restore. We tolerate either outcome:
    # (a) restore raises because tar rejected the traversal entry, or
    # (b) restore succeeds but the traversal entry was confined.
    # Either way, ``/workspace/escape.txt`` (one level above the session)
    # must NOT exist after the operation.
    restore_raised = False
    try:
        k8s_manager.restore_snapshot(
            sandbox_id=sandbox_id,
            session_id=session_id,
            snapshot_storage_path=storage_path,
            tenant_id=TEST_TENANT_ID,
            nextjs_port=None,
            llm_config=default_llm_config(),
            skills_section="No skills available.",
        )
    except Exception:
        restore_raised = True

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
        f"/workspace/escape.txt should not exist post-restore. "
        f"Probe: {escape_probe}. restore_raised={restore_raised}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "known: no checksum validation on snapshot tarballs; a partial-write "
        "during S3 outage produces a corrupt blob and restore fails opaquely "
        "(generic tarfile error rather than a clear corruption signal). "
    ),
)
def test_snapshot_corruption_detected_on_restore(
    k8s_manager: KubernetesSandboxManager,
    live_pod: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, session_id, _pod_name = live_pod

    # Forge a truncated gzip blob — valid gzip header, garbage body.
    corrupt_bytes = b"\x1f\x8b\x08\x00" + b"\x00" * 8 + b"truncated-mid-stream"
    storage_path = f"{TEST_TENANT_ID}/snapshots/{session_id}/corrupt.tar.gz"
    _put_snapshot_bytes(storage_path, corrupt_bytes)

    # Restore should raise a SnapshotCorruption-class error (or at minimum
    # an error whose message identifies the blob as corrupt). Today it
    # raises a generic RuntimeError wrapping a tarfile / aws-cli failure,
    # which this xfail absorbs until checksum validation lands.
    with pytest.raises(Exception) as excinfo:
        k8s_manager.restore_snapshot(
            sandbox_id=sandbox_id,
            session_id=session_id,
            snapshot_storage_path=storage_path,
            tenant_id=TEST_TENANT_ID,
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
