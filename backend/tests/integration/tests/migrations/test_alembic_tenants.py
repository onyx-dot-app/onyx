"""
pytest-alembic tests for the tenants/public schema migrations.

These tests use pytest-alembic to verify that alembic_tenants migrations
are correct. The alembic_tenants configuration handles migrations for
the public schema tables that are shared across tenants.

Usage:
    pytest tests/integration/tests/migrations/test_alembic_tenants.py -v

See: https://github.com/schireson/pytest-alembic
"""

from collections.abc import Generator
from typing import Any

import pytest
from pytest_alembic import create_alembic_fixture  # type: ignore[import-not-found,unused-ignore]
from pytest_alembic.tests import test_single_head_revision  # type: ignore[import-not-found,unused-ignore]
from pytest_alembic.tests import test_up_down_consistency  # type: ignore[import-not-found,unused-ignore]
from pytest_alembic.tests import test_upgrade  # type: ignore[import-not-found,unused-ignore]
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PASSWORD
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.sql_engine import SYNC_DB_API


@pytest.fixture
def alembic_config() -> dict[str, Any]:
    """Override alembic_config for tenants configuration."""
    return {
        "file": "alembic.ini",
        "config_ini_section": "schema_private",
        "script_location": "alembic_tenants",
    }


@pytest.fixture
def alembic_engine() -> Generator[Engine, None, None]:
    """Override alembic_engine for tenants configuration."""
    conn_str = build_connection_string(
        db="postgres",
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        db_api=SYNC_DB_API,
    )
    engine = create_engine(conn_str)
    yield engine
    engine.dispose()


# Create a custom alembic fixture for the tenants configuration
alembic_runner = create_alembic_fixture()

__all__ = [
    "test_single_head_revision",
    "test_up_down_consistency",
    "test_upgrade",
]
