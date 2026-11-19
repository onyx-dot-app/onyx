"""The chat detail route against Postgres and the shared cache."""

from collections.abc import Generator, Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO
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
    ToolCall,
    User,
)
from onyx.file_store.file_store import (
    FILE_SIZE_MISSING_SENTINEL,
    get_default_file_store,
)
from onyx.file_store.models import ChatFileType, FileDescriptor
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


def _new_chat(
    db_session: Session, owner: User, spawned_by: ChatMessage | None = None
) -> ChatSession:
    chat = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="Published files",
        spawned_by_message_id=spawned_by.id if spawned_by is not None else None,
    )
    db_session.add(chat)
    db_session.commit()
    return chat


def _add(
    db_session: Session,
    parent: ChatMessage,
    message_type: MessageType,
    files: list[FileDescriptor] | None = None,
) -> ChatMessage:
    return create_new_chat_message(
        chat_session_id=parent.chat_session_id,
        parent_message=parent,
        message=message_type.value,
        token_count=1,
        message_type=message_type,
        db_session=db_session,
        files=files,
    )


def _run(db_session: Session, invoker: ChatMessage, after: ChatMessage) -> ChatMessage:
    """The question of a subagent run that a tool call of `invoker` starts:
    the first run of a new subagent, or a later run after `after`."""
    call = ToolCall(
        chat_session_id=invoker.chat_session_id,
        parent_chat_message_id=invoker.id,
        turn_number=0,
        tool_call_id=f"call-{uuid4().hex}",
        tool_call_arguments={},
        tool_call_tokens=0,
    )
    db_session.add(call)
    db_session.flush()
    question = _add(db_session, after, MessageType.USER)
    question.invoking_tool_call_id = call.id
    db_session.commit()
    return question


def _publish(chat: ChatSession, path: str, title: str | None = None) -> FileDescriptor:
    """A file that `publish_files` saved. Subagents share the root chat's
    sandbox turn, so their files carry the root chat's ID too."""
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
    return FileDescriptor(id=file_id, type=ChatFileType.PLAIN_TEXT, name=name)


