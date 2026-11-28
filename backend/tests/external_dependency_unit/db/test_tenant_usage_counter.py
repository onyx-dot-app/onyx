"""Usage reads and adds against a real Postgres: which tenant_usage_counter
periods share a row, exact sums, adds from many sessions at once, and the
per-user count of images the chat image tool saved."""

import base64
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from onyx.db.chat import create_chat_session__no_commit
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import WindowAnchor
from onyx.db.models import ChatSession, TenantUsageCounter, User
from onyx.db.usage import (
    UsageLimitExceededError,
    UsagePeriod,
    UsageType,
    check_usage_limit,
    count_generated_images,
    get_usage,
    increment_usage,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.utils import save_chat_output_file, save_files
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


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
            # Every add in this file uses exactly this start.
            delete(TenantUsageCounter).where(TenantUsageCounter.window_start == start)
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


def test_a_period_that_never_ends_differs_from_every_real_end(
    db_session: Session,
) -> None:
    """A never-ending period and a period that ends at the epoch, both from the
    same start, keep their own rows."""
    start = datetime(1969, 12, 31, tzinfo=timezone.utc)
    never_ends = UsagePeriod(anchor=WindowAnchor.CALENDAR, start=start)
    ends_at_epoch = UsagePeriod(
        anchor=WindowAnchor.CALENDAR, start=start, end=start + timedelta(days=1)
    )
    try:
        increment_usage(db_session, UsageType.CHUNKS_INDEXED, 1, never_ends)
        increment_usage(db_session, UsageType.CHUNKS_INDEXED, 2, ends_at_epoch)
        db_session.commit()

        assert get_usage(db_session, UsageType.CHUNKS_INDEXED, never_ends) == 1
        assert get_usage(db_session, UsageType.CHUNKS_INDEXED, ends_at_epoch) == 2
    finally:
        db_session.rollback()
        db_session.execute(
            delete(TenantUsageCounter).where(TenantUsageCounter.window_start == start)
        )
        db_session.commit()


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


# The PNG signature is enough for the saved file's type.
_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()


@pytest.fixture
def users(
    db_session: Session,
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[tuple[User, User, list[str]], None, None]:
    """Two users and the IDs of the files a test saves for them."""
    owner = create_test_user(db_session, "image-owner", assign_default_group=False)
    other = create_test_user(db_session, "image-other", assign_default_group=False)
    file_ids: list[str] = []
    yield owner, other, file_ids
    db_session.rollback()
    for file_id in file_ids:
        get_default_file_store().delete_file(file_id, error_on_missing=False)
    for user in (owner, other):
        for session in db_session.query(ChatSession).filter_by(user_id=user.id):
            db_session.delete(session)
    db_session.commit()
    delete_test_user(db_session, owner, other)


def _save_images(file_ids: list[str], session: ChatSession, count: int) -> None:
    """Save images the way the image tool does after generating them."""
    file_ids.extend(
        save_files(urls=[], base64_files=[_PNG] * count, chat_session_id=session.id)
    )


def test_counts_the_images_saved_in_the_users_own_sessions(
    db_session: Session, users: tuple[User, User, list[str]]
) -> None:
    owner, other, file_ids = users
    first = create_chat_session__no_commit(db_session, None, owner.id, None)
    second = create_chat_session__no_commit(db_session, None, owner.id, None)
    others = create_chat_session__no_commit(db_session, None, other.id, None)
    db_session.commit()
    _save_images(file_ids, first, 2)
    _save_images(file_ids, second, 1)
    _save_images(file_ids, others, 1)
    # A code interpreter output shares the origin but is not a generated image.
    file_ids.append(
        save_chat_output_file(
            b"x,y",
            display_name="chart.csv",
            file_type="text/csv",
            chat_session_id=second.id,
        )
    )

    assert count_generated_images(db_session, owner.id) == 3
    assert count_generated_images(db_session, other.id) == 1


def test_a_chat_marked_deleted_still_counts(
    db_session: Session, users: tuple[User, User, list[str]]
) -> None:
    owner, _, file_ids = users
    session = create_chat_session__no_commit(db_session, None, owner.id, None)
    db_session.commit()
    _save_images(file_ids, session, 2)
    session.deleted = True
    db_session.commit()

    assert count_generated_images(db_session, owner.id) == 2


def test_a_user_without_images_counts_zero(
    db_session: Session, users: tuple[User, User, list[str]]
) -> None:
    owner, _, _ = users
    assert count_generated_images(db_session, owner.id) == 0
