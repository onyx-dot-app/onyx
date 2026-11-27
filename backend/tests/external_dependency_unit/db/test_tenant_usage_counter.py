"""Reads and adds on tenant_usage_counter against a real Postgres: which
periods share a row, exact sums, and adds from many sessions at once."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import WindowAnchor
from onyx.db.models import TenantUsageCounter
from onyx.db.usage import (
    UsageLimitExceededError,
    UsagePeriod,
    UsageType,
    check_usage_limit,
    get_usage,
    increment_usage,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


@pytest.fixture
def start() -> Generator[datetime, None, None]:
    """A period start no other test or real usage uses, removed afterwards."""
    start = datetime(2001, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=uuid4().int % 10**8
    )
    yield start
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        session.execute(
            delete(TenantUsageCounter).where(
                TenantUsageCounter.window_start.between(
                    start - timedelta(days=1), start + timedelta(days=30)
                )
            )
        )
        session.commit()


def _week(start: datetime) -> UsagePeriod:
    return UsagePeriod(
        anchor=WindowAnchor.CALENDAR, start=start, end=start + timedelta(days=7)
    )


def _rows(db_session: Session, start: datetime) -> int:
    return db_session.execute(
        select(func.count())
        .select_from(TenantUsageCounter)
        .where(TenantUsageCounter.window_start == start)
    ).scalar_one()


def test_adds_up_in_one_row_per_usage_type_and_period(
    db_session: Session, start: datetime
) -> None:
    week = _week(start)
    increment_usage(db_session, UsageType.LLM_COST, 10.5, week)
    increment_usage(db_session, UsageType.LLM_COST, 4, week)
    increment_usage(db_session, UsageType.CHUNKS_INDEXED, 300, week)
    db_session.commit()

    assert get_usage(db_session, UsageType.LLM_COST, week) == 14.5
    assert get_usage(db_session, UsageType.CHUNKS_INDEXED, week) == 300
    assert get_usage(db_session, UsageType.API_CALLS, week) == 0
    assert _rows(db_session, start) == 2


def test_periods_with_the_same_start_stay_apart(
    db_session: Session, start: datetime
) -> None:
    week = _week(start)
    never_ends = UsagePeriod(anchor=WindowAnchor.CALENDAR, start=start)
    increment_usage(db_session, UsageType.CHUNKS_INDEXED, 1, week)
    increment_usage(db_session, UsageType.CHUNKS_INDEXED, 2, never_ends)
    db_session.commit()

    assert get_usage(db_session, UsageType.CHUNKS_INDEXED, week) == 1
    assert get_usage(db_session, UsageType.CHUNKS_INDEXED, never_ends) == 2


def test_a_period_that_never_ends_keeps_one_row(
    db_session: Session, start: datetime
) -> None:
    never_ends = UsagePeriod(anchor=WindowAnchor.CALENDAR, start=start)
    for _ in range(3):
        increment_usage(db_session, UsageType.CHUNKS_INDEXED, 5, never_ends)
    db_session.commit()

    assert get_usage(db_session, UsageType.CHUNKS_INDEXED, never_ends) == 15
    assert _rows(db_session, start) == 1


def test_the_same_instant_in_another_timezone_is_the_same_period(
    db_session: Session, start: datetime
) -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    increment_usage(db_session, UsageType.API_CALLS, 1, _week(start))
    increment_usage(db_session, UsageType.API_CALLS, 1, _week(start.astimezone(ist)))
    db_session.commit()

    assert get_usage(db_session, UsageType.API_CALLS, _week(start)) == 2
    assert _rows(db_session, start) == 1


def test_many_small_amounts_sum_exactly(db_session: Session, start: datetime) -> None:
    week = _week(start)
    for _ in range(1000):
        increment_usage(db_session, UsageType.LLM_COST, 0.01, week)
    db_session.commit()

    assert get_usage(db_session, UsageType.LLM_COST, week) == 10.0


def test_check_reads_the_period_it_is_given(
    db_session: Session, start: datetime
) -> None:
    week = _week(start)
    increment_usage(db_session, UsageType.API_CALLS, 10, week)
    db_session.commit()

    check_usage_limit(db_session, UsageType.API_CALLS, 10, period=week)
    with pytest.raises(UsageLimitExceededError):
        check_usage_limit(
            db_session, UsageType.API_CALLS, 10, pending_amount=1, period=week
        )
    # The next week has nothing yet.
    check_usage_limit(
        db_session,
        UsageType.API_CALLS,
        10,
        pending_amount=10,
        period=_week(start + timedelta(days=7)),
    )


def test_concurrent_adds_are_not_lost(db_session: Session, start: datetime) -> None:
    week = _week(start)
    writers, adds_each = 8, 25

    def add_many() -> None:
        for _ in range(adds_each):
            with get_session_with_tenant(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            ) as session:
                increment_usage(session, UsageType.API_CALLS, 1, week)
                session.commit()

    with ThreadPoolExecutor(max_workers=writers) as pool:
        for future in [pool.submit(add_many) for _ in range(writers)]:
            future.result()

    assert get_usage(db_session, UsageType.API_CALLS, week) == writers * adds_each
    assert _rows(db_session, start) == 1
