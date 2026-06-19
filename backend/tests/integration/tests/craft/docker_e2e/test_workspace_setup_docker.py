"""Docker-backend workspace setup end-to-end tests.

Runs against the full Craft docker-compose stack and provisions a real sandbox
through the live api_server. This file pins Docker-specific session setup
behavior that unit and in-process integration tests cannot observe: ownership
inside the container, user-writable workspace paths, managed workspace
hydration, and file API operations backed by docker exec.
"""

from __future__ import annotations

from uuid import UUID
from uuid import uuid4

import pytest

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    SANDBOX_EXEC_USER,
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


@pytest.fixture
def workspace_user() -> DATestUser:
    return UserManager.create(name=f"craft_docker_workspace_{uuid4().hex[:8]}")


@pytest.fixture
def workspace_sandbox(
    workspace_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> tuple[UUID, str]:
    return provision_sandbox(workspace_user)


def test_session_setup_creates_user_writable_workspace(
    workspace_user: DATestUser,
    workspace_sandbox: tuple[UUID, str],
    docker_exec: DockerExec,
) -> None:
    """
    Provisioning must hydrate the managed workspace and per-session directory
    with uid 1000 ownership. This catches docker-exec setup regressions where
    the API writes as root, then the sandbox user cannot write or replace files.
    """
    session_id, container = workspace_sandbox
    session_path = f"/workspace/sessions/{session_id}"

    required_paths = [
        "/workspace",
        "/workspace/sessions",
        "/workspace/managed",
        "/workspace/managed/skills",
        "/workspace/managed/user_library",
        session_path,
        f"{session_path}/outputs",
        f"{session_path}/outputs/web",
        f"{session_path}/attachments",
        f"{session_path}/.opencode",
    ]
    stat_script = "\n".join(
        f'stat -c "%u:%g %F %n" "{path}"' for path in required_paths
    )
    stat_result = docker_exec(container, ["sh", "-c", stat_script])
    assert stat_result.returncode == 0, (
        "Required workspace paths missing after provision. "
        f"stdout={stat_result.stdout!r} stderr={stat_result.stderr!r}"
    )
    for line in stat_result.stdout.splitlines():
        assert line.startswith(f"{SANDBOX_EXEC_USER} "), (
            f"Workspace path not owned by sandbox user: {line!r}"
        )

    symlink_result = docker_exec(
        container,
        [
            "sh",
            "-c",
            (
                f'test -f "{session_path}/AGENTS.md" && '
                f'test -L "{session_path}/.opencode/skills" && '
                f'test "$(readlink "{session_path}/.opencode/skills")" = '
                '"/workspace/managed/skills"'
            ),
        ],
    )
    assert symlink_result.returncode == 0, (
        "Expected AGENTS.md plus .opencode/skills symlink after provision. "
        f"stdout={symlink_result.stdout!r} stderr={symlink_result.stderr!r}"
    )

    write_check = docker_exec(
        container,
        [
            "sh",
            "-c",
            (
                "set -e\n"
                'printf ok > "/workspace/managed/.write-check"\n'
                f'printf ok > "{session_path}/.write-check"\n'
                f'printf ok > "{session_path}/attachments/.write-check"\n'
                f'printf ok > "{session_path}/outputs/web/.write-check"\n'
                'rm -f "/workspace/managed/.write-check"\n'
                f'rm -f "{session_path}/.write-check"\n'
                f'rm -f "{session_path}/attachments/.write-check"\n'
                f'rm -f "{session_path}/outputs/web/.write-check"\n'
            ),
        ],
        user=SANDBOX_EXEC_USER,
    )
    assert write_check.returncode == 0, (
        "Sandbox user could not write to provisioned workspace directories. "
        f"stdout={write_check.stdout!r} stderr={write_check.stderr!r}"
    )

    private_file = "outputs/private/private.txt"
    private_setup = docker_exec(
        container,
        [
            "sh",
            "-c",
            (
                "set -e\n"
                f'mkdir -p "{session_path}/outputs/private"\n'
                f'printf private > "{session_path}/{private_file}"\n'
                f'chmod 700 "{session_path}/outputs/private"\n'
                f'chmod 600 "{session_path}/{private_file}"\n'
            ),
        ],
        user=SANDBOX_EXEC_USER,
    )
    assert private_setup.returncode == 0, (
        "Could not seed sandbox-user-private output file. "
        f"stdout={private_setup.stdout!r} stderr={private_setup.stderr!r}"
    )

    private_listing = BuildSessionManager.list_files(
        workspace_user, session_id, "outputs/private"
    )
    private_names = {entry["name"] for entry in private_listing["entries"]}
    assert "private.txt" in private_names

    downloaded = BuildSessionManager.download_artifact(
        workspace_user, session_id, private_file
    )
    assert downloaded == b"private"

    upload_name = f"docker-setup-{uuid4().hex[:8]}.txt"
    upload = BuildSessionManager.upload_file(
        workspace_user,
        session_id,
        filename=upload_name,
        content=b"docker workspace setup check",
    )
    assert upload["filename"] == upload_name
    assert upload["path"] == f"attachments/{upload_name}"

    listing = BuildSessionManager.list_files(workspace_user, session_id, "attachments")
    attachment_names = {entry["name"] for entry in listing["entries"]}
    assert upload_name in attachment_names

    BuildSessionManager.delete_file(workspace_user, session_id, upload["path"])
    post_delete_listing = BuildSessionManager.list_files(
        workspace_user, session_id, "attachments"
    )
    post_delete_names = {entry["name"] for entry in post_delete_listing["entries"]}
    assert upload_name not in post_delete_names
