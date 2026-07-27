"""Tests for the failed-chat (husk) GC criterion and deletion path.

A "failed" chat session is one that has never contained a non-SYSTEM message:
the web client creates sessions lazily at first send and the SYSTEM root
message is written before the user message, so a SYSTEM-only session holds no
user-visible content. These tests exercise get_failed_chat_session_batch — the
criterion used by the perform_failed_chat_cleanup_task sweep — and the hard
delete it performs, against a real Postgres.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.chat import (
    create_chat_session,
    create_new_chat_message,
    delete_chat_session,
    get_chat_session_by_id,
    get_failed_chat_session_batch,
    get_or_create_root_message,
)
from onyx.db.models import ChatMessage, ChatSession, User
from tests.external_dependency_unit.conftest import create_test_user

_WINDOW = timedelta(days=7)


@pytest.fixture
def test_user(db_session: Session) -> User:
    return create_test_user(db_session, email_prefix="failed_chat_gc")


@pytest.fixture
def session_tracker(
    db_session: Session,
) -> Generator[list[UUID], None, None]:
    """Collects created session ids and hard-deletes any that survive the test."""
    created: list[UUID] = []
    yield created
    for session_id in created:
        if db_session.get(ChatSession, session_id) is not None:
            delete_chat_session(
                user_id=None,
                chat_session_id=session_id,
                db_session=db_session,
                include_deleted=True,
                hard_delete=True,
            )


def _create_session(
    db_session: Session,
    user_id: UUID,
    tracker: list[UUID],
    age: timedelta,
    with_root_message: bool = True,
    deleted: bool = False,
) -> ChatSession:
    chat_session = create_chat_session(
        db_session=db_session,
        description=None,
        user_id=user_id,
        persona_id=None,
    )
    tracker.append(chat_session.id)
    if with_root_message:
        get_or_create_root_message(
            chat_session_id=chat_session.id, db_session=db_session
        )
    _backdate(db_session, chat_session.id, age, deleted=deleted)
    return chat_session


def _backdate(
    db_session: Session,
    chat_session_id: UUID,
    age: timedelta,
    deleted: bool = False,
    include_messages: bool = True,
) -> None:
    """Set the session (and optionally its messages) timestamps ``age`` in the
    past. time_updated must be assigned explicitly or onupdate would bump it."""
    ts = datetime.now(timezone.utc) - age
    db_session.execute(
        update(ChatSession)
        .where(ChatSession.id == chat_session_id)
        .values(time_created=ts, time_updated=ts, deleted=deleted)
    )
    if include_messages:
        db_session.execute(
            update(ChatMessage)
            .where(ChatMessage.chat_session_id == chat_session_id)
            .values(time_sent=ts)
        )
    db_session.commit()


def _add_user_message(db_session: Session, chat_session_id: UUID) -> None:
    root = get_or_create_root_message(
        chat_session_id=chat_session_id, db_session=db_session
    )
    create_new_chat_message(
        chat_session_id=chat_session_id,
        parent_message=root,
        message="hello",
        token_count=1,
        message_type=MessageType.USER,
        db_session=db_session,
        commit=True,
    )


def _sweep_failed_ids(db_session: Session, cutoff: datetime) -> set[UUID]:
    """Run a full keyset sweep, exactly like the chained cleanup task does."""
    failed: set[UUID] = set()
    after_id: UUID | None = None
    while True:
        batch, after_id = get_failed_chat_session_batch(
            db_session=db_session,
            cutoff=cutoff,
            after_id=after_id,
            batch_size=100,
        )
        failed.update(session_id for _, session_id in batch)
        if after_id is None:
            return failed


def test_old_husks_are_flagged_and_hard_deleted(
    db_session: Session, test_user: User, session_tracker: list[UUID]
) -> None:
    husk = _create_session(
        db_session, test_user.id, session_tracker, age=_WINDOW + timedelta(days=1)
    )
    soft_deleted_husk = _create_session(
        db_session,
        test_user.id,
        session_tracker,
        age=_WINDOW + timedelta(days=30),
        deleted=True,
    )
    messageless_husk = _create_session(
        db_session,
        test_user.id,
        session_tracker,
        age=_WINDOW + timedelta(days=1),
        with_root_message=False,
    )

    cutoff = datetime.now(timezone.utc) - _WINDOW
    failed_ids = _sweep_failed_ids(db_session, cutoff)
    assert husk.id in failed_ids
    assert soft_deleted_husk.id in failed_ids
    assert messageless_husk.id in failed_ids

    for session_id in (husk.id, soft_deleted_husk.id, messageless_husk.id):
        delete_chat_session(
            user_id=test_user.id,
            chat_session_id=session_id,
            db_session=db_session,
            include_deleted=True,
            hard_delete=True,
        )
        assert db_session.get(ChatSession, session_id) is None
        orphaned_messages = db_session.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.chat_session_id == session_id)
        ).scalar_one()
        assert orphaned_messages == 0


def test_recent_husk_is_kept(
    db_session: Session, test_user: User, session_tracker: list[UUID]
) -> None:
    recent_husk = _create_session(
        db_session, test_user.id, session_tracker, age=timedelta(days=1)
    )

    cutoff = datetime.now(timezone.utc) - _WINDOW
    assert recent_husk.id not in _sweep_failed_ids(db_session, cutoff)


def test_old_session_with_user_messages_is_kept(
    db_session: Session, test_user: User, session_tracker: list[UUID]
) -> None:
    real_session = _create_session(
        db_session, test_user.id, session_tracker, age=_WINDOW + timedelta(days=30)
    )
    _add_user_message(db_session, real_session.id)
    # Messages predate the cutoff too — age alone must not doom the session.
    _backdate(db_session, real_session.id, age=_WINDOW + timedelta(days=30))

    cutoff = datetime.now(timezone.utc) - _WINDOW
    assert real_session.id not in _sweep_failed_ids(db_session, cutoff)


def test_precreated_session_that_later_receives_messages_stays_usable(
    db_session: Session, test_user: User, session_tracker: list[UUID]
) -> None:
    # An API consumer pre-created an empty session inside the window ...
    precreated = _create_session(
        db_session,
        test_user.id,
        session_tracker,
        age=timedelta(days=3),
        with_root_message=False,
    )

    cutoff = datetime.now(timezone.utc) - _WINDOW
    assert precreated.id not in _sweep_failed_ids(db_session, cutoff)

    # ... and sends its first message days later: still present, still usable.
    _add_user_message(db_session, precreated.id)
    assert precreated.id not in _sweep_failed_ids(db_session, cutoff)
    assert (
        get_chat_session_by_id(
            chat_session_id=precreated.id,
            user_id=test_user.id,
            db_session=db_session,
        ).id
        == precreated.id
    )


def test_recent_system_message_guards_old_session(
    db_session: Session, test_user: User, session_tracker: list[UUID]
) -> None:
    """An in-flight first send writes the SYSTEM root moments before the user
    message commits; a session with a fresh SYSTEM message must not be swept
    even when the session row itself is old enough."""
    racing_session = _create_session(
        db_session,
        test_user.id,
        session_tracker,
        age=_WINDOW + timedelta(days=1),
        with_root_message=False,
    )
    # Root created "now", session rows backdated — the mid-send state.
    get_or_create_root_message(chat_session_id=racing_session.id, db_session=db_session)
    _backdate(
        db_session,
        racing_session.id,
        age=_WINDOW + timedelta(days=1),
        include_messages=False,
    )

    cutoff = datetime.now(timezone.utc) - _WINDOW
    assert racing_session.id not in _sweep_failed_ids(db_session, cutoff)
