import os

# Set environment variables BEFORE any other imports to ensure they're picked up
# by module-level code that reads env vars at import time
# TODO(Nik): https://linear.app/onyx-app/issue/ENG-1/update-test-infra-to-use-test-license
os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "false"

from collections.abc import AsyncGenerator
from collections.abc import Generator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import UserRole
from onyx.main import get_application
from onyx.utils.logger import setup_logger

# Opt into the shared @pytest.mark.secrets / test_secrets infrastructure.
from tests.utils.pytest_secrets import (
    pytest_collection_modifyitems as pytest_collection_modifyitems,
    pytest_configure as pytest_configure,
    test_secrets as test_secrets,
)

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
