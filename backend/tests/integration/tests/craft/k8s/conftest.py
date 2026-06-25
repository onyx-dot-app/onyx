"""Fixtures for the Craft Kubernetes integration suite."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Generator
from uuid import uuid4

import httpx
import pytest

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.db.sandbox import get_running_sandboxes
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.common.craft.users import create_or_login_admin
from tests.integration.common_utils.constants import ADMIN_USER_NAME
from tests.integration.common_utils.http_client import RetryingTransport
from tests.integration.common_utils.http_client import set_test_client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import suite_sandbox_ids

pytest_plugins = (
    "tests.integration.tests.craft.k8s.k8s_db_fixtures",
    "tests.integration.tests.craft.k8s.k8s_fixtures",
)


@pytest.fixture(scope="module", autouse=True)
def _reap_module_pods() -> Generator[None, None, None]:
    """Safety net for leaked suite sandboxes only.

    Filters to sandboxes this suite provisioned (tracked in
    ``k8s_fixtures._SUITE_SANDBOX_IDS``) so unrelated sandboxes on a shared
    cluster are never terminated.
    """
    yield
    if SANDBOX_BACKEND != SandboxBackend.KUBERNETES:
        return
    suite_ids = suite_sandbox_ids()
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as db:
        leaked = [s for s in get_running_sandboxes(db) if s.id in suite_ids]
    manager = get_sandbox_manager()
    for sandbox in leaked:
        with contextlib.suppress(Exception):
            manager.terminate(sandbox.id)


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    """No-op override; the workflow runs Alembic separately."""
    return None


@pytest.fixture(scope="session", autouse=True)
def _install_playwright() -> None:
    """No-op override; this suite does not use browser automation."""
    return None


@pytest.fixture(scope="session", autouse=True)
def initialize_db() -> None:
    """No-op override; sandbox fixtures initialize SQLAlchemy explicitly."""
    return None


@pytest.fixture(scope="session", autouse=True)
def _start_celery_workers() -> None:
    """No-op override; Helm starts the real in-cluster Celery workers."""
    return None


@pytest.fixture(scope="session", autouse=True)
def _test_client() -> Generator[httpx.Client, None, None]:
    """Bind integration HTTP helpers to the deployed api_server."""
    real_client = httpx.Client(
        transport=RetryingTransport(),
        timeout=httpx.Timeout(120.0, connect=10.0),
    )
    set_test_client(real_client)
    try:
        yield real_client
    finally:
        real_client.close()
        set_test_client(None)


@pytest.fixture(scope="session", autouse=True)
def seed_dev_license_for_session() -> None:
    """No-op override; no API routes requiring a dev license are called."""
    return None


@pytest.fixture(scope="session", autouse=True)
def _module_reset_and_seed(  # noqa: ARG001
    _test_client: httpx.Client,
) -> Generator[DATestUser, None, None]:
    """Seed through the deployed API without resetting the live cluster DB.

    Name must match the parent craft autouse fixture so it overrides (rather
    than runs alongside) the parent's admin seeding.
    """
    admin = create_or_login_admin(ADMIN_USER_NAME)
    provider = LLMProviderManager.create(
        user_performing_action=admin,
        name=f"craft-k8s-openai-{uuid4().hex[:8]}",
        api_key=os.environ.get("OPENAI_API_KEY", "test-api-key"),
        default_model_name="gpt-5-mini",
        set_as_default=False,
    )
    try:
        yield admin
    finally:
        LLMProviderManager.delete(provider, admin)


@pytest.fixture(scope="session")
def k8s_admin_user(_module_reset_and_seed: DATestUser) -> DATestUser:
    return _module_reset_and_seed
