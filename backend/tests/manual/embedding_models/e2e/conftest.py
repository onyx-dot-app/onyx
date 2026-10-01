"""Fixtures for the embedding-model switch e2e suite.

This suite drives a live, already-running Onyx stack over HTTP and changes its
embedding model. It never resets the database and never creates users.

It reuses the Manager helpers in ``tests/integration/common_utils`` but not the
integration conftest (which runs migrations, starts an in-process app and a
Celery fleet, and wipes Postgres). Importing ``tests.integration.common_utils``
does not load that conftest. The pattern follows
``tests/integration/tests/gateway_clients/conftest.py``: swap the shared
``http_client`` for a real ``httpx.Client`` for the duration of the module.

The target stack is ``API_SERVER_PROTOCOL://API_SERVER_HOST:API_SERVER_PORT``,
the same env vars the Managers read. The suite has no default target and no
default admin: ``API_SERVER_HOST``, ``API_SERVER_PORT``, ``ONYX_E2E_ADMIN_EMAIL``
and ``ONYX_E2E_ADMIN_PASSWORD`` must be set. Port 8080 (the port of the normal
dev stack) needs one more opt-in.
"""

import os
from collections.abc import Generator
from uuid import uuid4

import httpx
import pytest

from tests.integration.common_utils import http_client
from tests.integration.common_utils.constants import API_SERVER_URL, GENERAL_HEADERS
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import (
    DATestAPIKey,
    DATestCCPair,
    DATestUser,
)
from tests.manual.gates import README_PATH, env_flag

ADMIN_EMAIL_ENV = "ONYX_E2E_ADMIN_EMAIL"
ADMIN_PASSWORD_ENV = "ONYX_E2E_ADMIN_PASSWORD"

# The Managers build URLs from these at import time, with a fallback to
# http://127.0.0.1:8080. The suite reads the raw env, so the fallback never
# selects a target.
API_SERVER_HOST_ENV = "API_SERVER_HOST"
API_SERVER_PORT_ENV = "API_SERVER_PORT"
# Accepted only as a cross-check.
API_SERVER_URL_ENV = "API_SERVER_URL"
# The normal dev stack listens on 8080. Targeting it needs this opt-in too.
DEV_STACK_PORT = "8080"
ALLOW_DEV_STACK_PORT_ENV = "ONYX_EMBEDDING_E2E_ALLOW_PORT_8080"

HTTP_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


@pytest.fixture(scope="module", autouse=True)
def _live_api_server() -> Generator[None, None, None]:
    """Point the shared http_client at the live api_server under test."""
    missing = [
        name
        for name in (API_SERVER_HOST_ENV, API_SERVER_PORT_ENV)
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        pytest.fail(
            f"Set {' and '.join(missing)} to the api_server of a disposable "
            "stack. This suite changes the stack, so it has no default target. "
            f"See {README_PATH}."
        )
    port = os.environ[API_SERVER_PORT_ENV].strip()
    if port == DEV_STACK_PORT and not env_flag(ALLOW_DEV_STACK_PORT_ENV):
        pytest.fail(
            f"{API_SERVER_URL} uses port {DEV_STACK_PORT}, the port of the "
            "normal dev stack. Run a disposable stack on another port, or set "
            f"{ALLOW_DEV_STACK_PORT_ENV}=true if this stack is disposable."
        )

    requested_url = os.environ.get(API_SERVER_URL_ENV, "").strip().rstrip("/")
    if requested_url and requested_url != API_SERVER_URL:
        pytest.fail(
            f"{API_SERVER_URL_ENV}={requested_url} but the Managers target "
            f"{API_SERVER_URL}. Set API_SERVER_PROTOCOL, API_SERVER_HOST and "
            "API_SERVER_PORT instead."
        )

    try:
        response = httpx.get(f"{API_SERVER_URL}/health", timeout=10)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ValueError(f"unexpected health response: {payload!r}")
    except (httpx.HTTPError, ValueError) as e:
        pytest.fail(
            f"No Onyx api_server answered the health check at {API_SERVER_URL} "
            f"({e!r}). Start the target stack first, or point API_SERVER_HOST / "
            "API_SERVER_PORT at it."
        )

    previous = http_client._test_client
    live_client = httpx.Client(
        transport=http_client.RetryingTransport(), timeout=HTTP_TIMEOUT
    )
    http_client.set_test_client(live_client)
    try:
        yield
    finally:
        http_client.set_test_client(previous)
        live_client.close()


@pytest.fixture(scope="module")
def e2e_admin() -> DATestUser:
    """Log in as an existing admin. Never create users or reset the database."""
    email = os.environ.get(ADMIN_EMAIL_ENV, "").strip()
    password = os.environ.get(ADMIN_PASSWORD_ENV, "")
    if not email or not password:
        pytest.fail(
            f"Set {ADMIN_EMAIL_ENV} and {ADMIN_PASSWORD_ENV} to an existing "
            "admin of the target stack. The suite has no default admin."
        )
    try:
        # is_admin / is_active are placeholders; login_as_user sets them from /me.
        admin = UserManager.login_as_user(
            DATestUser(
                id="",
                email=email,
                password=password,
                headers=dict(GENERAL_HEADERS),
                is_admin=False,
                is_active=True,
            )
        )
    except Exception as e:
        pytest.fail(
            f"Could not log in as {email} at {API_SERVER_URL}: {e!r}. Set "
            f"{ADMIN_EMAIL_ENV} / {ADMIN_PASSWORD_ENV} to an existing admin."
        )
    if not admin.is_admin:
        pytest.fail(f"{email} is not an admin on {API_SERVER_URL}.")
    return admin


@pytest.fixture(scope="module")
def e2e_marker() -> str:
    """Unique per run, so seeded document ids never collide with earlier runs."""
    return uuid4().hex[:10]


@pytest.fixture(scope="module")
def e2e_api_key(e2e_admin: DATestUser) -> Generator[DATestAPIKey, None, None]:
    api_key = APIKeyManager.create(user_performing_action=e2e_admin)
    try:
        yield api_key
    finally:
        try:
            APIKeyManager.delete(api_key=api_key, user_performing_action=e2e_admin)
        except Exception as e:
            print(f"Could not delete the e2e API key {api_key.api_key_id}: {e!r}")


@pytest.fixture(scope="module")
def e2e_cc_pair(
    e2e_admin: DATestUser, e2e_marker: str
) -> Generator[DATestCCPair, None, None]:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=e2e_admin,
        name=f"embedding-e2e-{e2e_marker}",
    )
    try:
        yield cc_pair
    finally:
        # Starts a deletion attempt; the background deletion task removes the
        # seeded documents from the index.
        try:
            CCPairManager.delete(cc_pair, user_performing_action=e2e_admin)
        except Exception as e:
            print(f"Could not delete the e2e cc_pair {cc_pair.id}: {e!r}")
