from collections.abc import Generator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema

from onyx.cache import factory as cache_factory
from onyx.configs import app_configs
from onyx.configs.constants import CacheBackendType
from onyx.db.engine.sql_engine import SYNC_DB_API, SqlEngine, build_connection_string
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA,
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
)
from tests.external_dependency_unit.db.shard_test_utils import (
    admin_engine,
    temporary_database,
)

# Override the parent integration conftest's autouse session fixtures.
# Migration tests only need Postgres (provided by the workflow) and the
# pytest-alembic fixtures below — they must NOT pre-migrate the schema
# (would break pytest-alembic's test_upgrade) and must NOT start the
# FastAPI app (its lifespan calls setup_onyx() which requires OpenSearch,
# and the database-tests workflow doesn't start OpenSearch).


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    return None


@pytest.fixture(scope="session", autouse=True)
def _start_celery_workers() -> Generator[None, None, None]:
    yield None


@pytest.fixture(scope="session", autouse=True)
def _test_client() -> Generator[None, None, None]:
    yield None


@pytest.fixture
def alembic_engine(monkeypatch: pytest.MonkeyPatch) -> Generator[Engine, None, None]:
    with contextmanager(temporary_database)("pytest_alembic") as database:
        # These revisions create and drop a Postgres role, which is cluster-wide.
        monkeypatch.setattr(app_configs, "DB_READONLY_USER", database)
        engine = create_engine(build_connection_string(db=database, db_api=SYNC_DB_API))
        monkeypatch.setattr(SqlEngine, "_engine", engine)
        monkeypatch.setattr(cache_factory, "CACHE_BACKEND", CacheBackendType.POSTGRES)
        try:
            if POSTGRES_DEFAULT_SCHEMA != POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE:
                with engine.begin() as connection:
                    connection.execute(
                        CreateSchema(POSTGRES_DEFAULT_SCHEMA, if_not_exists=True)
                    )
            yield engine
        finally:
            engine.dispose()
    admin = admin_engine()
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP ROLE IF EXISTS "{database}"'))
    finally:
        admin.dispose()
