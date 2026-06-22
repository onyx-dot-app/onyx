"""Fixtures for the Craft HTTP-contract integration lane (``craft_api``).

Unlike the sibling ``craft`` suite (which needs a real Docker/K8s sandbox and
runs in the compose lane against an out-of-process api_server), this directory
runs in the STANDARD integration matrix: the global
``backend/tests/integration/conftest.py`` builds an in-process
``TestClient(app)`` against real Postgres + Redis, and these tests drive the
Craft build/session HTTP endpoints through it.

No real sandbox is provisioned. An autouse fixture installs a configured
``StubSandboxManager`` as the process-wide sandbox manager singleton, so every
build endpoint that would otherwise provision/health-check/read a container
instead gets deterministic in-memory responses. This keeps the lane fast and
hermetic while still exercising the real FastAPI routing, auth, DB writes, and
SessionManager orchestration.

The stub is configured for the full surface the moved Class-A tests reach:
session create/delete, file listing/read, upload stats + writes, the user-
library cold-start push, opencode-session prewarm, and the webapp proxy's
``get_webapp_url`` (pointed at an unreachable URL so the proxy falls back to
its branded offline page — which the webapp tests assert).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.sandbox import factory
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.scheduled_tasks import api as scheduled_tasks_api
from tests.common.craft.stubs import StubSandboxManager
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

# An intentionally unreachable internal URL. The webapp proxy resolves this via
# ``get_webapp_url`` and then tries to connect; the connection fails fast and
# the proxy renders its offline page — exactly the path the webapp tests pin.
_UNREACHABLE_WEBAPP_URL = "http://127.0.0.1:1/unreachable"


def _make_configured_stub() -> StubSandboxManager:
    """Build a ``StubSandboxManager`` covering every method the Craft build and
    session endpoints invoke in this lane.

    Provisioning is instant and in-memory, so tests create per-test sessions
    cheaply rather than sharing one.
    """
    stub = StubSandboxManager()

    # Provisioning + lifecycle.
    stub.provision_returns = SandboxInfo(
        sandbox_id=uuid4(),
        directory_path="/workspace",
        status=SandboxStatus.RUNNING,
        last_heartbeat=datetime.now(tz=timezone.utc),
    )
    stub.health_check_returns = True
    stub.session_workspace_exists_returns = True
    stub.setup_session_workspace_silent = True
    stub.cleanup_session_workspace_silent = True
    stub.terminate_silent = True
    stub.restore_snapshot_silent = True

    # Skills + user-library cold-start hydration both flow through
    # ``push_to_sandbox`` -> ``write_files_to_sandbox`` on session create.
    stub.write_files_to_sandbox_silent = True
    stub.write_sandbox_file_silent = True

    # Filesystem reads (list/download/upload/stats).
    stub.list_directory_returns = []
    stub.read_file_returns = b""
    stub.upload_file_returns = "attachments/file"
    stub.get_upload_stats_returns = (0, 0)

    # ``ensure_opencode_session`` is already defaulted on the stub; leave it.

    # Webapp proxy: resolvable but unreachable so the proxy serves its offline page.
    stub.get_webapp_url_returns = _UNREACHABLE_WEBAPP_URL

    return stub


@pytest.fixture(autouse=True)
def _disable_scheduled_task_executor_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep scheduled-task HTTP tests from starting real worker execution."""

    def _noop_enqueue(_run_id: UUID) -> None:
        return None

    monkeypatch.setattr(scheduled_tasks_api, "_enqueue_executor", _noop_enqueue)


@pytest.fixture(autouse=True)
def _stub_sandbox_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[StubSandboxManager, None, None]:
    """Install a configured stub as the process-wide sandbox manager.

    Setting ``factory._sandbox_manager_instance`` is sufficient because every
    caller goes through ``factory.get_sandbox_manager()`` (which returns the
    cached instance). Patching ``factory.get_sandbox_manager`` too is
    belt-and-suspenders for any direct reference.
    """
    stub = _make_configured_stub()
    monkeypatch.setattr(factory, "_sandbox_manager_instance", stub)
    monkeypatch.setattr(factory, "get_sandbox_manager", lambda: stub)
    yield stub


@pytest.fixture
def llm_provider(admin_user: DATestUser) -> DATestLLMProvider:
    """Seed a default LLM provider without requiring a real provider key."""
    return LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key="test-api-key",
    )


@pytest.fixture
def shared_session(
    llm_provider: object,  # noqa: ARG001 — ensures a default LLM provider (and admin) exist
) -> tuple[DATestUser, UUID]:
    """A single created session owned by a dedicated user, for read-only /
    validation / ownership / offline-proxy checks.

    Provisioning is instant under the stub, so this is created fresh per test
    (function scope) rather than shared across a module. Owned by a per-test
    user isolated from the function-scoped ``admin_user`` / ``basic_user``
    fixtures so a sibling create/delete can't disturb it. ``llm_provider``
    transitively guarantees an admin user exists, so the created user lands as
    a non-admin basic account.
    """
    owner = UserManager.create(name=f"craft-api-shared-{uuid4().hex[:8]}")
    body = BuildSessionManager.create(owner)
    return owner, UUID(body["id"])
