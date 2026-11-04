"""Group token-limit inserts preserve either supported budget."""

from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ee.onyx.db.token_limit import insert_user_group_token_rate_limit
from onyx.configs.constants import TokenRateLimitPeriod
from onyx.db.models import TokenRateLimit
from onyx.server.token_rate_limits.models import TokenRateLimitArgs


@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE user_group (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql(
            "CREATE TABLE model_configuration (id INTEGER PRIMARY KEY)"
        )
    cast(Table, TokenRateLimit.__table__).create(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_group_insert_persists_cost_budget(db_session: Session) -> None:
    limit = insert_user_group_token_rate_limit(
        db_session,
        TokenRateLimitArgs(
            enabled=True,
            token_budget=None,
            period=TokenRateLimitPeriod.WEEKLY,
            cost_budget_cents=3000.0,
        ),
        group_id=1,
    )
    assert limit.cost_budget_cents == pytest.approx(3000.0)
    assert limit.token_budget is None


def test_group_insert_persists_token_budget(db_session: Session) -> None:
    limit = insert_user_group_token_rate_limit(
        db_session,
        TokenRateLimitArgs(
            enabled=True, token_budget=500, period=TokenRateLimitPeriod.DAILY
        ),
        group_id=1,
    )
    assert limit.token_budget == 500
    assert limit.cost_budget_cents is None
