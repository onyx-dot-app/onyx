from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import UUID

from sqlalchemy.orm import Session

from ee.onyx.db.usage_export import get_all_empty_chat_message_entries
from ee.onyx.db.usage_export import get_empty_chat_messages_entries__paginated
from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from tests.external_dependency_unit.conftest import create_test_user


def _full_period() -> tuple[datetime, datetime]:
    return (
        datetime.fromtimestamp(0, tz=timezone.utc),
        datetime.now(tz=timezone.utc),
    )


def _make_user_message(
    db_session: Session, chat_session_id: UUID, parent: ChatMessage
) -> ChatMessage:
    return create_new_chat_message(
        chat_session_id=chat_session_id,
        parent_message=parent,
        message="user prompt",
        token_count=0,
        message_type=MessageType.USER,
        db_session=db_session,
    )


def _make_assistant_message(
    db_session: Session,
    chat_session_id: UUID,
    parent: ChatMessage,
    model_display_name: str,
) -> ChatMessage:
    msg = create_new_chat_message(
        chat_session_id=chat_session_id,
        parent_message=parent,
        message="assistant reply",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
    )
    msg.model_display_name = model_display_name
    db_session.commit()
    return msg


def test_multi_model_branch_emits_row_per_assistant_child(
    db_session: Session,
) -> None:
    """A user message answered by multiple models (multi-model branch) must
    produce one report row per assistant child so no model invocation is
    dropped — even non-preferred branches."""
    user = create_test_user(db_session, "usage-export-branch")
    chat_session = create_chat_session(
        db_session=db_session,
        description="multi-model branch",
        user_id=user.id,
        persona_id=None,
    )
    root = get_or_create_root_message(chat_session.id, db_session)

    user_msg = _make_user_message(db_session, chat_session.id, root)
    _make_assistant_message(db_session, chat_session.id, user_msg, "model-a")
    assistant_b = _make_assistant_message(
        db_session, chat_session.id, user_msg, "model-b"
    )

    # Even when one branch is marked preferred, both must still be reported.
    user_msg.preferred_response_id = assistant_b.id
    db_session.commit()

    _, skeletons = get_empty_chat_messages_entries__paginated(
        db_session, _full_period()
    )

    matching = [s for s in skeletons if s.message_id == user_msg.id]
    assert {s.llm_model for s in matching} == {"model-a", "model-b"}
    assert len(matching) == 2


def test_single_assistant_child_emits_single_row(db_session: Session) -> None:
    """The common case (one assistant reply per user message) still produces
    exactly one row with that model. Guards against the per-pair change
    inflating row counts in non-branched conversations."""
    user = create_test_user(db_session, "usage-export-single")
    chat_session = create_chat_session(
        db_session=db_session,
        description="single reply",
        user_id=user.id,
        persona_id=None,
    )
    root = get_or_create_root_message(chat_session.id, db_session)

    user_msg = _make_user_message(db_session, chat_session.id, root)
    _make_assistant_message(db_session, chat_session.id, user_msg, "only-model")

    _, skeletons = get_empty_chat_messages_entries__paginated(
        db_session, _full_period()
    )

    matching = [s for s in skeletons if s.message_id == user_msg.id]
    assert len(matching) == 1
    assert matching[0].llm_model == "only-model"


