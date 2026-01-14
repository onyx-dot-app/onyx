import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.constants import POSTGRES_WEB_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine
from onyx.main import fetch_versioned_implementation
from onyx.utils.logger import setup_logger

logger = setup_logger()

load_dotenv()


@asynccontextmanager
async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Minimal lifespan for tests that only initializes the database engine.

    This avoids the heavy setup (Vespa, etc.) that the full lifespan does.
    """
    SqlEngine.set_app_name(POSTGRES_WEB_APP_NAME)
    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )

    yield

    SqlEngine.reset_engine()


@pytest.fixture(scope="function")
def client() -> TestClient:
    # Set environment variables
    os.environ["ENABLE_PAID_ENTERPRISE_EDITION_FEATURES"] = "True"

    # Initialize TestClient with the FastAPI app using a minimal test lifespan
    # that only initializes the database (skips Vespa setup, etc.)
    app: FastAPI = fetch_versioned_implementation(
        module="onyx.main", attribute="get_application"
    )(lifespan_override=test_lifespan)
    # Use TestClient as a context manager to properly trigger lifespan
    with TestClient(app) as client:
        yield client
