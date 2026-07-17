"""
Docker-backend snapshot + restore round-trip against the full Craft compose
stack.

Seeds markers in the session outputs and opencode's data home, forces the
idle-cleanup beat to reap the sandbox (snapshot both kinds + tear down), then
restores via the API and asserts both survived a real re-provision -- covering
the session-snapshot and opencode chat-history round-trips end to end.
"""

from __future__ import annotations

import datetime
import time
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    OPENCODE_DATA_DIR,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    SANDBOX_EXEC_USER,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    SESSIONS_ROOT,
)
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.docker_e2e.conftest import DockerExec
from tests.integration.tests.craft.docker_e2e.conftest import ProvisionSandbox

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.DOCKER,
    reason="Docker integration tests require SANDBOX_BACKEND=docker.",
)

_TENANT_ID = "public"
# The cleanup beat ticks every 60s; allow a couple of cycles plus snapshot and
# terminate time before giving up.
_REAP_TIMEOUT_SECONDS = 180.0
_REAP_POLL_INTERVAL_SECONDS = 3.0


@pytest.fixture
def snapshot_user() -> DATestUser:
    return UserManager.create(name=f"craft_docker_snapshot_{uuid4().hex[:8]}")


def _force_idle(user_id: UUID) -> UUID:
    """
    Backdate the sandbox heartbeat past the idle timeout; returns sandbox id.
    """
    with get_session_with_tenant(tenant_id=_TENANT_ID) as db:
        sandbox = db.scalar(select(Sandbox).where(Sandbox.user_id == user_id))
        assert sandbox is not None, "Sandbox row missing for user."
        sandbox.last_heartbeat = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(hours=6)
        sandbox_id = sandbox.id
        db.commit()
    return sandbox_id


def _wait_for_reap(sandbox_id: UUID) -> None:
    """Block until the idle-cleanup beat puts the sandbox to sleep."""
    deadline = time.monotonic() + _REAP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with get_session_with_tenant(tenant_id=_TENANT_ID) as db:
            sandbox = db.get(Sandbox, sandbox_id)
            assert sandbox is not None
            if sandbox.status in (SandboxStatus.SLEEPING, SandboxStatus.TERMINATED):
                return
        time.sleep(_REAP_POLL_INTERVAL_SECONDS)
    raise AssertionError(
        f"Sandbox {sandbox_id} was not reaped within {_REAP_TIMEOUT_SECONDS}s "
        "(the idle-cleanup beat / sandbox-queue worker may not be running)."
    )


def test_session_and_opencode_history_survive_snapshot_restore(
    snapshot_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
    docker_exec: DockerExec,
) -> None:
    session_id, container = provision_sandbox(snapshot_user)
    session_path = f"{SESSIONS_ROOT}/{session_id}"

    output_token = uuid4().hex
    history_token = uuid4().hex
    output_file = f"{session_path}/outputs/onyx-roundtrip-output.txt"
    history_file = f"{OPENCODE_DATA_DIR}/onyx-roundtrip-history.txt"

    # Seed one marker in the per-session outputs dir and one in opencode's data
    # home, both as the sandbox user so they round-trip with correct ownership.
    seed = docker_exec(
        container,
        [
            "sh",
            "-c",
            (
                "set -e\n"
                f'mkdir -p "{session_path}/outputs" "{OPENCODE_DATA_DIR}"\n'
                f'printf %s "{output_token}" > "{output_file}"\n'
                f'printf %s "{history_token}" > "{history_file}"\n'
            ),
        ],
        user=SANDBOX_EXEC_USER,
    )
    assert seed.returncode == 0, (
        f"Failed to seed round-trip markers: stdout={seed.stdout!r} "
        f"stderr={seed.stderr!r}"
    )

    # Force the idle reap: snapshots both kinds to the FileStore, then tears
    # down.
    sandbox_id = _force_idle(UUID(snapshot_user.id))
    _wait_for_reap(sandbox_id)

    # The teardown must really have happened -- a surviving writable layer would
    # mask a broken restore.
    gone = docker_exec(container, ["test", "-f", history_file], user=SANDBOX_EXEC_USER)
    assert gone.returncode != 0, (
        "Expected the container/workspace to be gone after the idle reap; "
        "the data-home marker should not still be readable."
    )

    # Reopen the session: re-provision a fresh container and restore both
    # snapshots.
    restored = BuildSessionManager.restore(snapshot_user, session_id)

    # The container name derives from the sandbox id, which restore keeps
    # stable, so `container` still points at the fresh container. Assert it so a
    # future re-key fails here loudly rather than as a cryptic exec error below.
    assert restored.sandbox is not None
    assert restored.sandbox.id == str(sandbox_id), (
        "Restore changed the sandbox id; the container name derived from the "
        "original id is now stale."
    )

    check = docker_exec(
        container,
        ["sh", "-c", f'cat "{output_file}"; printf "|"; cat "{history_file}"'],
        user=SANDBOX_EXEC_USER,
    )
    assert check.returncode == 0, (
        "Restored marker files are missing after re-provision: "
        f"stdout={check.stdout!r} stderr={check.stderr!r}"
    )
    assert check.stdout == f"{output_token}|{history_token}", (
        "Round-trip markers did not survive snapshot + restore: "
        f"got {check.stdout!r}, want {output_token!r}|{history_token!r}"
    )
