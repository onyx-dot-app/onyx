"""Unit tests for token-rate-limit enforcement (in-memory SQLite).

Guards the admin-facing unit: a stored ``token_budget`` of N must enforce at
exactly N tokens (raw), so the value an admin types is the value enforced.
"""

import datetime
from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.db.models import TokenRateLimit
from onyx.db.models import TokenRateLimitScope
from onyx.server.query_and_chat.token_limit import _is_rate_limited


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine("sqlite://")
    # Only the table under test; user-group FK is not exercised here.
    cast(Table, TokenRateLimit.__table__).create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_limit(token_budget: int) -> TokenRateLimit:
    return TokenRateLimit(
        enabled=True,
        token_budget=token_budget,
        period_hours=1,
        scope=TokenRateLimitScope.GLOBAL,
    )


def _usage(token_count: int) -> list[tuple[datetime.datetime, int]]:
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    return [(now, token_count)]


class TestIsRateLimitedUnit:
    def test_budget_is_raw_tokens(self) -> None:
        # token_budget=12 must enforce at 12 tokens, not 12,000.
        limit = _make_limit(token_budget=12)
        assert _is_rate_limited([limit], _usage(11)) is False
        assert _is_rate_limited([limit], _usage(12)) is True
        assert _is_rate_limited([limit], _usage(13)) is True

    def test_below_budget_not_limited(self) -> None:
        limit = _make_limit(token_budget=1000)
        assert _is_rate_limited([limit], _usage(999)) is False

    def test_at_budget_is_limited(self) -> None:
        limit = _make_limit(token_budget=1000)
        assert _is_rate_limited([limit], _usage(1000)) is True
