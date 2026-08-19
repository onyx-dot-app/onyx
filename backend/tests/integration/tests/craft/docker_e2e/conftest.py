"""Docker-e2e fixtures layered on the craft base conftest."""

from __future__ import annotations

import subprocess
import time
from typing import NamedTuple, Protocol
from uuid import UUID

import pytest

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import EndpointPolicy, ExternalAppType, SandboxStatus
from onyx.db.external_app import (
    associate_built_in_skill__no_commit,
    create_external_app,
    get_built_in_external_app,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    SANDBOX_EXEC_ENV,
    SANDBOX_EXEC_USER,
)
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.webapp_preview import (
    WEBAPP_BOOTSTRAP_TIMEOUT_S,
    truncate_output,
    verify_webapp_bootstrap,
    webapp_bootstrap_command,
    webapp_install_check_command,
    webapp_logs_command,
)


class DockerSandbox(NamedTuple):
    session_id: UUID
    container_name: str


class DockerExec(Protocol):
    def __call__(
        self,
        container: str,
        cmd: list[str],
        *,
        timeout: float = 30.0,
        user: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class ProvisionSandbox(Protocol):
    def __call__(
        self,
        user: DATestUser,
        *,
        llm_provider_type: str | None = None,
        llm_model_name: str | None = None,
        headless: bool = True,
    ) -> DockerSandbox: ...


def _container_name(sandbox_id: str) -> str:
    return f"sandbox-{sandbox_id.split('-')[0]}"


def remove_container(container_name: str) -> None:
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=30.0,
            check=False,
        )
    except Exception as exc:
        print(f"WARNING: failed to remove container {container_name!r}: {exc}")


def _docker_exec(
    container: str,
    cmd: list[str],
    *,
    timeout: float = 30.0,
    user: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["docker", "exec"]
    if user is not None:
        command.extend(["--user", user])
    for key, value in (env or {}).items():
        command.extend(["-e", f"{key}={value}"])
    command.extend([container, *cmd])
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _provision_sandbox(
    user: DATestUser,
    *,
    llm_provider_type: str | None = None,
    llm_model_name: str | None = None,
    headless: bool = True,
) -> DockerSandbox:
    # Both default to None on the create request, so passing them through
    # unconditionally is equivalent to omitting them.
    session = BuildSessionManager.create(
        user,
        headless=headless,
        llm_provider_type=llm_provider_type,
        llm_model_name=llm_model_name,
    )
    sandbox = session.sandbox
    assert sandbox is not None, f"Session response missing sandbox: {session!r}"
    assert sandbox.status == SandboxStatus.RUNNING, (
        f"Sandbox not RUNNING after create: {sandbox.status!r}"
    )
    return DockerSandbox(
        session_id=UUID(session.id),
        container_name=_container_name(sandbox.id),
    )


def start_session_webapp(container: str, session_id: UUID) -> str:
    """Run the lazy webapp bootstrap in-container, standing in for the agent's
    `webapp` tool, and return the script's output.

    Carries the sandbox user's HOME as well as its uid: under the egress proxy
    the container runs as root, so a bare ``--user 1000:1000`` would leave
    HOME=/root and diverge from the agent's real privilege context.
    """
    started_at = time.monotonic()
    try:
        result = _docker_exec(
            container,
            ["sh", "-c", webapp_bootstrap_command(session_id)],
            timeout=WEBAPP_BOOTSTRAP_TIMEOUT_S,
            user=SANDBOX_EXEC_USER,
            env=SANDBOX_EXEC_ENV,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"start-webapp.sh did not finish within "
            f"{WEBAPP_BOOTSTRAP_TIMEOUT_S}s for session {session_id}:\n"
            f"{session_webapp_logs(container, session_id)}"
        )
    elapsed_s = time.monotonic() - started_at
    output = f"{result.stdout}{result.stderr}"
    install_state = _docker_exec(
        container,
        ["sh", "-c", webapp_install_check_command(session_id)],
        user=SANDBOX_EXEC_USER,
        env=SANDBOX_EXEC_ENV,
    ).stdout.strip()
    verify_webapp_bootstrap(
        session_id,
        output=output,
        install_state=install_state,
        elapsed_s=elapsed_s,
    )
    return output


def session_webapp_logs(container: str, session_id: UUID) -> str:
    result = _docker_exec(
        container,
        ["sh", "-c", webapp_logs_command(session_id)],
        user=SANDBOX_EXEC_USER,
        env=SANDBOX_EXEC_ENV,
    )
    return truncate_output(f"{result.stdout}{result.stderr}")


@pytest.fixture(scope="session")
def docker_exec() -> DockerExec:
    return _docker_exec


@pytest.fixture(scope="session")
def provision_sandbox() -> ProvisionSandbox:
    return _provision_sandbox


@pytest.fixture(scope="module")
def slack_external_app() -> None:
    """
    Seeds Slack directly with an ``ASK`` policy on
    ``slack.messages.write`` so the gate matcher claims ``chat.postMessage``.

    Unlike the cloud migration that seeds built-in apps per tenant (when
    ``AUTO_PROVISION_DEFAULT_EXTERNAL_APPS=true``), this skips real credentials
    and the full action catalog -- the test only needs the one gated action.
    Re-seed is a no-op when the row already exists.
    """
    with get_session_with_tenant(tenant_id="public") as db:
        existing = get_built_in_external_app(db, ExternalAppType.SLACK)
        if existing is None:
            app = create_external_app(
                db_session=db,
                name="Slack",
                app_type=ExternalAppType.SLACK,
                upstream_url_patterns=["https://slack\\.com/api/.*"],
                auth_template={"Authorization": "Bearer {access_token}"},
                organization_credentials={"access_token": "fake-test-token"},
                action_policies={"slack.messages.write": EndpointPolicy.ASK},
            )
            associate_built_in_skill__no_commit(db, app)
            db.commit()
