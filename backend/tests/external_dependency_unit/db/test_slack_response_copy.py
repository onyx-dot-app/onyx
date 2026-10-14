"""Slack imports preserve displayed answers and thinking without copying executions."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.agents.execution_records import ExecutionStatus, RunStatus
from onyx.agents.models import StepRecord, ToolExecutionRecord
from onyx.chat.chat_utils import capture_chat_history
from onyx.chat.models import ResponseRecord
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    add_chats_to_session_from_slack_thread,
    create_new_chat_message,
    get_chat_message_reasoning,
    get_chat_messages_by_session,
    get_or_create_root_message,
    update_db_session_with_messages,
)
from onyx.db.chat_response import read_response_steps, write_response_items
from onyx.db.models import ChatMessage, ChatSession
from onyx.llm.models import (
    AssistantContent,
    AssistantMessage,
    TextContent,
    ThinkingBlock,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.server.query_and_chat.session_loading import (
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    ReasoningDelta,
)


@pytest.mark.parametrize("thinking", ["Final reasoning", None])
def test_slack_copy_preserves_sdk_and_legacy_display_content(
    db_session: Session, thinking: str | None
) -> None:
    source_id, target_id = uuid4(), uuid4()
    db_session.add_all(
        [
            ChatSession(id=source_id, onyxbot_flow=True),
            ChatSession(id=target_id),
        ]
    )
    db_session.commit()
    try:
        root = get_or_create_root_message(source_id, db_session)
        question = create_new_chat_message(
            source_id, root, "Question", 1, MessageType.USER, db_session
        )
        display_answer = "Answer [[1]](https://example.com/source)"
        response = create_new_chat_message(
            source_id,
            question,
            display_answer,
            2,
            MessageType.ASSISTANT,
            db_session,
        )
        response.response_status = RunStatus.COMPLETE
        response.reasoning_tokens = "Stale duplicate thinking"
        run_id = str(response.id)
        source_answer_id = f"{run_id}:1"
        content: list[AssistantContent] = []
        if thinking:
            content.append(
                ThinkingContent(
                    text=thinking,
                    blocks=[ThinkingBlock(thinking=thinking, signature="signature")],
                )
            )
        content.append(TextContent(text="Answer [1]"))
        write_response_items(
            db_session,
            response,
            ResponseRecord(
                run_id=run_id,
                status=RunStatus.COMPLETE,
                answer_step_index=1,
                steps=[
                    StepRecord(
                        message=AssistantMessage(
                            id=f"{run_id}:0",
                            content=[
                                ThinkingContent(text="Before search"),
                                ToolCall(id="search", name="search", arguments={}),
                            ],
                        ),
                        generation_status=ExecutionStatus.COMPLETE,
                        tools={
                            "search": ToolExecutionRecord(
                                status=ExecutionStatus.COMPLETE,
                                result=ToolResultMessage(
                                    tool_call_id="search",
                                    tool_name="search",
                                    content="Search results",
                                ),
                            )
                        },
                    ),
                    StepRecord(
                        message=AssistantMessage(id=source_answer_id, content=content),
                        generation_status=ExecutionStatus.COMPLETE,
                    ),
                ],
            ),
            {},
        )
        legacy_question = create_new_chat_message(
            source_id, response, "Older question", 2, MessageType.USER, db_session
        )
        legacy_response = create_new_chat_message(
            source_id,
            legacy_question,
            "Older answer",
            2,
            MessageType.ASSISTANT,
            db_session,
            reasoning_tokens="Older thinking",
        )
        legacy_response.reasoning_tokens = "Earlier column value"
        db_session.commit()
        update_db_session_with_messages(
            db_session,
            legacy_response.id,
            source_id,
            reasoning_tokens="Updated older thinking",
            commit=True,
        )
        assert legacy_response.reasoning_tokens == "Updated older thinking"
        source_response_id = response.id
        add_chats_to_session_from_slack_thread(db_session, source_id, target_id)
        db_session.expire_all()

        messages = get_chat_messages_by_session(target_id, None, db_session)
        copied, legacy_copy = [
            message
            for message in messages
            if message.message_type == MessageType.ASSISTANT
        ]
        assert copied.id != source_response_id
        assert copied.message == display_answer
        assert copied.reasoning_tokens == (thinking or "")
        assert copied.response_status is None
        assert copied.tool_calls == []
        assert copied.response_items == []
        assert get_chat_message_reasoning(copied) == (thinking or "")

        history = capture_chat_history([copied], {}, len)
        assert len(history[0].response_messages) == 1
        assert history[0].response_messages[0].text == display_answer
        packets = translate_assistant_message_to_packets(copied, db_session)
        assert (
            "".join(
                packet.obj.content
                for packet in packets
                if isinstance(packet.obj, AgentResponseDelta)
            )
            == display_answer
        )
        assert "".join(
            packet.obj.reasoning
            for packet in packets
            if isinstance(packet.obj, ReasoningDelta)
        ) == (thinking or "")

        assert legacy_copy.message == "Older answer"
        assert get_chat_message_reasoning(legacy_copy) == "Updated older thinking"
        assert legacy_copy.response_items == []
        assert legacy_copy.response_status is None
        source = db_session.get(ChatMessage, source_response_id)
        assert source is not None
        assert source.reasoning_tokens == "Stale duplicate thinking"
        assert read_response_steps(source)[1].message.content == content
        assert (
            db_session.scalar(
                select(ChatSession.id).where(
                    ChatSession.spawned_by_message_id == copied.id
                )
            )
            is None
        )
    finally:
        db_session.rollback()
        db_session.execute(
            delete(ChatSession).where(ChatSession.id.in_([source_id, target_id]))
        )
        db_session.commit()
