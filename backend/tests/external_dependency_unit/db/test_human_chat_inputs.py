"""Withdrawn between-step inputs cannot reappear during response persistence."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.agents.models import (
    ExecutionStatus,
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunStatus,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import create_new_chat_message, get_or_create_root_message
from onyx.db.chat_inputs import (
    inputs_available,
    list_human_messages,
    receive_messages,
    submit_human_message__no_commit,
    withdraw_human_message__no_commit,
)
from onyx.db.chat_response import read_response_input, write_response_inputs
from onyx.db.models import ChatResponseItem, ChatSession
from onyx.llm.models import AssistantMessage, TextContent
from tests.external_dependency_unit.conftest import MakeTestUser


def test_between_step_input_withdrawal_cannot_be_resurrected(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("pending-chat-input")
    conversation = ChatSession(id=uuid4(), user_id=owner.id)
    db_session.add(conversation)
    db_session.flush()
    root = get_or_create_root_message(conversation.id, db_session)
    question = create_new_chat_message(
        conversation.id, root, "Question", 1, MessageType.USER, db_session, commit=False
    )
    response = create_new_chat_message(
        conversation.id,
        question,
        "",
        0,
        MessageType.ASSISTANT,
        db_session,
        commit=False,
    )
    response.response_status = RunStatus.RUNNING
    db_session.flush()
    assert conversation.user_id is not None
    pending = submit_human_message__no_commit(
        db_session,
        conversation.id,
        conversation.user_id,
        message="Focus on latency",
        delivery=MessageDelivery.SEND,
        target_response_id=response.id,
    )
    messages = receive_messages(db_session, str(conversation.id), str(response.id), [])
    assert len(messages) == 1
    assert messages[0].metadata == InputMessageMetadata(
        source=InputSource.HUMAN,
        source_run_id=str(response.id),
    )
    assert (
        withdraw_human_message__no_commit(
            db_session, conversation.id, conversation.user_id, pending.id
        )
        == pending
    )
    db_session.flush()
    assert not inputs_available(
        db_session, response.id, messages, ownership_version=None
    )
    item = ChatResponseItem(
        id=f"{response.id}:0",
        chat_message_id=response.id,
        step_index=0,
        message=AssistantMessage(content=[TextContent(text="Answer")]),
        generation_status=ExecutionStatus.COMPLETE,
    )
    with pytest.raises(ValueError, match="no longer pending"):
        write_response_inputs(db_session, response, item, messages)
    replacement = submit_human_message__no_commit(
        db_session,
        conversation.id,
        conversation.user_id,
        message="Focus on cost",
        delivery=MessageDelivery.SEND,
        target_response_id=response.id,
    )
    messages = receive_messages(db_session, str(conversation.id), str(response.id), [])
    assert inputs_available(db_session, response.id, messages, ownership_version=None)
    write_response_inputs(db_session, response, item, messages)
    db_session.add(item)
    db_session.commit()
    assert (
        withdraw_human_message__no_commit(
            db_session, conversation.id, conversation.user_id, replacement.id
        )
        is None
    )
    db_session.expire_all()
    loaded = db_session.get(ChatResponseItem, item.id)
    assert loaded is not None
    assert [read_response_input(row) for row in loaded.inputs] == messages
    assert list_human_messages(db_session, conversation.id, conversation.user_id) == []
