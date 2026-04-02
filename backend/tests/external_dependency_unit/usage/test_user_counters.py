from datetime import datetime
from datetime import timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.usage import acknowledge_user_counters
from onyx.db.usage import get_user_counters
from onyx.db.usage import increment_user_counter
from onyx.db.usage import set_user_counter
from onyx.db.usage import track_user_activity
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture()
def test_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> User:
    return create_test_user(db_session, "counter_test")


class TestIncrementUserCounter:
    def test_creates_new_counter(self, db_session: Session, test_user: User) -> None:
        increment_user_counter(db_session, test_user.id, "msg", 1000)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        assert len(rows) == 1
        assert rows[0].counter_key == "msg"
        assert rows[0].current_value == 1
        assert rows[0].target_value == 1000
        assert rows[0].completed_at is None

    def test_increments_existing_counter(
        self, db_session: Session, test_user: User
    ) -> None:
        increment_user_counter(db_session, test_user.id, "msg", 1000)
        increment_user_counter(db_session, test_user.id, "msg", 1000)
        increment_user_counter(db_session, test_user.id, "msg", 1000)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        msg_row = next(r for r in rows if r.counter_key == "msg")
        assert msg_row.current_value == 3

    def test_sets_completed_at_on_threshold(
        self, db_session: Session, test_user: User
    ) -> None:
        for _ in range(5):
            increment_user_counter(db_session, test_user.id, "ca", 5)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        ca_row = next(r for r in rows if r.counter_key == "ca")
        assert ca_row.current_value == 5
        assert ca_row.completed_at is not None

    def test_does_not_reset_completed_at_after_threshold(
        self, db_session: Session, test_user: User
    ) -> None:
        for _ in range(6):
            increment_user_counter(db_session, test_user.id, "ca", 5)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        ca_row = next(r for r in rows if r.counter_key == "ca")
        assert ca_row.current_value == 6
        assert ca_row.completed_at is not None


class TestSetUserCounter:
    def test_sets_value_directly(self, db_session: Session, test_user: User) -> None:
        set_user_counter(db_session, test_user.id, "pa", 10, 7)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        pa_row = next(r for r in rows if r.counter_key == "pa")
        assert pa_row.current_value == 7
        assert pa_row.completed_at is None

    def test_completes_when_reaching_target(
        self, db_session: Session, test_user: User
    ) -> None:
        set_user_counter(db_session, test_user.id, "pa", 10, 10)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        pa_row = next(r for r in rows if r.counter_key == "pa")
        assert pa_row.completed_at is not None


class TestAcknowledgeUserCounters:
    def test_acknowledges_counters(self, db_session: Session, test_user: User) -> None:
        for _ in range(5):
            increment_user_counter(db_session, test_user.id, "ca", 5)
        db_session.commit()

        acknowledge_user_counters(db_session, test_user.id, ["ca"])
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        ca_row = next(r for r in rows if r.counter_key == "ca")
        assert ca_row.acknowledged is True

    def test_does_not_acknowledge_other_users(
        self, db_session: Session, test_user: User
    ) -> None:
        other_user = create_test_user(db_session, "counter_other")

        for _ in range(5):
            increment_user_counter(db_session, test_user.id, "ca", 5)
            increment_user_counter(db_session, other_user.id, "ca", 5)
        db_session.commit()

        acknowledge_user_counters(db_session, test_user.id, ["ca"])
        db_session.commit()

        test_rows = get_user_counters(db_session, test_user.id)
        other_rows = get_user_counters(db_session, other_user.id)

        assert next(r for r in test_rows if r.counter_key == "ca").acknowledged is True
        assert (
            next(r for r in other_rows if r.counter_key == "ca").acknowledged is False
        )


class TestTrackUserActivity:
    def test_increments_message_counter(
        self, db_session: Session, test_user: User
    ) -> None:
        track_user_activity(db_session, test_user.id)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        msg_row = next((r for r in rows if r.counter_key == "msg"), None)
        assert msg_row is not None
        assert msg_row.current_value == 1

    def test_increments_deep_research_counter(
        self, db_session: Session, test_user: User
    ) -> None:
        track_user_activity(db_session, test_user.id, deep_research=True)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        dr_row = next((r for r in rows if r.counter_key == "dr"), None)
        assert dr_row is not None
        assert dr_row.current_value == 1

    def test_increments_web_search_counter(
        self, db_session: Session, test_user: User
    ) -> None:
        track_user_activity(db_session, test_user.id, has_web_search=True)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        ws_row = next((r for r in rows if r.counter_key == "ws"), None)
        assert ws_row is not None
        assert ws_row.current_value == 1

    def test_night_message_counter_during_night(
        self, db_session: Session, test_user: User
    ) -> None:
        night_time = datetime(2026, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
        with patch("onyx.db.usage.datetime") as mock_dt:
            mock_dt.now.return_value = night_time
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            track_user_activity(db_session, test_user.id)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        nm_row = next((r for r in rows if r.counter_key == "nm"), None)
        assert nm_row is not None
        assert nm_row.current_value == 1

    def test_night_message_counter_during_day(
        self, db_session: Session, test_user: User
    ) -> None:
        day_time = datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
        with patch("onyx.db.usage.datetime") as mock_dt:
            mock_dt.now.return_value = day_time
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            track_user_activity(db_session, test_user.id)
        db_session.commit()

        rows = get_user_counters(db_session, test_user.id)
        nm_row = next((r for r in rows if r.counter_key == "nm"), None)
        assert nm_row is None

    def test_user_isolation(self, db_session: Session, test_user: User) -> None:
        other_user = create_test_user(db_session, "counter_isolated")

        track_user_activity(db_session, test_user.id, deep_research=True)
        track_user_activity(db_session, other_user.id)
        db_session.commit()

        test_rows = get_user_counters(db_session, test_user.id)
        other_rows = get_user_counters(db_session, other_user.id)

        test_keys = {r.counter_key for r in test_rows}
        other_keys = {r.counter_key for r in other_rows}

        assert "dr" in test_keys
        assert "dr" not in other_keys