def test_pagination_does_not_drop_sessions_sharing_boundary_timestamp(
    db_session: Session,
) -> None:
    """Regression for ONX-2293: the usage CSV export drops rows once the data
    exceeds the 500-session page limit and sessions share the boundary
    ``time_created``.

    ``fetch_chat_sessions_eagerly_by_time`` paginated with a strict ``>``
    cursor on the non-unique ``ChatSession.time_created``; every session
    sharing the last page's timestamp was skipped by the next page. Here all
    sessions share one timestamp and the count crosses the page boundary, so
    the buggy implementation emits only the first page worth of rows.
    """
    user = create_test_user(db_session, "usage-export-pagination")
    shared_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # One past the 500-row page size so the dataset spans more than one page.
    num_sessions = 501
    expected_session_ids = set()
    try:
        for _ in range(num_sessions):
            chat_session = create_chat_session(
                db_session=db_session,
                description="boundary collision",
                user_id=user.id,
                persona_id=None,
            )
            db_session.query(ChatSession).filter(
                ChatSession.id == chat_session.id
            ).update({ChatSession.time_created: shared_time})
            root = get_or_create_root_message(chat_session.id, db_session)
            _make_user_message(db_session, chat_session.id, root)
            expected_session_ids.add(chat_session.id)
        db_session.commit()

        seen_session_ids = [
            skeleton.chat_session_id
            for batch in get_all_empty_chat_message_entries(db_session, _full_period())
            for skeleton in batch
        ]
        # Other tests share the DB, so scope to the sessions we created.
        mine_seen = [sid for sid in seen_session_ids if sid in expected_session_ids]

        # No session should be dropped, and none double-counted.
        assert set(mine_seen) == expected_session_ids
        assert len(mine_seen) == num_sessions
    finally:
        # Keep the shared DB small: sibling tests use the single-page helper and
        # assume their freshly-created session lands on the first page.
        if expected_session_ids:
            db_session.query(ChatMessage).filter(
                ChatMessage.chat_session_id.in_(expected_session_ids)
            ).delete(synchronize_session=False)
            db_session.query(ChatSession).filter(
                ChatSession.id.in_(expected_session_ids)
            ).delete(synchronize_session=False)
            db_session.commit()


def test_full_page_with_no_user_messages_keeps_paginating(
    db_session: Session,
) -> None:
    """A full page (``len == limit``) that happens to contain no USER messages
    must still return a non-None cursor so iteration continues — otherwise
    later pages (which may hold USER messages) are silently dropped.

    This is the second half of the ONX-2293 fix: pagination now terminates on a
    short page rather than on an empty skeleton list.
    """
    user = create_test_user(db_session, "usage-export-empty-page")
    shared_time = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Tight window so only the sessions created here are in range, independent
    # of other sessions in the shared DB.
    window = (
        shared_time - timedelta(seconds=1),
        shared_time + timedelta(seconds=1),
    )

    session_ids = []
    try:
        # Two sessions whose only message is an assistant reply (no USER message).
        for _ in range(2):
            chat_session = create_chat_session(
                db_session=db_session,
                description="no user messages",
                user_id=user.id,
                persona_id=None,
            )
            db_session.query(ChatSession).filter(
                ChatSession.id == chat_session.id
            ).update({ChatSession.time_created: shared_time})
            root = get_or_create_root_message(chat_session.id, db_session)
            _make_assistant_message(db_session, chat_session.id, root, "model-x")
            session_ids.append(chat_session.id)
        db_session.commit()

        # A full page (limit == number of sessions) with zero USER messages must
        # advance the cursor rather than signalling end-of-data.
        full_page_cursor, skeletons = get_empty_chat_messages_entries__paginated(
            db_session, window, limit=2
        )
        assert skeletons == []
        assert full_page_cursor is not None

        # A short page (fewer sessions than the limit) signals the end.
        short_page_cursor, _ = get_empty_chat_messages_entries__paginated(
            db_session, window, limit=10
        )
        assert short_page_cursor is None
    finally:
        if session_ids:
            db_session.query(ChatMessage).filter(
                ChatMessage.chat_session_id.in_(session_ids)
            ).delete(synchronize_session=False)
            db_session.query(ChatSession).filter(
                ChatSession.id.in_(session_ids)
            ).delete(synchronize_session=False)
            db_session.commit()


def test_orphan_user_message_emits_row_with_null_model(db_session: Session) -> None:
    """User message with no assistant reply (still streaming, errored) gets a
    single row with `llm_model=None` rather than being dropped."""
    user = create_test_user(db_session, "usage-export-orphan")
    chat_session = create_chat_session(
        db_session=db_session,
        description="orphan user message",
        user_id=user.id,
        persona_id=None,
    )
    root = get_or_create_root_message(chat_session.id, db_session)

    user_msg = _make_user_message(db_session, chat_session.id, root)

    _, skeletons = get_empty_chat_messages_entries__paginated(
        db_session, _full_period()
    )

    matching = [s for s in skeletons if s.message_id == user_msg.id]
    assert len(matching) == 1
    assert matching[0].llm_model is None
