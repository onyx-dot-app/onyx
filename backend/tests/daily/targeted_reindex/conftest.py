"""Daily-suite conftest for targeted-reindex integration tests.

These tests need:
- Real Postgres (cc_pair, IndexAttempt, IndexAttemptError, TargetedReindexJob rows)
- Real OpenSearch (verify documents actually land in the index)
- Real Drive credentials (via the shared `test_secrets` fixture)

The parent `tests/daily/conftest.py` already opts into the
`@pytest.mark.secrets` infrastructure; we add Postgres + tenant context
on top so the targeted-reindex flow can write its rows the same way
production does.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(scope="session", autouse=True)
def _init_sql_engine() -> None:
    """Initialise the connection pool exactly once per test session so we
    don't re-enter `SqlEngine.init_engine` on every test function. The
    init itself is internally guarded (early-return if already set), but
    keeping the call out of the per-function fixture avoids accidental
    pool churn if that guard ever changes."""
    SqlEngine.init_engine(pool_size=10, max_overflow=5)


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Real Postgres session. Mirrors `tests/external_dependency_unit/conftest.py`
    so the same write paths are exercised, just from the daily suite."""
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
