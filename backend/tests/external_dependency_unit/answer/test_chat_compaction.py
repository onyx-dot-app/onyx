"""Compacted chats retain history and resume from the selected conversation branch."""

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import MessageType
from onyx.db.chat import delete_chat_session
from onyx.db.models import ChatMessage
from onyx.llm.model_response import Delta
from onyx.llm.models import AssistantMessage, TextContent
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.server.query_and_chat.session_loading import (
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
    final_answer,
    submit_query,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.unit.onyx.agents.fakes import ScriptedLLM


@pytest.mark.usefixtures("full_deployment_setup", "mock_external_deps")
def test_compacted_chat_reloads_continues_and_regenerates_selected_branch(
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "compacted-chat")
    session = create_chat_session(db_session, user)
    original_input = "The project is called Kiwi. " + "historical detail " * 10000
    summary = "The original background establishes that the project is called Kiwi."
    model = ScriptedLLM(
        [
            Delta(content="Original answer"),
            Delta(content="Answer after compaction"),
            Delta(content="Later branch answer"),
            Delta(content="Regenerated answer"),
        ],
        max_input_tokens=128000,
    )
    try:
        with (
            patch("onyx.chat.prepare.get_llm_for_persona", return_value=model),
            patch.object(
                model,
                "invoke",
                return_value=AssistantMessage(content=[TextContent(text=summary)]),
            ) as summarize,
        ):
            assert (
                final_answer(list(submit_query(original_input, session.id, user)))
                == "Original answer"
            )
            assert summarize.call_count == 0

            model.max_input_tokens = 8000
            compacted = list(
                submit_query("What is the project called?", session.id, user)
            )
            assert final_answer(compacted) == "Answer after compaction"
            assert summarize.call_count > 0
            summary_calls = summarize.call_count
            ids = next(
                part for part in compacted if isinstance(part, MessageResponseIDInfo)
            )
            assert ids.user_message_id is not None
            db_session.expire_all()
            summaries = list(
                db_session.scalars(
                    select(ChatMessage).where(
                        ChatMessage.chat_session_id == session.id,
                        ChatMessage.message_type == MessageType.SUMMARY,
                    )
                )
            )
            assert len(summaries) == 1
            assert summaries[0].message == summary
            assert summaries[0].last_summarized_message_id is not None
            original_row = db_session.scalar(
                select(ChatMessage)
                .where(
                    ChatMessage.chat_session_id == session.id,
                    ChatMessage.message_type == MessageType.USER,
                )
                .order_by(ChatMessage.id)
            )
            assert original_row is not None and original_row.message == original_input
            saved = db_session.get(ChatMessage, ids.reserved_assistant_message_id)
            assert saved is not None
            replayed = translate_assistant_message_to_packets(saved, db_session)
            assert (
                "".join(
                    packet.obj.content
                    for packet in replayed
                    if isinstance(packet.obj, AgentResponseDelta)
                )
                == "Answer after compaction"
            )

            assert (
                final_answer(
                    list(submit_query("Continue with the budget", session.id, user))
                )
                == "Later branch answer"
            )
            assert summarize.call_count == summary_calls
            regeneration = list(
                handle_stream_message_objects(
                    new_msg_req=SendMessageRequest(
                        chat_session_id=session.id,
                        parent_message_id=ids.user_message_id,
                        message="Ignored during regeneration",
                    ),
                    user=user,
                )
            )
            assert final_answer(regeneration) == "Regenerated answer"
            for request in model.requests[1:]:
                prompt = "\n".join(
                    message.model_dump_json() for message in request["prompt"]
                )
                assert summary in prompt
                assert "historical detail" not in prompt
            continued_prompt = "\n".join(
                message.model_dump_json() for message in model.requests[2]["prompt"]
            )
            assert "Answer after compaction" in continued_prompt
            regenerated_prompt = "\n".join(
                message.model_dump_json() for message in model.requests[3]["prompt"]
            )
            assert "What is the project called?" in regenerated_prompt
            assert "Later branch answer" not in regenerated_prompt
            assert "Continue with the budget" not in regenerated_prompt
            assert "Answer after compaction" not in regenerated_prompt
    finally:
        db_session.rollback()
        delete_chat_session(user.id, session.id, db_session, hard_delete=True)
        delete_test_user(db_session, user)
        db_session.commit()
