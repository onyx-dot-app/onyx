from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.agents.models import InputSource, MessageDelivery
from onyx.configs.constants import MessageType
from onyx.db.models import ChatInput, ChatMessage, ChatSession, ToolCall
from tests.external_dependency_unit.conftest import MakeTestUser


@pytest.mark.parametrize("source", [InputSource.HUMAN, InputSource.AGENT])
def test_source_check_rejects_rows_with_null_required_fields(
    db_session: Session, make_test_user: MakeTestUser, source: InputSource
) -> None:
    owner = make_test_user("chat-input-constraint")
    conversation = ChatSession(id=uuid4(), user_id=owner.id)
    db_session.add(conversation)
    db_session.flush()
    if source == InputSource.HUMAN:
        row = ChatInput(
            recipient_session_id=conversation.id,
            message_id=str(uuid4()),
            source=source,
            delivery=None,
            content="No delivery",
        )
    else:
        response = ChatMessage(
            chat_session_id=conversation.id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        db_session.add(response)
        db_session.flush()
        tool_call = ToolCall(
            chat_session_id=conversation.id,
            parent_chat_message_id=response.id,
            turn_number=0,
            tool_call_id="send",
            tool_call_arguments={},
            tool_call_tokens=0,
        )
        db_session.add(tool_call)
        db_session.flush()
        # Every other agent field is valid, so only the missing step limit fails.
        row = ChatInput(
            recipient_session_id=conversation.id,
            message_id=str(uuid4()),
            source=source,
            delivery=MessageDelivery.QUEUE,
            invoking_tool_call_id=tool_call.id,
            root_response_id=response.id,
            max_steps=None,
            content="No step limit",
        )
    db_session.add(row)
    with pytest.raises(IntegrityError, match="ck_chat_input_source"):
        db_session.flush()
    db_session.rollback()
