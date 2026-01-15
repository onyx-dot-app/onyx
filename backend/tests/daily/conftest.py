import os
from collections.abc import AsyncGenerator
from collections.abc import Generator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.db.engine.sql_engine import get_session
from onyx.main import fetch_versioned_implementation
from onyx.utils.logger import setup_logger

logger = setup_logger()

load_dotenv()


@asynccontextmanager
async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """No-op lifespan for tests that don't need database or other services."""
    yield


def mock_get_session() -> Generator[MagicMock, None, None]:
    """Mock database session for tests that don't actually need DB access."""
    yield MagicMock()


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, None, None]:
    # Set environment variables
    os.environ["ENABLE_PAID_ENTERPRISE_EDITION_FEATURES"] = "True"

    # Initialize TestClient with the FastAPI app using a no-op test lifespan
    app: FastAPI = fetch_versioned_implementation(
        module="onyx.main", attribute="get_application"
    )(lifespan_override=test_lifespan)

    # Override the database session dependency with a mock
    # (these tests don't actually need DB access)
    app.dependency_overrides[get_session] = mock_get_session

    # Use TestClient as a context manager to properly trigger lifespan
    with TestClient(app) as client:
        yield client

    # Clean up dependency overrides
    app.dependency_overrides.clear()
