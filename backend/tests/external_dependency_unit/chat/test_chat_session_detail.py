"""The chat detail route against Postgres and the shared cache."""

import time
from collections.abc import Generator, Sequence
from datetime import datetime, timedelta, timezone
from itertools import count
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import String, cast, select, text, update
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.configs.constants import (
    CHAT_SESSION_ID_FILE_METADATA_KEY,
    DEFAULT_PERSONA_ID,
    FileOrigin,
    MessageType,
)
from onyx.db.chat import (
    create_new_chat_message,
    delete_unpublished_chat_artifacts,
    get_or_create_root_message,
    save_chat_artifact,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import (
    ChatArtifact,
    ChatArtifactVersion,
    ChatMessage,
    ChatSession,
    ChatSessionSharedStatus,
    FileRecord,
    User,
)
from onyx.file_store.file_store import (
    FILE_SIZE_MISSING_SENTINEL,
    FileStore,
    get_default_file_store,
)
from onyx.file_store.utils import save_chat_output_file
from onyx.server.features.build.sandbox.models import session_workspace
from onyx.server.query_and_chat import chat_backend
from onyx.tools.tool_implementations.sandbox.models import PublishedFile
from onyx.utils.threadpool_concurrency import (
    TimeoutThread,
    run_in_background,
    wait_on_background,
)
from tests.external_dependency_unit.conftest import MakeTestUser


@pytest.fixture
def owner(
    make_test_user: MakeTestUser, db_session: Session
) -> Generator[User, None, None]:
    """A test user. Teardown deletes the files of its chats."""
    user = make_test_user("chat-session-detail")
    yield user
    db_session.rollback()
    chat_ids = select(ChatSession.id).where(ChatSession.user_id == user.id)
    file_ids = db_session.scalars(
        select(FileRecord.file_id)
        .where(
            FileRecord.file_metadata[CHAT_SESSION_ID_FILE_METADATA_KEY].astext.in_(
                select(cast(ChatSession.id, String)).where(
                    ChatSession.user_id == user.id
                )
            )
        )
        .union(
            select(ChatArtifactVersion.file_id)
            .join(ChatArtifact, ChatArtifact.id == ChatArtifactVersion.artifact_id)
            .where(ChatArtifact.chat_session_id.in_(chat_ids))
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
) -> PublishedFile:
    """A file that `publish_files` saved for the chat, as the next publish.
    Subagents share the root chat's sandbox turn, so their files belong to the
    root chat too."""
    name = path.rsplit("/", 1)[-1]
    file = save_chat_artifact(
        name.encode(),
        name=name,
        mime_type="text/markdown",
        chat_session_id=chat.id,
        path=path,
        title=title,
        thumbnail=None,
    )
    published_at = _PUBLISHED_AT + timedelta(seconds=next(_PUBLISH_ORDER))
    if file.version == 1:
        db_session.execute(
            update(ChatArtifact)
            .where(ChatArtifact.id == file.artifact_id)
            .values(created_at=published_at)
        )
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == file.file_id)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL if missing else len(name))
    )
    db_session.commit()
    return file


@pytest.mark.usefixtures("initialize_file_store")
def test_the_latest_page_lists_the_latest_version_of_each_artifact(
    db_session: Session, owner: User
) -> None:
    """The list holds the latest version of each of the chat's artifacts,
    its subagents' files included, by the artifact's first publish, with the
    path and the version's title. It leaves out another chat's files, files
    that are not published files, and versions whose object is missing: an
    artifact whose latest version is missing lists the version before it."""
    chat = _new_chat(db_session, owner)
    other_chat = _new_chat(db_session, owner)
    question = _add(
        db_session, get_or_create_root_message(chat.id, db_session), MessageType.USER
    )
    _add(db_session, question, MessageType.ASSISTANT)

    report = f"{session_workspace(chat.id)}/drafts/report.md"
    draft = _publish(db_session, chat, report, "Draft")
    notes = _publish(db_session, chat, "/w/notes.md")
    _publish(db_session, other_chat, "/w/other.md")
    save_chat_output_file(
        b"png",
        display_name="image.png",
        file_type="image/png",
        chat_session_id=chat.id,
    )
    _publish(db_session, chat, "/w/chart.md", missing=True)
    final = _publish(db_session, chat, report, "Final")
    _publish(db_session, chat, "/w/notes.md", "Newest notes", missing=True)

    detail = chat_backend.get_chat_session(
        chat.id, limit=1, user=owner, db_session=db_session
    )

    assert (final.artifact_id, final.version) == (draft.artifact_id, 2)
    assert detail.published_files is not None
    assert [
        (
            file.file_id,
            file.artifact_id,
            file.version,
            file.path,
            file.display_path,
            file.title,
            file.name,
            file.size,
        )
        for file in detail.published_files
    ] == [
        (
            final.file_id,
            draft.artifact_id,
            2,
            report,
            "drafts/report.md",
            "Final",
            "report.md",
            len("report.md"),
        ),
        (
            notes.file_id,
            notes.artifact_id,
            1,
            "/w/notes.md",
            "/w/notes.md",
            None,
            "notes.md",
            len("notes.md"),
        ),
    ]


