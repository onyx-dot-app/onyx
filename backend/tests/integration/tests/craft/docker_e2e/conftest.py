"""Docker-e2e fixtures layered on the craft base conftest."""

from __future__ import annotations

import subprocess
from typing import NamedTuple
from typing import Protocol
from uuid import UUID

import pytest

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.enums import SandboxStatus
from onyx.db.external_app import create_external_app
from onyx.db.external_app import get_built_in_external_app
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser


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
    ) -> subprocess.CompletedProcess[str]: ...


class ProvisionSandbox(Protocol):
    def __call__(
        self,
        user: DATestUser,
        *,
        llm_provider_type: str | None = None,
        llm_model_name: str | None = None,
    ) -> DockerSandbox: ...


def _container_name(sandbox_id: str) -> str:
    return f"sandbox-{sandbox_id.split('-')[0]}"


def _docker_exec(
    container: str,
    cmd: list[str],
    *,
    timeout: float = 30.0,
    user: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["docker", "exec"]
    if user is not None:
        command.extend(["--user", user])
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
) -> DockerSandbox:
    # Both default to None on the create request, so passing them through
    # unconditionally is equivalent to omitting them.
    session = BuildSessionManager.create(
        user,
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


@pytest.fixture(scope="session")
def docker_exec() -> DockerExec:
    return _docker_exec


@pytest.fixture(scope="session")
def provision_sandbox() -> ProvisionSandbox:
    return _provision_sandbox


@pytest.fixture(scope="module")
def slack_external_app() -> None:
    """
    Seeds Slack directly with ``enabled=True`` and an ``ASK`` policy on
    ``slack.messages.write`` so the gate matcher claims ``chat.postMessage``.

    Unlike the cloud migration that seeds built-in apps per tenant (when
    ``AUTO_PROVISION_DEFAULT_EXTERNAL_APPS=true``), this skips real credentials
    and the full action catalog -- the test only needs the one gated action.
    Re-seed is a no-op when the row already exists.
    """
    with get_session_with_tenant(tenant_id="public") as db:
        existing = get_built_in_external_app(db, ExternalAppType.SLACK)
        if existing is None:
            create_external_app(
                db_session=db,
                name="Slack",
                description="Slack integration for gate-flow e2e tests.",
                bundle_file_id="",
                bundle_sha256="",
                app_type=ExternalAppType.SLACK,
                upstream_url_patterns=["https://slack\\.com/api/.*"],
                auth_template={"Authorization": "Bearer {access_token}"},
                organization_credentials={"access_token": "fake-test-token"},
                enabled=True,
                is_public=True,
                action_policies={"slack.messages.write": EndpointPolicy.ASK},
            )
            db.commit()
