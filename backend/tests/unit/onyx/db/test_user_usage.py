"""Unit tests for the per-user usage ledger.

`record_user_usage` is Postgres-only (pg_insert upsert); its unit tests mock the
session like tenant usage. Read-path helpers still run against in-memory SQLite
seeded with ORM inserts."""

import datetime
import sqlite3
from collections.abc import Generator
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import Table, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from onyx.db.models import User__UserGroup, UserUsage
from onyx.db.user_usage import (
    UserUsageByDay,
    get_group_cost_cents_since,
    get_total_cost_cents_buckets_since,
    get_total_cost_cents_since,
    get_user_cost_cents_buckets_since,
    get_user_cost_cents_in_window,
    get_user_cost_cents_since,
    get_user_usage_by_day_and_model,
    record_user_usage,
)


@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


def _seed_usage(
    db_session: Session,
    user_id: str,
    model: str,
    flow: str,
    provider: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cost_cents: float,
    window_start: datetime.datetime,
) -> None:
    """Insert a ledger row without going through the Postgres upsert path."""
    db_session.add(
        UserUsage(
            user_id=user_id,
            window_start=window_start,
            model=model,
            flow=flow,
            provider=provider or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cost_cents=cost_cents,
        )
    )
    db_session.flush()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _register_timezone(dbapi_connection: object, _: object) -> None:
        cast(sqlite3.Connection, dbapi_connection).create_function(
            "timezone", 2, lambda _tz, value: value
        )

    cast(Table, UserUsage.__table__).create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class TestRecordUserUsage:
    """Postgres upsert path — mock the session; do not execute SQL."""

    def test_executes_upsert_and_flushes(self) -> None:
        mock_session = MagicMock()
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        user_id = str(uuid4())

        record_user_usage(
            mock_session,
            user_id=user_id,
            model="claude-3",
            flow="CHAT",
            provider="anthropic",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=10,
            cost_cents=1.5,
            window_start=window,
        )

        mock_session.execute.assert_called_once()
        mock_session.flush.assert_called_once()

    def test_null_provider_stored_as_empty_string(self) -> None:
        from sqlalchemy.dialects import postgresql

        mock_session = MagicMock()
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        record_user_usage(
            mock_session,
            user_id=str(uuid4()),
            model="model-a",
            flow="CHAT",
            provider=None,
            input_tokens=10,
            output_tokens=5,
            cache_read_tokens=0,
            cost_cents=0.1,
            window_start=window,
        )

        stmt = mock_session.execute.call_args[0][0]
        compiled = stmt.compile(dialect=postgresql.dialect())
        assert compiled.params["provider"] == ""


class TestAggregation:
    def test_by_day_and_model(self, db_session: Session) -> None:
        user_id = str(uuid4())
        day1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        day2 = datetime.datetime(2026, 6, 2, tzinfo=datetime.timezone.utc)

        _seed_usage(
            db_session, user_id, "model-a", "CHAT", "anthropic", 100, 50, 0, 1.0, day1
        )
        _seed_usage(
            db_session,
            user_id,
            "model-a",
            "CHAT",
            "anthropic",
            25,
            10,
            0,
            0.5,
            day1 + datetime.timedelta(hours=1),
        )
        _seed_usage(
            db_session, user_id, "model-b", "CHAT", "anthropic", 200, 60, 0, 2.0, day1
        )
        _seed_usage(
            db_session, user_id, "model-a", "CHAT", "anthropic", 300, 70, 0, 3.0, day2
        )

        result = get_user_usage_by_day_and_model(
            db_session,
            user_id,
            since=day1,
            until=datetime.datetime(2026, 6, 3, tzinfo=datetime.timezone.utc),
        )
        assert result == [
            UserUsageByDay(
                day="2026-06-01",
                model="model-a",
                input_tokens=125,
                output_tokens=60,
                cache_read_tokens=0,
                cost_cents=1.5,
            ),
            UserUsageByDay(
                day="2026-06-01",
                model="model-b",
                input_tokens=200,
                output_tokens=60,
                cache_read_tokens=0,
                cost_cents=2.0,
            ),
            UserUsageByDay(
                day="2026-06-02",
                model="model-a",
                input_tokens=300,
                output_tokens=70,
                cache_read_tokens=0,
                cost_cents=3.0,
            ),
        ]

    def test_aggregation_excludes_other_users(self, db_session: Session) -> None:
        user_id = str(uuid4())
        other_id = str(uuid4())
        day1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        _seed_usage(db_session, user_id, "model-a", "CHAT", None, 100, 50, 0, 1.0, day1)
        _seed_usage(
            db_session, other_id, "model-a", "CHAT", None, 999, 50, 0, 9.0, day1
        )

        result = get_user_usage_by_day_and_model(
            db_session,
            user_id,
            since=day1,
            until=datetime.datetime(2026, 6, 2, tzinfo=datetime.timezone.utc),
        )
        assert len(result) == 1
        assert result[0].input_tokens == 100