@pytest.mark.usefixtures("initialize_file_store")
def test_concurrent_publishes_of_one_path_number_their_versions_without_gaps(
    db_session: Session, owner: User
) -> None:
    """Publishes of one new path that all start at once number their versions
    1 to N on one artifact: the artifact's row lock makes them take turns."""
    publish_count = 6
    chat = _new_chat(db_session, owner)
    publishes: list[TimeoutThread[PublishedFile]] = []
    try:
        with get_session_with_current_tenant() as holder:
            # Lets the publishes start but holds every version insert
            holder.execute(text("LOCK TABLE chat_artifact_version IN EXCLUSIVE MODE"))
            # Each publish joins the list as it starts
            publishes.extend(
                run_in_background(
                    save_chat_artifact,
                    b"a",
                    name="a.md",
                    mime_type="text/markdown",
                    chat_session_id=chat.id,
                    path="/w/a.md",
                    title=None,
                    thumbnail=None,
                )
                for _ in range(publish_count)
            )
            # Every publish waits on a lock before the holder lets them go. A
            # transaction reads one snapshot of pg_stat_activity, so each probe
            # ends its own.
            deadline = time.monotonic() + 30
            while True:
                waiting = db_session.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE wait_event_type = 'Lock' "
                        "AND query ILIKE '%chat_artifact%'"
                    )
                )
                db_session.rollback()
                if (waiting or 0) >= publish_count:
                    break
                assert time.monotonic() < deadline
                time.sleep(0.05)  # test-flakes: allow a poll with a deadline
            holder.rollback()
    finally:
        # Closing the holder releases the lock, so every publish ends, also
        # when a probe fails
        for publish in publishes:
            publish.join()
    published = [wait_on_background(publish) for publish in publishes]

    assert sorted(file.version or 0 for file in published) == list(
        range(1, publish_count + 1)
    )
    assert len({file.artifact_id for file in published}) == 1


@pytest.mark.usefixtures("initialize_file_store")
def test_a_failed_publish_leaves_no_empty_artifact(
    db_session: Session, owner: User
) -> None:
    """The clean-up of a failed publish deletes its files and the artifacts
    that they leave without a version. An artifact with an earlier version
    keeps it, so the next publish numbers on from that version."""
    chat = _new_chat(db_session, owner)
    kept = _publish(db_session, chat, "/w/kept.md")
    failed = [
        _publish(db_session, chat, "/w/kept.md"),
        _publish(db_session, chat, "/w/new.md"),
    ]

    delete_unpublished_chat_artifacts(failed)

    db_session.expire_all()
    assert (
        db_session.scalars(
            select(FileRecord.file_id).where(
                FileRecord.file_id.in_([file.file_id for file in failed])
            )
        ).all()
        == []
    )
    assert db_session.scalars(
        select(ChatArtifact.path).where(ChatArtifact.chat_session_id == chat.id)
    ).all() == ["/w/kept.md"]
    again = _publish(db_session, chat, "/w/kept.md")
    assert (again.artifact_id, again.version) == (kept.artifact_id, 2)
    new = _publish(db_session, chat, "/w/new.md")
    assert new.version == 1
    assert new.artifact_id != failed[1].artifact_id


def _failing_save(monkeypatch: pytest.MonkeyPatch, origin: FileOrigin) -> None:
    """Make the file store's saves of `origin` fail."""
    store_type = type(get_default_file_store())
    save_file = store_type.save_file

    def save(self: FileStore, *args: Any, **kwargs: Any) -> str:
        if kwargs.get("file_origin") is origin:
            raise RuntimeError("the file store is down")
        return save_file(self, *args, **kwargs)

    monkeypatch.setattr(store_type, "save_file", save)


def _thumbnail_ids(db_session: Session, name: str) -> list[str]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(FileRecord.file_id).where(
                FileRecord.file_origin == FileOrigin.CHAT_ARTIFACT_THUMBNAIL,
                FileRecord.display_name == f"{name} thumbnail",
            )
        )
    )


@pytest.mark.usefixtures("initialize_file_store")
def test_a_thumbnail_goes_when_its_file_fails_to_save(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, owner: User
) -> None:
    chat = _new_chat(db_session, owner)
    name = f"{uuid4().hex}.pdf"
    _failing_save(monkeypatch, FileOrigin.CHAT_ARTIFACT)

    with pytest.raises(RuntimeError, match="the file store is down"):
        save_chat_artifact(
            b"%PDF",
            name=name,
            mime_type="application/pdf",
            chat_session_id=chat.id,
            path=f"/w/{name}",
            title=None,
            thumbnail=b"jpeg",
        )

    assert _thumbnail_ids(db_session, name) == []
    assert (
        db_session.scalars(
            select(ChatArtifact.id).where(ChatArtifact.chat_session_id == chat.id)
        ).all()
        == []
    )


@pytest.mark.usefixtures("initialize_file_store")
def test_a_file_publishes_without_a_thumbnail_that_fails_to_save(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, owner: User
) -> None:
    chat = _new_chat(db_session, owner)
    name = f"{uuid4().hex}.pdf"
    _failing_save(monkeypatch, FileOrigin.CHAT_ARTIFACT_THUMBNAIL)

    file = save_chat_artifact(
        b"%PDF",
        name=name,
        mime_type="application/pdf",
        chat_session_id=chat.id,
        path=f"/w/{name}",
        title=None,
        thumbnail=b"jpeg",
    )

    assert (file.version, file.thumbnail_file_id) == (1, None)
    assert get_default_file_store().read_file(file.file_id).read() == b"%PDF"
    assert _thumbnail_ids(db_session, name) == []


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
