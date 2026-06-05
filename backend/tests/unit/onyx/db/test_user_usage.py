"""Unit tests for the per-user usage ledger (in-memory SQLite)."""

import datetime
from collections.abc import Generator
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.db.models import User__UserGroup
from onyx.db.models import UserUsage
from onyx.db.user_usage import get_group_cost_cents_since
from onyx.db.user_usage import get_total_cost_cents_since
from onyx.db.user_usage import get_user_cost_cents_in_window
from onyx.db.user_usage import get_user_cost_cents_since
from onyx.db.user_usage import get_user_usage_by_day_and_model
from onyx.db.user_usage import get_window_start
from onyx.db.user_usage import record_user_usage


# Map the postgres-only column types onto SQLite equivalents so the real
# UserUsage table from models.py can be created against an in-memory DB.
@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine("sqlite://")
    # Only the table under test; FK to user.id is not enforced by SQLite.
    user_usage_table = cast(Table, UserUsage.__table__)
    user_usage_table.create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class TestGetWindowStart:
    def test_weekly_aligns_to_monday(self) -> None:
        # 2026-06-03 is a Wednesday.
        dt = datetime.datetime(2026, 6, 3, 14, 22, tzinfo=datetime.timezone.utc)
        window = get_window_start(dt, period_hours=168)
        assert window.weekday() == 0  # Monday
        assert window == datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

    def test_hourly_epoch_aligned(self) -> None:
        dt = datetime.datetime(2026, 6, 3, 14, 59, 59, tzinfo=datetime.timezone.utc)
        window = get_window_start(dt, period_hours=1)
        assert window == datetime.datetime(
            2026, 6, 3, 14, 0, 0, tzinfo=datetime.timezone.utc
        )

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime.datetime(2026, 6, 3, 14, 30)
        aware = datetime.datetime(2026, 6, 3, 14, 30, tzinfo=datetime.timezone.utc)
        assert get_window_start(naive, 1) == get_window_start(aware, 1)


