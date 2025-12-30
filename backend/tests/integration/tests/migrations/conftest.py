"""
pytest-alembic configuration for testing Alembic migrations.

This module provides fixtures required by pytest-alembic to test the main
schema migrations (alembic). For alembic_tenants, see test_alembic_tenants.py.

Usage:
    Run all built-in pytest-alembic tests:
        pytest tests/integration/tests/migrations/test_alembic_main.py -v

See: https://pytest-alembic.readthedocs.io/en/latest/
"""

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.engine import Engine

from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PASSWORD
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.sql_engine import SYNC_DB_API
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _create_sync_engine() -> Engine:
    """Create a synchronous SQLAlchemy engine for pytest-alembic."""
    conn_str = build_connection_string(
        db="postgres",
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        db_api=SYNC_DB_API,
    )
    return create_engine(conn_str)


@pytest.fixture
def alembic_config() -> dict[str, Any]:
    """
    Configure pytest-alembic for the main schema migrations.

    Returns pytest-alembic configuration options.
    See: https://pytest-alembic.readthedocs.io/en/latest/setup.html
    """
    return {
        "file": "alembic.ini",
        "script_location": "alembic",
        # Pass additional attributes to the alembic config
        # These will be available in env.py via context.config.attributes
        "attributes": {
            "schema_name": POSTGRES_DEFAULT_SCHEMA,
        },
    }


@pytest.fixture
def alembic_engine() -> Generator[Engine, None, None]:
    """
    Provide a synchronous SQLAlchemy engine for pytest-alembic.

    pytest-alembic requires a synchronous engine to run migrations.
    The engine is configured to connect to the test database.

    Note: pytest-alembic will internally perform commits, so ensure
    the database is in an appropriate state before running tests.
    """
    engine = _create_sync_engine()

    # Ensure the default schema exists
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{POSTGRES_DEFAULT_SCHEMA}"'))
        conn.commit()

    yield engine

    engine.dispose()
