"""Admin resets clear one user's active enforcement window."""

import datetime
import uuid
from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit, UserUsage
from onyx.db.user_usage import (
    USER_USAGE_BUCKET_SECONDS,
    get_usage_reset_window_start,
    get_user_cost_cents_since,
    reset_user_usage,
)
from onyx.utils.datetime import get_window_start


@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_e: object, _c: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_e: object, _c: object, **_kw: object) -> str:
    return "JSON"


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine: Engine = create_engine("sqlite://")
    cast(Table, UserUsage.__table__).create(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _record(db: Session, user_id: str, cost: float, window: datetime.datetime) -> None:
    db.add(
        UserUsage(
            user_id=user_id,
            window_start=window,
            model="m",
            flow="CHAT",
            provider="",
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cost_cents=cost,
        )
    )
    db.flush()


class TestResetUserUsage:
    def test_clears_active_window_keeps_older_history(self, db: Session) -> None:
        uid = str(uuid.uuid4())
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        current = get_window_start(now, USER_USAGE_BUCKET_SECONDS)
        prior = current - datetime.timedelta(days=1)
        historical = current - datetime.timedelta(days=14)
        _record(db, uid, 500.0, current)
        _record(db, uid, 400.0, prior)
        _record(db, uid, 999.0, historical)

        removed = reset_user_usage(db, uid, prior)

        assert removed == 2
        assert get_user_cost_cents_since(db, uid, prior) == 0.0
        assert get_user_cost_cents_since(db, uid, historical) == 999.0

    def test_reset_window_covers_longest_applicable_limit(self) -> None:
        now = datetime.datetime(2026, 7, 28, 12, tzinfo=datetime.timezone.utc)
        current = get_window_start(now, USER_USAGE_BUCKET_SECONDS)
        rate_limits = [
            TokenRateLimit(
                enabled=True,
                token_budget=100,
                cost_budget_cents=None,
                period_hours=48,
                scope=TokenRateLimitScope.USER,
            ),
            TokenRateLimit(
                enabled=True,
                token_budget=None,
                cost_budget_cents=100.0,
                period_hours=168,
                scope=TokenRateLimitScope.GLOBAL,
            ),
        ]

        assert get_usage_reset_window_start(now, rate_limits) == (
            current - datetime.timedelta(days=1)
        )

    def test_only_targets_the_given_user(self, db: Session) -> None:
        me, other = str(uuid.uuid4()), str(uuid.uuid4())
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        current = get_window_start(now, USER_USAGE_BUCKET_SECONDS)
        _record(db, me, 500.0, current)
        _record(db, other, 500.0, current)

        reset_user_usage(db, me, current)

        assert get_user_cost_cents_since(db, me, current) == 0.0
        assert get_user_cost_cents_since(db, other, current) == 500.0

    def test_reset_with_no_rows_is_a_noop(self, db: Session) -> None:
        current = get_window_start(
            datetime.datetime.now(tz=datetime.timezone.utc),
            USER_USAGE_BUCKET_SECONDS,
        )
        assert reset_user_usage(db, str(uuid.uuid4()), current) == 0

    def test_does_not_commit_the_callers_transaction(self, db: Session) -> None:
        uid = str(uuid.uuid4())
        current = get_window_start(
            datetime.datetime.now(tz=datetime.timezone.utc),
            USER_USAGE_BUCKET_SECONDS,
        )
        _record(db, uid, 500.0, current)
        db.commit()

        reset_user_usage(db, uid, current)
        db.rollback()

        assert get_user_cost_cents_since(db, uid, current) == 500.0
