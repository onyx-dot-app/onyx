"""The chat detail route against Postgres and the shared cache."""

from collections.abc import Generator, Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO
from itertools import count
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import String, cast, select, update
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.configs.constants import (
    CHAT_SESSION_ID_FILE_METADATA_KEY,
    DEFAULT_PERSONA_ID,
    FileOrigin,
    MessageType,
)
from onyx.db.chat import create_new_chat_message, get_or_create_root_message
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import (
    ChatMessage,
    ChatSession,
    ChatSessionSharedStatus,
    FileRecord,
    User,
)
from onyx.file_store.constants import chat_artifact_file_id
from onyx.file_store.file_store import (
    FILE_SIZE_MISSING_SENTINEL,
    get_default_file_store,
)
from onyx.file_store.utils import save_chat_output_file
from onyx.server.query_and_chat import chat_backend
from tests.external_dependency_unit.conftest import MakeTestUser


@pytest.fixture
def owner(
    make_test_user: MakeTestUser, db_session: Session
) -> Generator[User, None, None]:
    """A test user. Teardown deletes the files stamped with its chats."""
    user = make_test_user("chat-session-detail")
    yield user
    db_session.rollback()
    chat_ids = select(cast(ChatSession.id, String)).where(
        ChatSession.user_id == user.id
    )
    file_ids = db_session.scalars(
        select(FileRecord.file_id).where(
            FileRecord.file_metadata[CHAT_SESSION_ID_FILE_METADATA_KEY].astext.in_(
                chat_ids
            )
        )
    ).all()
    for file_id in file_ids:
        get_default_file_store().delete_file(file_id, error_on_missing=False)


def test_an_idle_chat_detail_holds_the_saves_of_the_turn_that_ended(
    db_session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="Read order",
    )
    db_session.add(chat)
    db_session.flush()
    root = ChatMessage(
        chat_session_id=chat.id,
        message="",
        token_count=0,
        message_type=MessageType.SYSTEM,
    )
    db_session.add(root)
    db_session.flush()
    question = ChatMessage(
        parent_message_id=root.id,
        chat_session_id=chat.id,
        message="Question",
        token_count=1,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.commit()
    question_id = question.id

    turn = ChatTurnAdmission(get_cache_backend())
    turn.claim(chat.id)
    read_messages = chat_backend.get_chat_messages_by_session

    def read_then_end_turn(**kwargs: Any) -> Sequence[ChatMessage]:
        messages = read_messages(**kwargs)
        # The turn saves its reply and then releases admission, after the
        # route has read the messages.
        with get_session_with_current_tenant() as run_session:
            run_session.add(
                ChatMessage(
                    parent_message_id=question_id,
                    chat_session_id=chat.id,
                    message="Reply",
                    token_count=1,
                    message_type=MessageType.ASSISTANT,
                )
            )
            run_session.commit()
        turn.release()
        return messages

    monkeypatch.setattr(
        chat_backend, "get_chat_messages_by_session", read_then_end_turn
    )
    try:
        detail = chat_backend.get_chat_session(
            chat.id, user=owner, db_session=db_session
        )
    finally:
        turn.release()

    # A client stores an idle page as final, so an idle page must hold the reply.
    assert detail.is_processing or "Reply" in [
        message.message for message in detail.messages
    ]


def _new_chat(db_session: Session, owner: User) -> ChatSession:
    chat = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="Published files",
    )
    db_session.add(chat)
    db_session.commit()
    return chat


def _add(
    db_session: Session, parent: ChatMessage, message_type: MessageType
) -> ChatMessage:
    return create_new_chat_message(
        chat_session_id=parent.chat_session_id,
        parent_message=parent,
        message=message_type.value,
        token_count=1,
        message_type=message_type,
        db_session=db_session,
    )


# Publish times one second apart, so the order does not rest on the clock
_PUBLISHED_AT = datetime(2026, 11, 18, tzinfo=timezone.utc)
_PUBLISH_ORDER = count()


def _publish(
    db_session: Session,
    chat: ChatSession,
    path: str,
    title: str | None = None,
    missing: bool = False,
) -> str:
    """A file that `publish_files` saved for the chat, as the next publish.
    Subagents share the root chat's sandbox turn, so their files carry the
    root chat's ID too."""
    name = path.rsplit("/", 1)[-1]
    file_id = save_chat_output_file(
        name.encode(),
        display_name=name,
        file_type="text/markdown",
        file_origin=FileOrigin.CHAT_ARTIFACT,
        chat_session_id=chat.id,
        published_path=path,
        published_title=title,
    )
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == file_id)
        .values(
            created_at=_PUBLISHED_AT + timedelta(seconds=next(_PUBLISH_ORDER)),
            file_size=FILE_SIZE_MISSING_SENTINEL if missing else len(name),
        )
    )
    db_session.commit()
    return file_id


