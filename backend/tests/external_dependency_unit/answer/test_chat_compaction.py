"""Compacted chats retain history and resume from the selected conversation branch."""

from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.compaction import count_tokens
from onyx.agents.models import RunStatus
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import FileOrigin, MessageType
from onyx.db.chat import delete_chat_session
from onyx.db.enums import UserFileStatus
from onyx.db.models import ChatMessage, UserFile
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.file_store.utils import plaintext_file_name_for_id
from onyx.llm.model_response import Delta
from onyx.llm.models import AssistantMessage, TextContent
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.server.query_and_chat.session_loading import (
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    StreamingError,
)
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
    final_answer,
    submit_query,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.unit.onyx.agents.fakes import ScriptedLLM


@pytest.mark.usefixtures("mock_external_deps", "initialize_file_store")
@pytest.mark.parametrize("scenario", ["summary", "summary_failure", "oversized"])
def test_chat_compaction_preserves_current_files_and_compacts_them_after_answering(
    db_session: Session, scenario: str
) -> None:
    user = create_test_user(db_session, "attachment-compaction")
    session = create_chat_session(db_session, user)
    file_store = get_default_file_store()
    files: list[UserFile] = []
    bodies = [
        f"Report {index} contains unique supporting evidence. "
        * (5000 if scenario == "oversized" else 600)
        for index in range(2)
    ]
    model = ScriptedLLM(
        [
            Delta(content="Earlier answer"),
            Delta(content="Reports compared"),
            Delta(content="Follow-up answer"),
        ],
        max_input_tokens=128000,
    )
    try:
        descriptors: list[FileDescriptor] = []
        for index, body in enumerate(bodies):
            filename = f"report-{index}.txt"
            file_id = file_store.save_file(
                content=BytesIO(body.encode()),
                display_name=filename,
                file_origin=FileOrigin.CHAT_UPLOAD,
                file_type="text/plain",
            )
            file = UserFile(
                id=uuid4(),
                user_id=user.id,
                file_id=file_id,
                name=filename,
                file_type="text/plain",
                token_count=count_tokens(body),
                status=UserFileStatus.COMPLETED,
            )
            files.append(file)
            db_session.add(file)
            descriptors.append(
                {
                    "id": file_id,
                    "user_file_id": str(file.id),
                    "name": filename,
                    "type": ChatFileType.PLAIN_TEXT,
                }
            )
        db_session.commit()
        with (
            patch("onyx.chat.process_message.get_llm_for_persona", return_value=model),
            patch.object(
                model,
                "invoke",
                side_effect=RuntimeError("Summary unavailable")
                if scenario == "summary_failure"
                else None,
                return_value=AssistantMessage(
                    content=[
                        TextContent(text="Earlier evidence and report comparison.")
                    ]
                ),
            ) as summarize,
        ):
            assert (
                final_answer(
                    list(submit_query("Old context. " * 10000, session.id, user))
                )
                == "Earlier answer"
            )
            model.max_input_tokens = 12000
            parts = list(
                handle_stream_message_objects(
                    new_msg_req=SendMessageRequest(
                        chat_session_id=session.id,
                        message="Compare the reports.",
                        file_descriptors=descriptors,
                        additional_context="Include supporting evidence.",
                    ),
                    user=user,
                )
            )
            if scenario == "oversized":
                assert any(isinstance(part, StreamingError) for part in parts)
                assert len(model.requests) == 1
            else:
                assert final_answer(parts) == "Reports compared"
                summarize.assert_called()
                current_prompt = "\n".join(
                    message.model_dump_json() for message in model.requests[1]["prompt"]
                )
                for body in bodies:
                    assert body in current_prompt
                assert "Include supporting evidence." in current_prompt

                model.max_input_tokens = 6000
                assert (
                    final_answer(
                        list(submit_query("Continue the comparison.", session.id, user))
                    )
                    == "Follow-up answer"
                )
                followup_prompt = "\n".join(
                    message.model_dump_json() for message in model.requests[2]["prompt"]
                )
                for body in bodies:
                    assert body not in followup_prompt
        db_session.expire_all()
        question = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == session.id,
                ChatMessage.message == "Compare the reports.",
            )
        )
        assert question is not None and question.files == descriptors
        for file, body in zip(files, bodies, strict=True):
            with file_store.read_file(file.file_id, mode="b") as content:
                assert content.read() == body.encode()
    finally:
        db_session.rollback()
        delete_chat_session(user.id, session.id, db_session, hard_delete=True)
        for file in files:
            file_store.delete_file(file.file_id)
            file_store.delete_file(
                plaintext_file_name_for_id(str(file.id)), error_on_missing=False
            )
            db_session.delete(file)
        delete_test_user(db_session, user)
        db_session.commit()


@pytest.mark.usefixtures("mock_external_deps")
@pytest.mark.parametrize("summary_fails", [False, True])
def test_shorter_question_recovers_after_oversized_input(
    db_session: Session, summary_fails: bool
) -> None:
    user = create_test_user(db_session, "oversized-chat")
    session = create_chat_session(db_session, user)
    oversized = "Oversized input. " * 10000
    model = ScriptedLLM([Delta(content="Hello")], max_input_tokens=8000)
    try:
        with (
            patch("onyx.chat.process_message.get_llm_for_persona", return_value=model),
            patch.object(
                model,
                "invoke",
                side_effect=RuntimeError("Summary unavailable")
                if summary_fails
                else None,
                return_value=AssistantMessage(
                    content=[
                        TextContent(
                            text="An earlier question exceeded the context limit."
                        )
                    ]
                ),
            ) as summarize,
        ):
            failed = list(submit_query(oversized, session.id, user))
            assert any(isinstance(part, StreamingError) for part in failed)
            assert not model.requests

            # A separate chat request rebuilds its agent from saved history.
            recovered = list(submit_query("Say hello", session.id, user))
            assert final_answer(recovered) == "Hello"
            summarize.assert_called()
            assert len(model.requests) == 1
            prompt = "\n".join(
                message.model_dump_json() for message in model.requests[0]["prompt"]
            )
            assert "Say hello" in prompt
            assert oversized not in prompt

        db_session.expire_all()
        messages = list(
            db_session.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_session_id == session.id)
                .order_by(ChatMessage.id)
            )
        )
        assert [
            message.message
            for message in messages
            if message.message_type == MessageType.USER
        ] == [oversized, "Say hello"]
        assert [
            message.response_status
            for message in messages
            if message.message_type == MessageType.ASSISTANT
        ] == [RunStatus.ERROR, RunStatus.COMPLETE]
    finally:
        db_session.rollback()
        delete_chat_session(user.id, session.id, db_session, hard_delete=True)
        delete_test_user(db_session, user)
        db_session.commit()


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
            patch("onyx.chat.process_message.get_llm_for_persona", return_value=model),
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
