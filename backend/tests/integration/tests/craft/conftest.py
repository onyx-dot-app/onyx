"""Fixtures for craft integration tests."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Generator
from uuid import UUID
from uuid import uuid4

import httpx
import pytest

from onyx.auth.schemas import UserRole
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.db.sandbox import get_running_sandboxes
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.integration.common_utils import http_client
from tests.integration.common_utils.constants import ADMIN_USER_NAME
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import build_email
from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module", autouse=True)
def _reap_module_sandboxes() -> Generator[None, None, None]:
    yield
    if SANDBOX_BACKEND != SandboxBackend.DOCKER:
        return
    SqlEngine.init_engine(pool_size=2, max_overflow=2)
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as db:
        running = get_running_sandboxes(db)
    manager = get_sandbox_manager()
    for sandbox in running:
        with contextlib.suppress(Exception):
            manager.terminate(sandbox.id)


_CONNECT_RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)
_SAFE_RETRY_EXCEPTIONS = (
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)
_RETRY_STATUSES = {502, 504}
_SAFE_RETRY_METHODS = {"GET", "HEAD", "OPTIONS"}
_MAX_ATTEMPTS = 3


class _RetryingTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        backoff = 0.5
        for attempt in range(_MAX_ATTEMPTS):
            last = attempt == _MAX_ATTEMPTS - 1
            try:
                response = super().handle_request(request)
            except _CONNECT_RETRY_EXCEPTIONS:
                if last:
                    raise
                time.sleep(backoff)
                backoff *= 2
                continue
            except _SAFE_RETRY_EXCEPTIONS:
                if last or request.method.upper() not in _SAFE_RETRY_METHODS:
                    raise
                time.sleep(backoff)
                backoff *= 2
                continue
            if (
                response.status_code in _RETRY_STATUSES
                and request.method.upper() in _SAFE_RETRY_METHODS
                and not last
            ):
                response.close()
                time.sleep(backoff)
                backoff *= 2
                continue
            return response
        raise AssertionError("unreachable")


def _create_or_login_user(name: str, expected_role: UserRole) -> DATestUser:
    try:
        user = UserManager.create(name=name)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400:
            raise
        user = UserManager.login_as_user(
            DATestUser(
                id="",
                email=build_email(name),
                password=DEFAULT_PASSWORD,
                headers=GENERAL_HEADERS.copy(),
                role=expected_role,
                is_active=True,
            )
        )
    if user.role != expected_role:
        raise AssertionError(
            f"Expected {name} to have role {expected_role.value}, got {user.role.value}"
        )
    return user


@pytest.fixture(scope="session", autouse=True)
def _test_client() -> Generator[httpx.Client, None, None]:
    """httpx client targeting the real out-of-process api_server."""
    real_client = httpx.Client(
        transport=_RetryingTransport(),
        timeout=httpx.Timeout(60.0, connect=10.0),
    )
    http_client.set_test_client(real_client)
    try:
        yield real_client
    finally:
        real_client.close()
        http_client.set_test_client(None)


@pytest.fixture(scope="session", autouse=True)
def _install_playwright() -> None:
    """No-op override: craft API-boundary tests don't use playwright."""
    return None


@pytest.fixture(scope="session", autouse=True)
def _start_celery_workers() -> Generator[None, None, None]:
    """No-op override: the deployed ``background`` worker runs the celery tasks."""
    yield None


@pytest.fixture(scope="session", autouse=True)
def _module_reset_and_seed() -> None:
    """Skip the parent's reset_all() (out-of-process downgrade deadlocks against
    the api_server's pooled connections); seed an admin + LLM provider."""
    admin = _create_or_login_user(ADMIN_USER_NAME, UserRole.ADMIN)
    LLMProviderManager.create(user_performing_action=admin, api_key="test-api-key")


@pytest.fixture
def llm_provider(admin_user: DATestUser) -> DATestLLMProvider:
    """Override the global fixture: seed a provider with a fake key (the compose
    lane has no OPENAI_API_KEY and craft tests make no live call)."""
    return LLMProviderManager.create(
        user_performing_action=admin_user, api_key="test-api-key"
    )


@pytest.fixture(scope="module")
def shared_session(
    request: pytest.FixtureRequest,
) -> Generator[tuple[DATestUser, UUID], None, None]:
    """One provisioned session + sandbox, shared across a module's tests.

    Owned by a per-module user isolated from the function-scoped
    admin_user/basic_user so a sibling's create/delete can't terminate its
    sandbox. Use only for read-only / validation / ownership checks; tests that
    mutate-and-assert session state must create their own session.
    """
    slug = request.module.__name__.rsplit(".", 1)[-1].replace("_", "-")
    owner = UserManager.create(name=f"craft-shared-{slug}-{uuid4().hex[:8]}")
    body = BuildSessionManager.create(owner)
    sandbox = body.get("sandbox")
    try:
        yield owner, UUID(body["id"])
    finally:
        if sandbox and sandbox.get("id"):
            try:
                get_sandbox_manager().terminate(UUID(sandbox["id"]))
            except Exception:
                pass
