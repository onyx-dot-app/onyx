"""Manual smoke test for the Docker sandbox backend (PR 2).

Drives ``DockerSandboxManager`` end-to-end against the local Docker daemon.
Exercises: provision → setup_session_workspace → list_directory →
upload_file → read_file → write_sandbox_file → cleanup_session_workspace →
terminate. Skips ACP/send_message (that needs a real Onyx API server +
LLM provider — covered by Level 3 below).

Usage::

    SANDBOX_BACKEND=docker \\
    SANDBOX_API_SERVER_URL=https://example.com \\
    uv run python backend/scripts/manual_test_docker_sandbox.py

Optional env overrides:
    SANDBOX_CONTAINER_IMAGE   (default: onyxdotapp/sandbox:v0.1.44)
    SANDBOX_DOCKER_NETWORK    (default: onyx_craft_sandbox)
"""

from __future__ import annotations

import os
import sys
import time
from uuid import uuid4


def _patch_filestore() -> None:
    """Bypass DB / object-store wiring — we don't exercise snapshots here.

    SnapshotManager grabs a real FileStore at init. For Level 1 we don't
    call create_snapshot/restore_snapshot, so we can swap a no-op stub.
    """
    from onyx.file_store import file_store as fs_module

    class _NullFileStore:
        def save_file(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("save_file not exercised in Level 1")

        def read_file(self, *_a, **_kw):  # type: ignore[no-untyped-def]
            raise RuntimeError("read_file not exercised in Level 1")

        def delete_file(self, *_a, **_kw):  # type: ignore[no-untyped-def]
            pass

        def get_file_size(self, *_a, **_kw):  # type: ignore[no-untyped-def]
            return None

    # ty/mypy: monkeypatching the module attribute; runtime-typed _NullFileStore
    # satisfies SnapshotManager's structural use of FileStore.
    setattr(fs_module, "get_default_file_store", lambda: _NullFileStore())


def main() -> int:
    # Set required env BEFORE importing the manager so config picks them up.
    os.environ.setdefault("SANDBOX_BACKEND", "docker")
    os.environ.setdefault("SANDBOX_API_SERVER_URL", "https://example.invalid")

    _patch_filestore()

    from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
        DockerSandboxManager,
    )
    from onyx.server.features.build.sandbox.models import LLMProviderConfig

    # Reset singleton so this script can be re-run in the same shell.
    DockerSandboxManager._instance = None  # type: ignore[attr-defined]

    mgr = DockerSandboxManager()

    sandbox_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()
    tenant_id = "manual-smoke"

    llm = LLMProviderConfig(
        provider="openai",
        model_name="gpt-4o-mini",
        api_key="sk-not-used-in-this-test",
        api_base=None,
    )

    print(f"[1/8] provision sandbox={sandbox_id}")
    info = mgr.provision(
        sandbox_id=sandbox_id,
        user_id=user_id,
        tenant_id=tenant_id,
        llm_config=llm,
        onyx_pat="pat-not-used-in-this-test",
    )
    print(f"      -> {info.directory_path}  status={info.status.name}")

    print("[2/8] health_check")
    healthy = mgr.health_check(sandbox_id)
    print(f"      -> healthy={healthy}")
    assert healthy, "container should be running"

    print(f"[3/8] setup_session_workspace session={session_id}")
    t0 = time.time()
    mgr.setup_session_workspace(
        sandbox_id=sandbox_id,
        session_id=session_id,
        llm_config=llm,
        nextjs_port=None,  # skip Next.js to keep the test fast & headless
        skills_section="(no skills)",
    )
    print(f"      -> done in {time.time() - t0:.1f}s")

    print("[4/8] session_workspace_exists")
    exists = mgr.session_workspace_exists(sandbox_id, session_id)
    print(f"      -> {exists}")
    assert exists, "session workspace should be present after setup"

    print("[5/8] list_directory outputs/")
    entries = mgr.list_directory(sandbox_id, session_id, "outputs")
    print(f"      -> {len(entries)} entries: {[e.name for e in entries[:6]]}...")
    assert any(e.name == "web" for e in entries), "expected outputs/web from template"

    print("[6/8] upload_file → attachments/")
    payload = b"hello docker sandbox PR 2\n"
    path = mgr.upload_file(sandbox_id, session_id, "smoke.txt", payload)
    print(f"      -> uploaded to {path}")

    read_back = mgr.read_file(sandbox_id, session_id, path)
    assert read_back == payload, f"round-trip mismatch: {read_back!r}"
    print(f"      -> read_file round-trip OK ({len(read_back)} bytes)")

    print("[7/8] list_session_workspaces")
    sessions = mgr.list_session_workspaces(sandbox_id)
    print(f"      -> {sessions}")
    assert session_id in sessions, "our session must be listed"

    print("[8/8] cleanup_session_workspace + terminate")
    mgr.cleanup_session_workspace(sandbox_id, session_id, nextjs_port=None)
    assert not mgr.session_workspace_exists(sandbox_id, session_id)
    mgr.terminate(sandbox_id)
    assert not mgr.health_check(sandbox_id), "container should be gone"
    print("      -> cleaned up")

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
