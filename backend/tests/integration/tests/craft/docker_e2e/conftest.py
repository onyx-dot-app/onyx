"""
Overrides the integration framework's in-process ``_test_client`` autouse with a
real httpx.Client, plus seeds a Slack ``external_app`` so the gate flow can
fire.

The default ``tests/integration/conftest.py::_test_client`` builds an in-process
FastAPI ``TestClient``. That works for tests where the "api_server" being
asserted against is the test process itself. It does NOT work for the docker e2e
-- those tests provision real sandbox containers via the docker socket, and
``DockerSandboxManager.provision`` blocks on a health-check against
``http://sandbox-<id8>:4096``, a hostname that only resolves inside the
``onyx_craft_sandbox`` bridge network. The in-process api_server lives on the
host net and can never resolve it.

The fix: hit the dockerized api_server (port-published at host 8080 by
``docker-compose.dev.yml``) instead. From the host, ``localhost:8080`` -> the
api_server container, which is on both the default and ``onyx_craft_sandbox``
networks and CAN resolve sandbox hostnames.

The Slack seeding is needed because the default deployment has no external apps
configured. ``ExternalAppActionMatcher`` only claims a request if some app's
``upstream_url_patterns`` matches the URL; without a Slack row,
``chat.postMessage`` is treated as off-catalog and not gated.
``AUTO_PROVISION_DEFAULT_EXTERNAL_APPS`` defaults to off and the K8s lane
doesn't actually run ``test_approval_gate.py`` either (it's not listed in the
lane's paths filter or pytest args), so this fixture is the first place to wire
the seeding in CI.

This conftest is intentionally scoped to ``docker_e2e/`` only. Sibling craft
tests under ``tests/integration/tests/craft/`` keep the in-process model.
"""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from typing import Protocol
from uuid import UUID

import httpx
import pytest

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import create_external_app
from onyx.db.external_app import get_built_in_external_app
from tests.integration.common_utils import http_client
from tests.integration.common_utils.constants import ADMIN_USER_NAME
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


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
    def __call__(self, user: DATestUser) -> tuple[UUID, str]: ...


def _container_name(sandbox_id: str) -> str:
    """Docker manager names containers ``sandbox-<id8>``."""
    return f"sandbox-{sandbox_id.split('-')[0]}"


def _docker_exec(
    container: str,
    cmd: list[str],
    *,
    timeout: float = 30.0,
    user: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Runs ``cmd`` inside ``container`` and captures stdout/stderr."""
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


def _provision_sandbox(user: DATestUser) -> tuple[UUID, str]:
    """
    Creates a session via the real API and returns its (session_id, container).

    The create endpoint is synchronous -- by the time it returns, the sandbox
    container is RUNNING and opencode-serve has passed its health check.
    """
    session = BuildSessionManager.create(user)
    sandbox = session["sandbox"]
    assert sandbox is not None, f"Session response missing sandbox: {session!r}"
    assert sandbox["status"].upper() == "RUNNING", (
        f"Sandbox not RUNNING after create: {sandbox['status']!r}"
    )
    return UUID(session["id"]), _container_name(sandbox["id"])


@pytest.fixture(scope="session")
def docker_exec() -> DockerExec:
    return _docker_exec


@pytest.fixture(scope="session")
def provision_sandbox() -> ProvisionSandbox:
    return _provision_sandbox


@pytest.fixture(scope="session", autouse=True)
def _test_client() -> Generator[httpx.Client, None, None]:
    """
    Replaces the parent ``_test_client`` with an httpx.Client targeting the
    dockerized api_server. Same fixture name + scope so pytest picks the child
    override per directory.
    """
    real_client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))
    http_client.set_test_client(real_client)
    try:
        yield real_client
    finally:
        real_client.close()
        http_client.set_test_client(None)


@pytest.fixture(scope="session", autouse=True)
def _install_playwright() -> None:
    """No-op override: No docker_e2e test uses playwright."""
    return None


@pytest.fixture(scope="session", autouse=True)
def _start_celery_workers() -> Generator[None, None, None]:
    """No-op override: The ``background`` container already runs the workers."""
    yield None


@pytest.fixture(scope="session", autouse=True)
def _module_reset_and_seed() -> None:
    """
    Override: Skip the parent's ``reset_all()``. The dockerized api_server holds
    pooled postgres connections; an out-of-process ``alembic downgrade base``
    deadlocks against those. Admin + LLM provider seeding is session-scoped
    because this directory has multiple test modules and ``UserManager.create``
    is not idempotent for the fixed admin email.
    """
    admin = UserManager.create(name=ADMIN_USER_NAME)
    LLMProviderManager.create(user_performing_action=admin, api_key="test-api-key")


@pytest.fixture(scope="module")
def slack_external_app() -> None:
    """
    Seeds Slack directly with ``enabled=True`` and an ``ASK`` policy on
    ``slack.messages.write`` so the gate matcher claims ``chat.postMessage``.

    Unlike ``provision_built_in_external_apps`` (which the cloud tenant-creation
    path runs when ``AUTO_PROVISION_DEFAULT_EXTERNAL_APPS=true``), this skips
    real credentials and the full action catalog -- the test only needs the one
    gated action. Re-seed is a no-op when the row already exists.
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
                # Fake token. An unfillable template short-circuits the ASK gate
                # (forwards bare, no DB row), which breaks every gate-flow test.
                organization_credentials={"access_token": "fake-test-token"},
                enabled=True,
                is_public=True,
                action_policies={"slack.messages.write": EndpointPolicy.ASK},
            )
            db.commit()
