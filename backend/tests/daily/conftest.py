import os
from collections.abc import Generator
from typing import Any

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.main import fetch_versioned_implementation
from onyx.utils.logger import setup_logger

logger = setup_logger()

load_dotenv()


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, Any, None]:
    # Set environment variables
    os.environ["ENABLE_PAID_ENTERPRISE_EDITION_FEATURES"] = "True"

    # Initialize TestClient with the FastAPI app
    app: FastAPI = fetch_versioned_implementation(
        module="onyx.main", attribute="get_application"
    )()
    # Use TestClient as a context manager to properly trigger lifespan
    # (which initializes SqlEngine)
    with TestClient(app) as client:
        yield client
