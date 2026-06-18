import os

# Daily tests run without a live backend; EE code paths that depend on
# Redis/Vespa/etc are not available, so disable enforcement before any
# module-level imports below pull in EE versioned implementations.
os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "false"

from collections.abc import AsyncGenerator  # noqa: E402
from collections.abc import Generator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from onyx.auth.users import current_user  # noqa: E402
from onyx.db.engine.sql_engine import get_session  # noqa: E402
from onyx.db.enums import Permission  # noqa: E402
from onyx.db.models import UserRole  # noqa: E402
from onyx.main import get_application  # noqa: E402
from onyx.utils.logger import setup_logger  # noqa: E402

# Opt into the shared @pytest.mark.secrets / test_secrets infrastructure.
from tests.utils.pytest_secrets import (  # noqa: E402
    pytest_collection_modifyitems as pytest_collection_modifyitems,
)
from tests.utils.pytest_secrets import (
    pytest_configure as pytest_configure,  # noqa: E402
)
from tests.utils.pytest_secrets import test_secrets as test_secrets  # noqa: E402

logger = setup_logger()

load_dotenv()


@asynccontextmanager
async def test_lifespan(
    app: FastAPI,  # noqa: ARG001
) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """No-op lifespan for tests that don't need database or other services."""
    yield


def mock_get_session() -> Generator[MagicMock, None, None]:
    """Mock database session for tests that don't actually need DB access."""
    yield MagicMock()


def mock_current_user() -> MagicMock:
    """Mock admin user for endpoints protected by require_permission."""
    mock_admin = MagicMock()
    mock_admin.role = UserRole.ADMIN
    mock_admin.effective_permissions = [Permission.FULL_ADMIN_PANEL_ACCESS.value]
    return mock_admin


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, None, None]:
    # Initialize TestClient with the FastAPI app using a no-op test lifespan.
    # Patch out prometheus metrics setup to avoid "Duplicated timeseries in
    # CollectorRegistry" errors when multiple tests each create a new app
    # (prometheus registers metrics globally and rejects duplicate names).
    with patch("onyx.main.setup_prometheus_metrics"):
        app: FastAPI = get_application(lifespan_override=test_lifespan)

    # Override the database session dependency with a mock
    # (these tests don't actually need DB access)
    app.dependency_overrides[get_session] = mock_get_session
    app.dependency_overrides[current_user] = mock_current_user

    # Use TestClient as a context manager to properly trigger lifespan
    with TestClient(app) as client:
        yield client

    # Clean up dependency overrides
    app.dependency_overrides.clear()
