"""Guards the incognito persistence seams against real Postgres and Redis.

Two behaviors the feature rests on: save_chat_turn keeps the assistant row for
tracking but writes no text when content is not persisted, and the ephemeral
store round-trips a turn's messages so the next turn has its context. Run here
rather than as unit tests because both only mean something against the real
stores.
"""

from collections.abc import Generator
from io import BytesIO
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.incognito import delete_incognito_generated_files
from onyx.chat.incognito_context import (
    append_incognito_message,
    load_incognito_context,
    teardown_incognito_session,
)
from onyx.chat.models import ChatMessageSimple
from onyx.chat.save_chat import save_chat_turn
from onyx.configs.constants import DocumentSource, FileOrigin, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    create_chat_session,
    get_or_create_root_message,
    reserve_message_id,
)
from onyx.db.file_record import (
    FileRecordNotFoundError,
    get_incognito_file_ids,
    get_session_ids_with_incognito_files,
)
from onyx.db.models import ChatMessage, ChatSession, User
from onyx.file_store.file_store import get_default_file_store
from onyx.redis.redis_pool import get_redis_client
from onyx.tools.models import ToolCallInfo
from shared_configs.contextvars import CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "incognito-persist")
    yield user
    db_session.rollback()
    db_session.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    delete_test_user(db_session, user)
    db_session.commit()


def _new_session(db_session: Session, user_id: UUID) -> ChatSession:
    return create_chat_session(
        db_session=db_session,
        description="incognito",
        user_id=user_id,
        persona_id=None,
    )


def _reserve_assistant(db_session: Session, session_id: UUID) -> ChatMessage:
    root = get_or_create_root_message(chat_session_id=session_id, db_session=db_session)
    return reserve_message_id(
        db_session=db_session,
        chat_session_id=session_id,
        parent_message=root.id,
    )


def _search_doc(document_id: str) -> SearchDoc:
    return SearchDoc(
        document_id=document_id,
        chunk_ind=0,
        semantic_identifier="secret doc",
        blurb="confidential excerpt",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=["<hi>confidential</hi>"],
    )


def test_save_chat_turn_keeps_the_row_but_writes_no_text(
    db_session: Session, owner: User
) -> None:
    session = _new_session(db_session, owner.id)
    assistant = _reserve_assistant(db_session, session.id)

    doc = _search_doc("secret-doc-1")
    save_chat_turn(
        message_text="the acquisition target is confidential",
        reasoning_tokens="secret reasoning",
        tool_calls=[
            ToolCallInfo(
                parent_tool_call_id=None,
                turn_index=0,
                tab_index=0,
                tool_name="run_search",
                tool_call_id="call-1",
                tool_id=1,
                reasoning_tokens=None,
                tool_call_arguments={"query": "the confidential query"},
                tool_call_response="retrieved excerpt text",
                search_docs=[doc],
            )
        ],
        citation_to_doc={1: doc},
        all_search_docs={doc.document_id: doc},
        db_session=db_session,
        assistant_message=assistant,
        emitted_citations={1},
        persist_content=False,
    )
    db_session.commit()

    stored = db_session.get(ChatMessage, assistant.id)
    assert stored is not None
    # Row survives for tracking, with a real token count, but no text.
    assert stored.message == ""
    assert stored.reasoning_tokens is None
    assert stored.token_count > 0
    # Conversation-derived artifacts stay out too: no tool calls, no search
    # docs, no citations for a content-free turn.
    assert not stored.tool_calls
    assert not stored.search_docs
    assert not stored.citations


def test_save_chat_turn_persists_text_by_default(
    db_session: Session, owner: User
) -> None:
    session = _new_session(db_session, owner.id)
    assistant = _reserve_assistant(db_session, session.id)

    save_chat_turn(
        message_text="an ordinary answer",
        reasoning_tokens=None,
        tool_calls=[],
        citation_to_doc={},
        all_search_docs={},
        db_session=db_session,
        assistant_message=assistant,
    )
    db_session.commit()

    stored = db_session.get(ChatMessage, assistant.id)
    assert stored is not None
    assert stored.message == "an ordinary answer"


def test_turn_round_trips_through_the_store() -> None:
    """A turn appends the user message then the answer. The next turn loads both
    in order so the model sees its own context."""
    session_id = uuid4()
    try:
        append_incognito_message(
            session_id,
            ChatMessageSimple(
                message="what is our runway",
                token_count=4,
                message_type=MessageType.USER,
            ),
        )
        append_incognito_message(
            session_id,
            ChatMessageSimple(
                message="eighteen months",
                token_count=2,
                message_type=MessageType.ASSISTANT,
            ),
        )

        history = load_incognito_context(session_id).messages
        assert [(m.message_type, m.message) for m in history] == [
            (MessageType.USER, "what is our runway"),
            (MessageType.ASSISTANT, "eighteen months"),
        ]
    finally:
        teardown_incognito_session(session_id)


def test_teardown_ends_the_session_immediately() -> None:
    session_id = uuid4()
    append_incognito_message(
        session_id,
        ChatMessageSimple(
            message="secret", token_count=1, message_type=MessageType.USER
        ),
    )
    assert load_incognito_context(session_id).messages

    teardown_incognito_session(session_id)

    assert load_incognito_context(session_id).messages == []


def test_teardown_clears_buffered_stream_chunks() -> None:
    """The stream buffer holds the streamed answer NDJSON, so teardown must
    delete it with the context instead of leaving it to the TTL."""
    session_id = uuid4()
    client = get_redis_client()
    chunk_key = f"chatstream_{session_id}_1:0"
    client.set(chunk_key, b"buffered answer text", ex=600)
    assert client.get(chunk_key) is not None

    teardown_incognito_session(session_id)

    assert client.get(chunk_key) is None


def _content_free_blob(session_id: UUID) -> str:
    """Save a blob the way a tool does inside a content-free turn."""
    token = CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.set(str(session_id))
    try:
        return get_default_file_store().save_file(
            content=BytesIO(b"generated chart bytes"),
            display_name="chart.png",
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type="image/png",
        )
    finally:
        CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.reset(token)


def test_a_blob_is_stamped_when_it_is_saved(db_session: Session) -> None:
    """The stamp lands with the record, so no window exists where a blob is
    durable but unfindable."""
    session_id = uuid4()
    file_id = _content_free_blob(session_id)

    assert get_incognito_file_ids(str(session_id), db_session) == [file_id]


def test_teardown_deletes_the_stamped_blobs(db_session: Session) -> None:
    session_id = uuid4()
    file_id = _content_free_blob(session_id)
    file_store = get_default_file_store()

    assert delete_incognito_generated_files(session_id, db_session)

    with pytest.raises(FileRecordNotFoundError):
        file_store.read_file(file_id)
    assert get_incognito_file_ids(str(session_id), db_session) == []


def test_a_refused_deletion_keeps_the_stamp(db_session: Session) -> None:
    """A store outage must leave the blob findable for the sweep."""
    session_id = uuid4()
    file_id = _content_free_blob(session_id)
    file_store = get_default_file_store()

    with patch.object(
        type(file_store), "delete_file", side_effect=RuntimeError("store blip")
    ):
        assert not delete_incognito_generated_files(session_id, db_session)

    assert get_incognito_file_ids(str(session_id), db_session) == [file_id]
    assert str(session_id) in get_session_ids_with_incognito_files(db_session)

    assert delete_incognito_generated_files(session_id, db_session)
    with pytest.raises(FileRecordNotFoundError):
        file_store.read_file(file_id)
