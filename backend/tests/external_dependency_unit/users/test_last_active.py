"""`batch_get_last_active` reports real activity, which `User.updated_at` does not.

`User.updated_at` has `onupdate=func.now()`, so it only moves when the user row itself
is written — a role change, a theme preference. Logging in and chatting never touch it,
so the admin Users page showed a stale timestamp for people who were actively chatting.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.models import ChatMessage
from onyx.db.users import batch_get_last_active
from tests.external_dependency_unit.conftest import create_test_user


def test_returns_most_recent_session_per_user(db_session: Session) -> None:
    user = create_test_user(db_session, "last-active-recent")

    older = create_chat_session(
        db_session, description="older", user_id=user.id, persona_id=None
    )
    newer = create_chat_session(
        db_session, description="newer", user_id=user.id, persona_id=None
    )
    now = datetime.now(timezone.utc)
    older.time_updated = now - timedelta(days=3)
    newer.time_updated = now - timedelta(minutes=5)
    db_session.commit()

    result = batch_get_last_active(db_session, [user.id])

    assert result[user.id] == newer.time_updated


def test_user_without_chat_sessions_reports_none(db_session: Session) -> None:
    """A real user who has never chatted must be distinguishable from an active one."""
    user = create_test_user(db_session, "last-active-never")

    result = batch_get_last_active(db_session, [user.id])

    assert user.id in result
    assert result[user.id] is None


def test_activity_is_not_attributed_across_users(db_session: Session) -> None:
    chatty = create_test_user(db_session, "last-active-chatty")
    quiet = create_test_user(db_session, "last-active-quiet")

    session = create_chat_session(
        db_session, description="chatty", user_id=chatty.id, persona_id=None
    )
    db_session.commit()

    result = batch_get_last_active(db_session, [chatty.id, quiet.id])

    assert result[chatty.id] == session.time_updated
    assert result[quiet.id] is None


def test_diverges_from_updated_at(db_session: Session) -> None:
    """The regression: chatting does not bump `updated_at`, so the two disagree."""
    user = create_test_user(db_session, "last-active-diverges")
    updated_at_before = user.updated_at

    create_chat_session(
        db_session, description="fresh", user_id=user.id, persona_id=None
    )
    db_session.commit()
    db_session.refresh(user)

    last_active = batch_get_last_active(db_session, [user.id])[user.id]

    assert last_active is not None
    # Chatting left the user row untouched, which is exactly why the page was wrong.
    assert user.updated_at == updated_at_before
    assert last_active > updated_at_before


def test_empty_input_skips_the_query(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty input must short-circuit, not issue a query with an empty IN list."""
    calls: list[Any] = []
    real_execute = db_session.execute

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", spy)

    assert batch_get_last_active(db_session, []) == {}
    assert calls == []


def test_follow_up_message_advances_last_active(db_session: Session) -> None:
    """The regression both reviewers caught.

    `ChatSession.time_updated` only moves when the session row is written, so a
    follow-up message in an existing chat leaves it untouched. Aggregating it
    alone reported the session's creation time while the user was mid-conversation.
    """
    user = create_test_user(db_session, "last-active-followup")

    session = create_chat_session(
        db_session, description="ongoing", user_id=user.id, persona_id=None
    )
    db_session.commit()
    session_started = batch_get_last_active(db_session, [user.id])[user.id]
    assert session_started is not None

    # A follow-up turn: only a ChatMessage row is written.
    db_session.add(
        ChatMessage(
            chat_session_id=session.id,
            message="a follow-up",
            token_count=0,
            message_type=MessageType.USER,
            time_sent=session_started + timedelta(hours=2),
        )
    )
    db_session.commit()
    db_session.refresh(session)

    last_active = batch_get_last_active(db_session, [user.id])[user.id]

    assert last_active is not None
    # The session row itself never moved — that is the whole point.
    assert session.time_updated == session_started
    assert last_active > session_started
