from __future__ import annotations

import os
from collections.abc import Generator
from uuid import uuid4

import httpx
import pytest

from onyx.auth.schemas import UserRole as AuthUserRole
from tests.integration.common_utils import http_client
from tests.integration.common_utils.constants import ADMIN_USER_NAME
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import build_email
from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.conftest import _RetryingTransport

pytest_plugins = ("tests.integration.tests.craft.k8s.k8s_fixtures",)


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
        transport=_RetryingTransport(),
        timeout=httpx.Timeout(120.0, connect=10.0),
    )
    http_client.set_test_client(real_client)
    try:
        yield real_client
    finally:
        real_client.close()
        http_client.set_test_client(None)


@pytest.fixture(scope="session", autouse=True)
def seed_dev_license_for_session() -> None:
    """No-op override; no API routes requiring a dev license are called."""
    return None


def _is_user_already_exists(response: httpx.Response) -> bool:
    # Only a 400 with detail REGISTER_USER_ALREADY_EXISTS counts; a malformed
    # request also 400s but must not be treated as "exists".
    if response.status_code == 409:
        return True
    if response.status_code != 400:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return (
        isinstance(body, dict) and body.get("detail") == "REGISTER_USER_ALREADY_EXISTS"
    )


def _create_or_login_seed_admin() -> DATestUser:
    try:
        return UserManager.create(name=ADMIN_USER_NAME)
    except httpx.HTTPStatusError as e:
        if not _is_user_already_exists(e.response):
            raise

    return UserManager.login_as_user(
        DATestUser(
            id="",
            email=build_email(ADMIN_USER_NAME),
            password=DEFAULT_PASSWORD,
            headers=GENERAL_HEADERS.copy(),
            role=AuthUserRole.BASIC,
            is_active=True,
        )
    )


@pytest.fixture(scope="session", autouse=True)
def _module_reset_and_seed(  # noqa: ARG001
    _test_client: httpx.Client,
) -> Generator[DATestUser, None, None]:
    """Seed through the deployed API without resetting the live cluster DB.

    Name must match the parent craft autouse fixture so it overrides (rather
    than runs alongside) the parent's admin seeding.
    """
    admin = _create_or_login_seed_admin()
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