@pytest.mark.usefixtures("initialize_file_store")
def test_the_latest_page_lists_the_chats_newest_file_of_each_path(
    db_session: Session, owner: User
) -> None:
    """The list holds the newest publish of each path in the chat, oldest
    first, with the path and title from the file record. It holds the files of
    every branch and of the chat's subagents. It leaves out another chat's
    files, files that are not published files, files published without a
    stamped path, and files whose object is missing: a path whose newest copy
    is missing lists its older copy."""
    chat = _new_chat(db_session, owner)
    other_chat = _new_chat(db_session, owner)
    question = _add(
        db_session, get_or_create_root_message(chat.id, db_session), MessageType.USER
    )
    _add(db_session, question, MessageType.ASSISTANT)
    # The user regenerates the answer: the second answer is the branch's.
    _add(db_session, question, MessageType.ASSISTANT)

    _publish(db_session, chat, "/w/report.md", "Draft")
    _publish(db_session, chat, "/w/notes.md")
    _publish(db_session, other_chat, "/w/other.md")
    save_chat_output_file(
        b"png",
        display_name="image.png",
        file_type="image/png",
        file_origin=FileOrigin.CHAT_IMAGE_GEN,
        chat_session_id=chat.id,
    )
    # A published file without a path
    get_default_file_store().save_file(
        content=BytesIO(b"old"),
        display_name="old.md",
        file_origin=FileOrigin.CHAT_ARTIFACT,
        file_type="text/markdown",
        file_metadata={CHAT_SESSION_ID_FILE_METADATA_KEY: str(chat.id)},
        file_id=chat_artifact_file_id(chat.id),
    )
    _publish(db_session, chat, "/w/chart.md", missing=True)
    _publish(db_session, chat, "/w/report.md", "Final")
    _publish(db_session, chat, "/w/notes.md", "Newest notes", missing=True)

    detail = chat_backend.get_chat_session(
        chat.id, limit=1, user=owner, db_session=db_session
    )

    assert detail.published_files is not None
    assert [
        (file.path, file.title, file.name, file.size) for file in detail.published_files
    ] == [
        ("/w/notes.md", None, "notes.md", len("notes.md")),
        ("/w/report.md", "Final", "report.md", len("report.md")),
    ]


@pytest.mark.usefixtures("initialize_file_store")
def test_only_a_latest_page_or_shared_load_lists_the_files(
    db_session: Session, owner: User
) -> None:
    """An older page and an owner's unpaged load carry no list: the client does
    not read it there. A chat without published files has an empty list."""
    empty = _new_chat(db_session, owner)
    _add(
        db_session,
        _add(
            db_session,
            get_or_create_root_message(empty.id, db_session),
            MessageType.USER,
        ),
        MessageType.ASSISTANT,
    )
    assert (
        chat_backend.get_chat_session(
            empty.id, limit=2, user=owner, db_session=db_session
        ).published_files
        == []
    )

    chat = _new_chat(db_session, owner)
    question = _add(
        db_session, get_or_create_root_message(chat.id, db_session), MessageType.USER
    )
    answer = _add(db_session, question, MessageType.ASSISTANT)
    later = _add(db_session, answer, MessageType.USER)
    _publish(db_session, chat, "/w/a.md")

    older_page = chat_backend.get_chat_session(
        chat.id, limit=1, before_message_id=later.id, user=owner, db_session=db_session
    )
    assert answer.id in {message.message_id for message in older_page.messages}
    assert older_page.published_files is None
    unpaged = chat_backend.get_chat_session(chat.id, user=owner, db_session=db_session)
    assert unpaged.published_files is None
    chat.shared_status = ChatSessionSharedStatus.PUBLIC
    db_session.commit()
    for detail in (
        chat_backend.get_chat_session(
            chat.id, is_shared=True, user=owner, db_session=db_session
        ),
        chat_backend.get_chat_session(
            chat.id, limit=1, user=owner, db_session=db_session
        ),
    ):
        assert [file.path for file in detail.published_files or []] == ["/w/a.md"]
