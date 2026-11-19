"""The chat detail route against Postgres and the shared cache."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage, ChatSession, User
from onyx.server.query_and_chat import chat_backend
from tests.external_dependency_unit.conftest import MakeTestUser


@pytest.fixture
def owner(make_test_user: MakeTestUser) -> User:
    return make_test_user("chat-session-detail")


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