@pytest.mark.usefixtures("initialize_file_store")
def test_the_latest_page_lists_the_branch_files_with_their_stamped_path_and_title(
    db_session: Session, owner: User
) -> None:
    """The list holds the published files of the branch's answers and of the
    subagent sessions that they spawned, recursively, with the path and title
    from the file record. It leaves out another branch's files, files that are
    not published files, files published without a stamped path, and files
    whose object is missing. An answer whose files are a JSON null adds
    nothing."""
    chat = _new_chat(db_session, owner)
    report = _publish(chat, "/w/report.md", "Report")
    image_id = save_chat_output_file(
        b"png",
        display_name="image.png",
        file_type="image/png",
        file_origin=FileOrigin.CHAT_IMAGE_GEN,
        chat_session_id=chat.id,
    )
    # A published file without a path.
    unstamped_id = get_default_file_store().save_file(
        content=BytesIO(b"old"),
        display_name="old.md",
        file_origin=FileOrigin.CHAT_ARTIFACT,
        file_type="text/markdown",
        file_metadata={CHAT_SESSION_ID_FILE_METADATA_KEY: str(chat.id)},
    )
    missing = _publish(chat, "/w/missing.md")
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == missing["id"])
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.commit()

    question = _add(
        db_session, get_or_create_root_message(chat.id, db_session), MessageType.USER
    )
    first_answer = _add(
        db_session,
        question,
        MessageType.ASSISTANT,
        [
            report,
            FileDescriptor(id=image_id, type=ChatFileType.IMAGE, name="image.png"),
            FileDescriptor(id=unstamped_id, type=ChatFileType.PLAIN_TEXT),
            missing,
        ],
    )
    follow_up = _add(db_session, first_answer, MessageType.USER)
    _add(db_session, follow_up, MessageType.ASSISTANT, [_publish(chat, "/w/other.md")])
    last_answer = _add(db_session, follow_up, MessageType.ASSISTANT, None)

    # A subagent of the last answer publishes, and so does its own subagent.
    child = _new_chat(db_session, owner, spawned_by=last_answer)
    child_answer = _add(
        db_session,
        _run(db_session, last_answer, get_or_create_root_message(child.id, db_session)),
        MessageType.ASSISTANT,
        [_publish(chat, "/w/report.md", "Report from a subagent")],
    )
    grandchild = _new_chat(db_session, owner, spawned_by=child_answer)
    _add(
        db_session,
        _run(
            db_session,
            child_answer,
            get_or_create_root_message(grandchild.id, db_session),
        ),
        MessageType.ASSISTANT,
        [_publish(chat, "/w/chart.md")],
    )

    detail = chat_backend.get_chat_session(
        chat.id, limit=2, user=owner, db_session=db_session
    )

    assert [
        (file.path, file.title, file.name, file.size, file.message_id)
        for file in detail.published_files
    ] == [
        ("/w/report.md", "Report", "report.md", len(b"report.md"), first_answer.id),
        (
            "/w/report.md",
            "Report from a subagent",
            "report.md",
            len(b"report.md"),
            last_answer.id,
        ),
        ("/w/chart.md", None, "chart.md", len(b"chart.md"), last_answer.id),
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
    answer = _add(
        db_session, question, MessageType.ASSISTANT, [_publish(chat, "/w/a.md")]
    )
    later = _add(db_session, answer, MessageType.USER)

    older_page = chat_backend.get_chat_session(
        chat.id, limit=1, before_message_id=later.id, user=owner, db_session=db_session
    )
    assert answer.id in {message.message_id for message in older_page.messages}
    assert older_page.published_files == []
    unpaged = chat_backend.get_chat_session(chat.id, user=owner, db_session=db_session)
    assert unpaged.published_files == []
    chat.shared_status = ChatSessionSharedStatus.PUBLIC
    db_session.commit()
    shared = chat_backend.get_chat_session(
        chat.id, is_shared=True, user=owner, db_session=db_session
    )
    assert [file.path for file in shared.published_files] == ["/w/a.md"]
    assert [
        file.path
        for file in chat_backend.get_chat_session(
            chat.id, limit=1, user=owner, db_session=db_session
        ).published_files
    ] == ["/w/a.md"]


@pytest.mark.usefixtures("initialize_file_store")
def test_a_subagent_run_counts_on_the_branch_of_the_turn_that_started_it(
    db_session: Session, owner: User
) -> None:
    """A1 spawns a subagent, A2 publishes the report, and A3 sends the
    subagent a follow-up whose run publishes the report's path again. That run
    belongs to A3: it sorts after A2, and it leaves the list when the user
    regenerates A3."""
    chat = _new_chat(db_session, owner)

    def turn(
        after: ChatMessage, files: list[FileDescriptor] | None = None
    ) -> tuple[ChatMessage, ChatMessage]:
        question = _add(db_session, after, MessageType.USER)
        return question, _add(db_session, question, MessageType.ASSISTANT, files)

    _, first = turn(get_or_create_root_message(chat.id, db_session))
    agent = _new_chat(db_session, owner, spawned_by=first)
    first_run = _add(
        db_session,
        _run(db_session, first, get_or_create_root_message(agent.id, db_session)),
        MessageType.ASSISTANT,
        [_publish(chat, "/w/notes.md")],
    )
    _, second = turn(first, [_publish(chat, "/w/report.md", "Draft")])
    third_question, third = turn(second)
    _add(
        db_session,
        _run(db_session, third, first_run),
        MessageType.ASSISTANT,
        [_publish(chat, "/w/report.md", "Final")],
    )

    def listed() -> list[tuple[str, str | None, int]]:
        detail = chat_backend.get_chat_session(
            chat.id, limit=2, user=owner, db_session=db_session
        )
        return [
            (file.path, file.title, file.message_id) for file in detail.published_files
        ]

    assert listed() == [
        ("/w/notes.md", None, first.id),
        ("/w/report.md", "Draft", second.id),
        ("/w/report.md", "Final", third.id),
    ]

    # The user regenerates A3: the follow-up run is off the branch.
    _add(db_session, third_question, MessageType.ASSISTANT)
    assert listed() == [
        ("/w/notes.md", None, first.id),
        ("/w/report.md", "Draft", second.id),
    ]


@pytest.mark.usefixtures("initialize_file_store")
def test_a_background_run_that_publishes_after_a_later_turn_is_the_latest_copy(
    db_session: Session, owner: User
) -> None:
    """A1 starts a background subagent. A2 publishes the report, and then the
    subagent's run publishes the same path. The list is in publish order, so
    the subagent's copy is the latest, though its run belongs to A1."""
    chat = _new_chat(db_session, owner)
    question = _add(
        db_session, get_or_create_root_message(chat.id, db_session), MessageType.USER
    )
    first = _add(db_session, question, MessageType.ASSISTANT)
    agent = _new_chat(db_session, owner, spawned_by=first)
    run_question = _run(
        db_session, first, get_or_create_root_message(agent.id, db_session)
    )
    turn_copy = _publish(chat, "/w/report.md", "From the turn")
    second = _add(
        db_session,
        _add(db_session, first, MessageType.USER),
        MessageType.ASSISTANT,
        [turn_copy],
    )
    background_copy = _publish(chat, "/w/report.md", "From the subagent")
    _add(db_session, run_question, MessageType.ASSISTANT, [background_copy])
    # Publish times one second apart, so the order does not rest on the clock.
    published_at = datetime(2026, 11, 18, tzinfo=timezone.utc)
    for offset, descriptor in enumerate((turn_copy, background_copy)):
        db_session.execute(
            update(FileRecord)
            .where(FileRecord.file_id == descriptor["id"])
            .values(created_at=published_at + timedelta(seconds=offset))
        )
    db_session.commit()

    detail = chat_backend.get_chat_session(
        chat.id, limit=2, user=owner, db_session=db_session
    )

    assert [(file.title, file.message_id) for file in detail.published_files] == [
        ("From the turn", second.id),
        ("From the subagent", first.id),
    ]


@pytest.mark.usefixtures("initialize_file_store")
def test_a_foreground_subagent_file_is_listed_once(
    db_session: Session, owner: User
) -> None:
    """A foreground subagent's file is on its own response and on the answer
    that waited for it. The list holds it once."""
    chat = _new_chat(db_session, owner)
    question = _add(
        db_session, get_or_create_root_message(chat.id, db_session), MessageType.USER
    )
    answer = _add(db_session, question, MessageType.ASSISTANT)
    agent = _new_chat(db_session, owner, spawned_by=answer)
    report = _publish(chat, "/w/report.md", "Report")
    _add(
        db_session,
        _run(db_session, answer, get_or_create_root_message(agent.id, db_session)),
        MessageType.ASSISTANT,
        [report],
    )
    answer.files = [report]
    db_session.commit()

    detail = chat_backend.get_chat_session(
        chat.id, limit=2, user=owner, db_session=db_session
    )

    assert [(file.file_id, file.message_id) for file in detail.published_files] == [
        (report["id"], answer.id)
    ]
