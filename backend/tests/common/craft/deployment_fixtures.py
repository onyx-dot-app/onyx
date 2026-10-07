"""Run against an existing deployment, without starting or resetting local services."""

import os
from collections.abc import Generator

import httpx
import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import (
    RetryingTransport,
    set_test_client,
)


@pytest.fixture(scope="session", autouse=True)
def deployed_frontend() -> str:
    frontend: str | None = os.environ.get("SANDBOX_TEST_FRONTEND_URL")
    family: str | None = os.environ.get("SANDBOX_TEST_IP_FAMILY")
    if not any((frontend, family)):
        pytest.skip("Set SANDBOX_TEST_FRONTEND_URL and SANDBOX_TEST_IP_FAMILY")
    if not frontend or family not in {"ipv4", "ipv6"}:
        pytest.fail(
            "Both sandbox deployment settings are required; family must be ipv4 or ipv6"
        )
    url: httpx.URL = httpx.URL(frontend)
    if url.scheme not in {"http", "https"} or url.path != "/":
        pytest.fail(
            "SANDBOX_TEST_FRONTEND_URL must be the frontend origin without /api"
        )
    return frontend.rstrip("/")


# The deployment owns migrations, database initialization, workers and licensing.
@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(scope="session", autouse=True)
def initialize_db() -> None:
    pass


@pytest.fixture(scope="session", autouse=True)
def _start_celery_workers() -> None:
    pass


@pytest.fixture(scope="session", autouse=True)
def seed_dev_license_for_session() -> None:
    pass


# This suite owns its API session and sandbox cleanup. Parent Craft fixtures use host DBs.
@pytest.fixture(scope="module", autouse=True)
def _reap_module_sandboxes() -> None:
    pass


@pytest.fixture(scope="session", autouse=True)
def _module_reset_and_seed() -> None:
    pass


@pytest.fixture(scope="session", autouse=True)
def _test_client(deployed_frontend: str) -> Generator[httpx.Client, None, None]:
    def through_frontend(request: httpx.Request) -> None:
        prefix: str = API_SERVER_URL + "/"
        assert str(request.url).startswith(prefix), request.url
        request.url = httpx.URL(
            deployed_frontend + "/api/" + str(request.url)[len(prefix) :]
        )
        request.headers["host"] = request.url.netloc.decode("ascii")

    with httpx.Client(
        transport=RetryingTransport(),
        timeout=httpx.Timeout(240, connect=10),
        event_hooks={"request": [through_frontend]},
    ) as deployed_client:
        set_test_client(deployed_client)
        try:
            yield deployed_client
        finally:
            set_test_client(None)
