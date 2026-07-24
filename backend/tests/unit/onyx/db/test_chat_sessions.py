"""Tests for get_chat_sessions_by_user filtering behavior.

Verifies that failed chat sessions (those with only SYSTEM messages) are
correctly filtered out while preserving recently created sessions, matching
the behavior specified in PR #7233.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.models import ChatSession


def _make_session(
    user_id: UUID,
    time_created: datetime | None = None,
    time_updated: datetime | None = None,
    description: str = "",
) -> MagicMock:
    """Create a mock ChatSession with the given attributes."""
    session = MagicMock(spec=ChatSession)
    session.id = uuid4()
    session.user_id = user_id
    session.time_created = time_created or datetime.now(timezone.utc)
    session.time_updated = time_updated or session.time_created
    session.description = description
    session.deleted = False
    session.onyxbot_flow = False
    session.project_id = None
    return session


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def old_time() -> datetime:
    """A timestamp well outside the 5-minute leeway window."""
    return datetime.now(timezone.utc) - timedelta(hours=1)


@pytest.fixture
def recent_time() -> datetime:
    """A timestamp within the 5-minute leeway window."""
    return datetime.now(timezone.utc) - timedelta(minutes=2)


class TestGetChatSessionsByUser:
    """Tests for the failed chat filtering logic in get_chat_sessions_by_user."""

    def test_filters_out_failed_sessions(
        self, user_id: UUID, old_time: datetime
    ) -> None:
        """Sessions with only SYSTEM messages should be excluded."""
        valid_session = _make_session(user_id, time_created=old_time)
        failed_session = _make_session(user_id, time_created=old_time)

        db_session = MagicMock(spec=Session)

        # First execute: returns all sessions
        # Second execute: returns only the valid session's ID (has non-system msgs)
        mock_result_1 = MagicMock()
        mock_result_1.scalars.return_value.all.return_value = [
            valid_session,
            failed_session,
        ]

        mock_result_2 = MagicMock()
        mock_result_2.scalars.return_value.all.return_value = [valid_session.id]

        db_session.execute.side_effect = [mock_result_1, mock_result_2]

        result = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            include_failed_chats=False,
        )

        assert len(result) == 1
        assert result[0].id == valid_session.id

    def test_keeps_recent_sessions_without_messages(
        self, user_id: UUID, recent_time: datetime
    ) -> None:
        """Recently created sessions should be kept even without messages."""
        recent_session = _make_session(user_id, time_created=recent_time)

        db_session = MagicMock(spec=Session)

        mock_result_1 = MagicMock()
        mock_result_1.scalars.return_value.all.return_value = [recent_session]

        db_session.execute.side_effect = [mock_result_1]

        result = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            include_failed_chats=False,
        )

        assert len(result) == 1
        assert result[0].id == recent_session.id
        # Should only have been called once — no second query needed
        # because the recent session is within the leeway window
        assert db_session.execute.call_count == 1

    def test_include_failed_chats_skips_filtering(
        self, user_id: UUID, old_time: datetime
    ) -> None:
        """When include_failed_chats=True, no filtering should occur."""
        session_a = _make_session(user_id, time_created=old_time)
        session_b = _make_session(user_id, time_created=old_time)

        db_session = MagicMock(spec=Session)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [session_a, session_b]

        db_session.execute.side_effect = [mock_result]

        result = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            include_failed_chats=True,
        )

        assert len(result) == 2
        # Only one DB call — no second query for message validation
        assert db_session.execute.call_count == 1

    def test_limit_applied_after_filtering(
        self, user_id: UUID, old_time: datetime
    ) -> None:
        """Limit should be applied after filtering, not before."""
        sessions = [_make_session(user_id, time_created=old_time) for _ in range(5)]
        valid_ids = [s.id for s in sessions[:3]]

        db_session = MagicMock(spec=Session)

        mock_result_1 = MagicMock()
        mock_result_1.scalars.return_value.all.return_value = sessions

        mock_result_2 = MagicMock()
        mock_result_2.scalars.return_value.all.return_value = valid_ids

        db_session.execute.side_effect = [mock_result_1, mock_result_2]

        result = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            include_failed_chats=False,
            limit=2,
        )

        assert len(result) == 2
        # Should be the first 2 valid sessions (order preserved)
        assert result[0].id == sessions[0].id
        assert result[1].id == sessions[1].id

    def test_mixed_recent_and_old_sessions(
        self, user_id: UUID, old_time: datetime, recent_time: datetime
    ) -> None:
        """Mix of recent and old sessions should filter correctly."""
        old_valid = _make_session(user_id, time_created=old_time)
        old_failed = _make_session(user_id, time_created=old_time)
        recent_no_msgs = _make_session(user_id, time_created=recent_time)

        db_session = MagicMock(spec=Session)

        mock_result_1 = MagicMock()
        mock_result_1.scalars.return_value.all.return_value = [
            old_valid,
            old_failed,
            recent_no_msgs,
        ]

        mock_result_2 = MagicMock()
        mock_result_2.scalars.return_value.all.return_value = [old_valid.id]

        db_session.execute.side_effect = [mock_result_1, mock_result_2]

        result = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            include_failed_chats=False,
        )

        result_ids = {cs.id for cs in result}
        assert old_valid.id in result_ids
        assert recent_no_msgs.id in result_ids
        assert old_failed.id not in result_ids

    def test_fetches_next_batch_when_filtering_undershoots(
        self, user_id: UUID, old_time: datetime
    ) -> None:
        """When failed sessions shrink a batch below the limit, the next batch
        is fetched with a keyset cursor instead of fetching the full history."""
        # limit=2 fetches batches of 2 + slack (10) = 12 rows.
        first_batch = [
            _make_session(
                user_id,
                time_created=old_time,
                time_updated=old_time - timedelta(minutes=i),
            )
            for i in range(12)
        ]
        second_batch = [
            _make_session(
                user_id,
                time_created=old_time,
                time_updated=old_time - timedelta(minutes=20 + i),
            )
            for i in range(2)
        ]

        db_session = MagicMock(spec=Session)

        # Batch 1: only one of the 12 sessions is valid -> undershoots limit.
        mock_batch_1 = MagicMock()
        mock_batch_1.scalars.return_value.all.return_value = first_batch
        mock_filter_1 = MagicMock()
        mock_filter_1.scalars.return_value.all.return_value = [first_batch[0].id]

        # Batch 2: both sessions are valid.
        mock_batch_2 = MagicMock()
        mock_batch_2.scalars.return_value.all.return_value = second_batch
        mock_filter_2 = MagicMock()
        mock_filter_2.scalars.return_value.all.return_value = [
            s.id for s in second_batch
        ]

        db_session.execute.side_effect = [
            mock_batch_1,
            mock_filter_1,
            mock_batch_2,
            mock_filter_2,
        ]

        result = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            include_failed_chats=False,
            limit=2,
        )

        assert [cs.id for cs in result] == [first_batch[0].id, second_batch[0].id]
        assert db_session.execute.call_count == 4

        # Both session fetches are SQL-limited, and the second one is
        # keyset-cursored on the last row of the first batch.
        first_stmt = db_session.execute.call_args_list[0].args[0]
        second_stmt = db_session.execute.call_args_list[2].args[0]
        assert "LIMIT" in str(first_stmt)
        assert "LIMIT" in str(second_stmt)
        assert first_batch[-1].time_updated in second_stmt.compile().params.values()

    def test_empty_result(self, user_id: UUID) -> None:
        """No sessions should return empty list without errors."""
        db_session = MagicMock(spec=Session)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db_session.execute.side_effect = [mock_result]

        result = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            include_failed_chats=False,
        )

        assert result == []
        assert db_session.execute.call_count == 1
