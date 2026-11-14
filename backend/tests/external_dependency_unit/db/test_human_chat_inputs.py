"""Pending human input is session-scoped and is accepted at most once."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.agents.models import (
    MessageDelivery,
    RunStatus,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    create_chat_history_chain,
    create_new_chat_message,
    get_or_create_root_message,
    reserve_chat_response_ids,
)
from onyx.db.chat_inputs import (
    list_human_messages,
    submit_human_message__no_commit,
)
from onyx.db.models import ChatSession
from tests.external_dependency_unit.conftest import MakeTestUser


def test_follow_up_question_keeps_history_and_pending_messages(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("agent-results-question")
    conversation = ChatSession(id=uuid4(), user_id=owner.id)
    db_session.add(conversation)
    db_session.flush()
    root = get_or_create_root_message(conversation.id, db_session)
    question = create_new_chat_message(
        conversation.id,
        root,
        "Research this",
        2,
        MessageType.USER,
        db_session,
        commit=False,
    )
    response = create_new_chat_message(
        conversation.id,
        question,
        "Research is running",
        3,
        MessageType.ASSISTANT,
        db_session,
        commit=False,
    )
    response.response_status = RunStatus.COMPLETE
    db_session.flush()
    pending = submit_human_message__no_commit(
        db_session,
        conversation.id,
        message="Then compare the results",
        delivery=MessageDelivery.QUEUE,
        target_response_id=response.id,
        turn_preparing=False,
        mentions=[],
    )
    results = create_new_chat_message(
        conversation.id,
        response,
        "",
        0,
        MessageType.AGENT_RESULTS,
        db_session,
        commit=False,
    )
    follow_up_ids = reserve_chat_response_ids(
        db_session, conversation.id, results.id, ["Test model"]
    )
    db_session.expire_all()
    history = create_chat_history_chain(conversation.id, db_session)
    assert [message.id for message in history] == [
        question.id,
        response.id,
        results.id,
        follow_up_ids[0],
    ]
    assert [message.message_type for message in history] == [
        MessageType.USER,
        MessageType.ASSISTANT,
        MessageType.AGENT_RESULTS,
        MessageType.ASSISTANT,
    ]
    # Queued input belongs to the session, not to a response.
    assert list_human_messages(db_session, conversation.id) == [pending]
    assert pending.target_response_id is None

    reserve_chat_response_ids(
        db_session, conversation.id, follow_up_ids[0], ["Test model"]
    )
    db_session.expire_all()
    with pytest.raises(RuntimeError, match="two assistant messages"):
        create_chat_history_chain(conversation.id, db_session)