class TestCostInWindow:
    def test_sums_cost_across_dimensions(self, db_session: Session) -> None:
        user_id = str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        _seed_usage(
            db_session, user_id, "model-a", "CHAT", "anthropic", 10, 5, 0, 1.25, window
        )
        _seed_usage(
            db_session, user_id, "model-b", "BUILD", "openai", 20, 5, 0, 2.75, window
        )

        total = get_user_cost_cents_in_window(db_session, user_id, window)
        assert total == pytest.approx(4.0)

    def test_empty_window_is_zero(self, db_session: Session) -> None:
        total = get_user_cost_cents_in_window(
            db_session,
            str(uuid4()),
            datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
        )
        assert total == 0.0


class TestUserCostSince:
    def test_includes_rows_at_or_after_cutoff(self, db_session: Session) -> None:
        user_id = str(uuid4())
        w = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        _seed_usage(db_session, user_id, "m", "CHAT", None, 1, 1, 0, 42.0, w)
        assert get_user_cost_cents_since(db_session, user_id, w) == pytest.approx(42.0)

    def test_rows_before_cutoff_excluded(self, db_session: Session) -> None:
        user_id = str(uuid4())
        older = datetime.datetime(2026, 5, 25, tzinfo=datetime.timezone.utc)
        newer = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        _seed_usage(db_session, user_id, "m", "CHAT", None, 1, 1, 0, 5.0, older)
        _seed_usage(db_session, user_id, "m", "CHAT", None, 1, 1, 0, 8.0, newer)
        assert get_user_cost_cents_since(db_session, user_id, newer) == pytest.approx(
            8.0
        )

    def test_excludes_other_users(self, db_session: Session) -> None:
        u1, u2 = str(uuid4()), str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        _seed_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 3.0, window)
        _seed_usage(db_session, u2, "m", "CHAT", None, 1, 1, 0, 9.0, window)
        assert get_user_cost_cents_since(db_session, u1, window) == pytest.approx(3.0)


class TestTotalCostSince:
    def test_sums_across_users(self, db_session: Session) -> None:
        u1, u2 = str(uuid4()), str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        _seed_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 3.0, window)
        _seed_usage(db_session, u2, "m", "CHAT", None, 1, 1, 0, 4.0, window)

        assert get_total_cost_cents_since(db_session, window) == pytest.approx(7.0)

    def test_older_window_excluded(self, db_session: Session) -> None:
        u1 = str(uuid4())
        w1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        w2 = datetime.datetime(2026, 6, 8, tzinfo=datetime.timezone.utc)
        _seed_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 3.0, w1)
        _seed_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 9.0, w2)

        assert get_total_cost_cents_since(db_session, w2) == pytest.approx(9.0)


class TestUserCostBucketsSince:
    def test_returns_per_window_totals(self, db_session: Session) -> None:
        user_id = str(uuid4())
        other = str(uuid4())
        w1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        w2 = datetime.datetime(2026, 6, 8, tzinfo=datetime.timezone.utc)
        _seed_usage(db_session, user_id, "m", "CHAT", None, 1, 1, 0, 3.0, w1)
        _seed_usage(db_session, user_id, "n", "CHAT", None, 1, 1, 0, 5.0, w1)
        _seed_usage(db_session, user_id, "m", "CHAT", None, 1, 1, 0, 9.0, w2)
        _seed_usage(db_session, other, "m", "CHAT", None, 1, 1, 0, 99.0, w1)

        buckets = dict(get_user_cost_cents_buckets_since(db_session, user_id, w1))
        assert buckets[w1] == pytest.approx(8.0)
        assert buckets[w2] == pytest.approx(9.0)
        assert sum(c for ws, c in buckets.items() if ws >= w2) == pytest.approx(9.0)


class TestTotalCostBucketsSince:
    def test_sums_across_users_per_window(self, db_session: Session) -> None:
        u1, u2 = str(uuid4()), str(uuid4())
        w1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        w2 = datetime.datetime(2026, 6, 8, tzinfo=datetime.timezone.utc)
        _seed_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 3.0, w1)
        _seed_usage(db_session, u2, "m", "CHAT", None, 1, 1, 0, 4.0, w1)
        _seed_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 9.0, w2)

        buckets = dict(get_total_cost_cents_buckets_since(db_session, w1))
        assert buckets[w1] == pytest.approx(7.0)
        assert buckets[w2] == pytest.approx(9.0)


@pytest.fixture
def db_session_with_groups() -> Generator[Session, None, None]:
    engine: Engine = create_engine("sqlite://")
    cast(Table, UserUsage.__table__).create(bind=engine)
    cast(Table, User__UserGroup.__table__).create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class TestGroupCostSince:
    def test_sums_members_of_group(self, db_session_with_groups: Session) -> None:
        s = db_session_with_groups
        u1, u2, outsider = str(uuid4()), str(uuid4()), str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        s.add_all(
            [
                User__UserGroup(user_group_id=10, user_id=u1),
                User__UserGroup(user_group_id=10, user_id=u2),
            ]
        )
        s.flush()
        _seed_usage(s, u1, "m", "CHAT", None, 1, 1, 0, 2.0, window)
        _seed_usage(s, u2, "m", "CHAT", None, 1, 1, 0, 5.0, window)
        _seed_usage(s, outsider, "m", "CHAT", None, 1, 1, 0, 99.0, window)

        assert get_group_cost_cents_since(s, 10, window) == pytest.approx(7.0)
