import pytest

from onyx.db.engine.sql_engine import SqlEngine


@pytest.fixture(scope="session", autouse=True)
def initialize_db() -> None:
    # Make sure that the db engine is initialized before any tests are run
    SqlEngine.init_engine(
        pool_size=10,
        max_overflow=5,
    )
