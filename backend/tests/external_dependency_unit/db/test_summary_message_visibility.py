"""Guards that context summaries stay out of every public chat-history surface.

A summary row is internal model context. Exercises the real WHERE clauses
against Postgres, since a mocked session would return rows the SQL filters.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.query_history import (
    fetch_chat_sessions_eagerly_by_time,
    get_page_of_chat_sessions,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    create_chat_session,
    create_new_chat_message,
    find_summary_for_branch,
    get_chat_message,
    get_chat_messages_by_session,
    get_chat_messages_by_sessions,
    get_chat_session_by_message_id,
    get_or_create_root_message,
)
from onyx.db.chat_search import search_chat_sessions
from onyx.db.models import ChatMessage, ChatSession, User
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

SUMMARY_ONLY_WORD = "zebracornsummary"


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "summary-visibility")
    yield user

    db_session.rollback()
    db_session.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    delete_test_user(db_session, user)
    db_session.commit()


def _session_with_summary(
    db_session: Session, owner: User
) -> tuple[ChatSession, list[ChatMessage], ChatMessage]:
    chat_session = create_chat_session(
        db_session=db_session,
        description="ordinary chat",
        user_id=owner.id,
        persona_id=None,
    )
    root = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )
    user_message = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=root,
        message="hello",
        token_count=1,
        message_type=MessageType.USER,
        db_session=db_session,
    )
    answer = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=user_message,
        message="hi there",
        token_count=2,
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
    )
    # Written the same way compression writes it: no latest-child update.
    summary = ChatMessage(
        chat_session_id=chat_session.id,
        message_type=MessageType.SUMMARY,
        message=f"summary {SUMMARY_ONLY_WORD}",
        token_count=2,
        parent_message_id=user_message.id,
        last_summarized_message_id=f"chat:{user_message.id}",
    )
    db_session.add(summary)
    db_session.commit()
    return chat_session, [root, user_message, answer], summary


def test_session_message_listings_exclude_summaries(
    db_session: Session, owner: User
) -> None:
    chat_session, visible, summary = _session_with_summary(db_session, owner)
    visible_ids = {message.id for message in visible}

    by_session = get_chat_messages_by_session(
        chat_session_id=chat_session.id, user_id=owner.id, db_session=db_session
    )
    assert {message.id for message in by_session} == visible_ids

    by_sessions = get_chat_messages_by_sessions(
        chat_session_ids=[chat_session.id], user_id=owner.id, db_session=db_session
    )
    assert {message.id for message in by_sessions} == visible_ids

    # Compression still reads its summary directly.
    found = find_summary_for_branch(db_session, list(by_session))
    assert found is not None and found.id == summary.id


def test_summary_is_not_addressable_by_id(db_session: Session, owner: User) -> None:
    _, visible, summary = _session_with_summary(db_session, owner)

    assert get_chat_message(visible[-1].id, owner.id, db_session).id == visible[-1].id
    with pytest.raises(ValueError):
        get_chat_message(summary.id, owner.id, db_session)
    with pytest.raises(ValueError):
        get_chat_session_by_message_id(db_session, summary.id)


def test_search_does_not_match_summary_text(db_session: Session, owner: User) -> None:
    _session_with_summary(db_session, owner)

    sessions, _ = search_chat_sessions(
        user_id=owner.id, db_session=db_session, query=SUMMARY_ONLY_WORD
    )
    assert sessions == []


def test_query_history_excludes_summaries(db_session: Session, owner: User) -> None:
    chat_session, visible, summary = _session_with_summary(db_session, owner)
    db_session.expire_all()

    page = get_page_of_chat_sessions(
        start_time=None,
        end_time=None,
        db_session=db_session,
        page_num=0,
        page_size=1000,
    )
    window = timedelta(minutes=5)
    now = datetime.now(timezone.utc)
    metered = fetch_chat_sessions_eagerly_by_time(
        start=now - window, end=now + window, db_session=db_session, limit=None
    )

    for sessions in (page, metered):
        listed = next(s for s in sessions if s.id == chat_session.id)
        message_ids = {message.id for message in listed.messages}
        assert summary.id not in message_ids
        assert visible[-1].id in message_ids


def test_find_summary_for_branch_uses_nearest_ancestor_on_branch(
    db_session: Session, owner: User
) -> None:
    chat_session, (root, user_message, answer), first_summary = _session_with_summary(
        db_session, owner
    )
    follow_up = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=answer,
        message="tell me more",
        token_count=3,
        message_type=MessageType.USER,
        db_session=db_session,
    )
    other_branch = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=answer,
        message="a different question",
        token_count=3,
        message_type=MessageType.USER,
        db_session=db_session,
    )
    nearer_summary = ChatMessage(
        chat_session_id=chat_session.id,
        message_type=MessageType.SUMMARY,
        message="newer summary",
        token_count=2,
        parent_message_id=follow_up.id,
        last_summarized_message_id=f"chat:{answer.id}",
    )
    db_session.add(nearer_summary)
    db_session.commit()

    on_branch = find_summary_for_branch(
        db_session, [root, user_message, answer, follow_up]
    )
    assert on_branch is not None and on_branch.id == nearer_summary.id

    # The newer summary belongs to a sibling branch, so the shared ancestor's applies.
    off_branch = find_summary_for_branch(
        db_session, [root, user_message, answer, other_branch]
    )
    assert off_branch is not None and off_branch.id == first_summary.id

    # A later summary on the same ancestor replaces the earlier one.
    replacement = ChatMessage(
        chat_session_id=chat_session.id,
        message_type=MessageType.SUMMARY,
        message="replacement summary",
        token_count=2,
        parent_message_id=user_message.id,
        last_summarized_message_id=f"chat:{user_message.id}",
    )
    db_session.add(replacement)
    db_session.commit()
    replaced = find_summary_for_branch(
        db_session, [root, user_message, answer, other_branch]
    )
    assert replaced is not None and replaced.id == replacement.id