class TestRecordUserUsage:
    def test_two_records_accumulate(self, db_session: Session) -> None:
        user_id = str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        record_user_usage(
            db_session,
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
        record_user_usage(
            db_session,
            user_id=user_id,
            model="claude-3",
            flow="CHAT",
            provider="anthropic",
            input_tokens=200,
            output_tokens=70,
            cache_read_tokens=5,
            cost_cents=2.0,
            window_start=window,
        )

        rows = db_session.query(UserUsage).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.input_tokens == 300
        assert row.output_tokens == 120
        assert row.cache_read_tokens == 15
        assert row.cost_cents == pytest.approx(3.5)

    def test_distinct_dimensions_separate_rows(self, db_session: Session) -> None:
        user_id = str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        record_user_usage(
            db_session,
            user_id,
            "model-a",
            "CHAT",
            "anthropic",
            10,
            5,
            0,
            0.1,
            window,
        )
        record_user_usage(
            db_session,
            user_id,
            "model-b",
            "CHAT",
            "anthropic",
            20,
            5,
            0,
            0.2,
            window,
        )
        assert db_session.query(UserUsage).count() == 2

    def test_null_provider_accumulates(self, db_session: Session) -> None:
        user_id = str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        record_user_usage(
            db_session, user_id, "model-a", "CHAT", None, 10, 5, 0, 0.1, window
        )
        record_user_usage(
            db_session, user_id, "model-a", "CHAT", None, 30, 5, 0, 0.3, window
        )
        rows = db_session.query(UserUsage).all()
        assert len(rows) == 1
        assert rows[0].input_tokens == 40
        assert rows[0].cost_cents == pytest.approx(0.4)
        # A missing provider is stored as "" (not NULL) so the dedup unique index
        # collapses these rows on every Postgres version.
        assert rows[0].provider == ""


class TestAggregation:
    def test_by_day_and_model(self, db_session: Session) -> None:
        user_id = str(uuid4())
        day1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        day2 = datetime.datetime(2026, 6, 2, tzinfo=datetime.timezone.utc)

        record_user_usage(
            db_session,
            user_id,
            "model-a",
            "CHAT",
            "anthropic",
            100,
            50,
            0,
            1.0,
            day1,
        )
        record_user_usage(
            db_session,
            user_id,
            "model-b",
            "CHAT",
            "anthropic",
            200,
            60,
            0,
            2.0,
            day1,
        )
        record_user_usage(
            db_session,
            user_id,
            "model-a",
            "CHAT",
            "anthropic",
            300,
            70,
            0,
            3.0,
            day2,
        )

        result = get_user_usage_by_day_and_model(
            db_session,
            user_id,
            since=day1,
            until=datetime.datetime(2026, 6, 3, tzinfo=datetime.timezone.utc),
        )
        assert result == [
            {
                "day": "2026-06-01",
                "model": "model-a",
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 0,
                "cost_cents": 1.0,
            },
            {
                "day": "2026-06-01",
                "model": "model-b",
                "input_tokens": 200,
                "output_tokens": 60,
                "cache_read_tokens": 0,
                "cost_cents": 2.0,
            },
            {
                "day": "2026-06-02",
                "model": "model-a",
                "input_tokens": 300,
                "output_tokens": 70,
                "cache_read_tokens": 0,
                "cost_cents": 3.0,
            },
        ]

    def test_aggregation_excludes_other_users(self, db_session: Session) -> None:
        user_id = str(uuid4())
        other_id = str(uuid4())
        day1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        record_user_usage(
            db_session, user_id, "model-a", "CHAT", None, 100, 50, 0, 1.0, day1
        )
        record_user_usage(
            db_session, other_id, "model-a", "CHAT", None, 999, 50, 0, 9.0, day1
        )

        result = get_user_usage_by_day_and_model(
            db_session,
            user_id,
            since=day1,
            until=datetime.datetime(2026, 6, 2, tzinfo=datetime.timezone.utc),
        )
        assert len(result) == 1
        assert result[0]["input_tokens"] == 100


class TestCostInWindow:
    def test_sums_cost_across_dimensions(self, db_session: Session) -> None:
        user_id = str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

        record_user_usage(
            db_session,
            user_id,
            "model-a",
            "CHAT",
            "anthropic",
            10,
            5,
            0,
            1.25,
            window,
        )
        record_user_usage(
            db_session,
            user_id,
            "model-b",
            "BUILD",
            "openai",
            20,
            5,
            0,
            2.75,
            window,
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
    """Range-scan read used by enforcement: sums ledger rows with
    window_start >= cutoff. The cutoff is grid-relaxed by the caller
    (_worst_triggered_cost_limit), so this helper is a plain range scan."""

    def test_includes_rows_at_or_after_cutoff(self, db_session: Session) -> None:
        user_id = str(uuid4())
        w = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        record_user_usage(db_session, user_id, "m", "CHAT", None, 1, 1, 0, 42.0, w)
        assert get_user_cost_cents_since(db_session, user_id, w) == pytest.approx(42.0)

    def test_rows_before_cutoff_excluded(self, db_session: Session) -> None:
        user_id = str(uuid4())
        older = datetime.datetime(2026, 5, 25, tzinfo=datetime.timezone.utc)
        newer = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        record_user_usage(db_session, user_id, "m", "CHAT", None, 1, 1, 0, 5.0, older)
        record_user_usage(db_session, user_id, "m", "CHAT", None, 1, 1, 0, 8.0, newer)
        assert get_user_cost_cents_since(db_session, user_id, newer) == pytest.approx(
            8.0
        )

    def test_excludes_other_users(self, db_session: Session) -> None:
        u1, u2 = str(uuid4()), str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        record_user_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 3.0, window)
        record_user_usage(db_session, u2, "m", "CHAT", None, 1, 1, 0, 9.0, window)
        assert get_user_cost_cents_since(db_session, u1, window) == pytest.approx(3.0)


class TestTotalCostSince:
    def test_sums_across_users(self, db_session: Session) -> None:
        u1, u2 = str(uuid4()), str(uuid4())
        window = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        record_user_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 3.0, window)
        record_user_usage(db_session, u2, "m", "CHAT", None, 1, 1, 0, 4.0, window)

        assert get_total_cost_cents_since(db_session, window) == pytest.approx(7.0)

    def test_older_window_excluded(self, db_session: Session) -> None:
        u1 = str(uuid4())
        w1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        w2 = datetime.datetime(2026, 6, 8, tzinfo=datetime.timezone.utc)
        record_user_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 3.0, w1)
        record_user_usage(db_session, u1, "m", "CHAT", None, 1, 1, 0, 9.0, w2)

        # cutoff at w2 excludes the earlier w1 row
        assert get_total_cost_cents_since(db_session, w2) == pytest.approx(9.0)


@pytest.fixture
def db_session_with_groups() -> Generator[Session, None, None]:
    """UserUsage + User__UserGroup tables, for group-scoped cost aggregation."""
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
        record_user_usage(s, u1, "m", "CHAT", None, 1, 1, 0, 2.0, window)
        record_user_usage(s, u2, "m", "CHAT", None, 1, 1, 0, 5.0, window)
        record_user_usage(s, outsider, "m", "CHAT", None, 1, 1, 0, 99.0, window)

        assert get_group_cost_cents_since(s, 10, window) == pytest.approx(7.0)
