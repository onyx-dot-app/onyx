"""Unit tests for reset_user_usage (in-memory SQLite over the real ledger).

An admin reset must clear a user's CURRENT window (lifting a budget block) while
preserving prior windows (the reporting history) and other users' rows.
"""

import datetime
import uuid
from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.db.models import UserUsage
from onyx.db.user_usage import get_user_cost_cents_since
from onyx.db.user_usage import get_window_start
from onyx.db.user_usage import record_user_usage
from onyx.db.user_usage import reset_user_usage
from onyx.db.user_usage import USAGE_PERIOD_HOURS


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
    record_user_usage(db, user_id, "m", "CHAT", None, 1, 1, 0, cost, window)


class TestResetUserUsage:
    def test_clears_current_window_keeps_history(self, db: Session) -> None:
        uid = str(uuid.uuid4())
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        current = get_window_start(now, period_hours=USAGE_PERIOD_HOURS)
        prior = current - datetime.timedelta(days=14)
        _record(db, uid, 500.0, current)
        _record(db, uid, 999.0, prior)

        removed = reset_user_usage(db, uid)

        assert removed == 1
        # current-window spend is gone (budget block lifts) ...
        assert get_user_cost_cents_since(db, uid, current) == 0.0
        # ... but the prior window (history) is preserved.
        assert get_user_cost_cents_since(db, uid, prior) == 999.0

    def test_only_targets_the_given_user(self, db: Session) -> None:
        me, other = str(uuid.uuid4()), str(uuid.uuid4())
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        current = get_window_start(now, period_hours=USAGE_PERIOD_HOURS)
        _record(db, me, 500.0, current)
        _record(db, other, 500.0, current)

        reset_user_usage(db, me)

        assert get_user_cost_cents_since(db, me, current) == 0.0
        assert get_user_cost_cents_since(db, other, current) == 500.0  # untouched

    def test_reset_with_no_rows_is_a_noop(self, db: Session) -> None:
        assert reset_user_usage(db, str(uuid.uuid4())) == 0
