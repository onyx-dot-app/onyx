"""Guards the incognito persistence seams against real Postgres and Redis.

Two behaviors the feature rests on: save_chat_turn keeps the assistant row for
tracking but writes no text when content is not persisted, and the ephemeral
store round-trips a turn's messages so the next turn has its context. Run here
rather than as unit tests because both only mean something against the real
stores.
"""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.incognito_context import (
    append_incognito_message,
    load_incognito_context,
    teardown_incognito_session,
)
from onyx.chat.models import ChatMessageSimple
from onyx.chat.save_chat import save_chat_turn
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    create_chat_session,
    get_or_create_root_message,
    reserve_message_id,
)
from onyx.db.models import ChatMessage, ChatSession, User
from onyx.tools.models import ToolCallInfo
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "incognito-persist")
    yield user
    db_session.rollback()
    db_session.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    db_session.delete(user)
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
