"""Chat history retains inputs across compaction, reload, and regeneration."""

from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from docx import Document
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.compaction import count_tokens
from onyx.agents.models import RunStatus
from onyx.chat.files import _get_or_extract_plaintext
from onyx.chat.incognito_context import teardown_incognito_session
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import FileOrigin, MessageType
from onyx.db.chat import delete_chat_session
from onyx.db.enums import IncognitoRecordMode, UserFileStatus
from onyx.db.models import ChatMessage, ChatResponseItem, UserFile
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.file_store.utils import plaintext_file_name_for_id
from onyx.llm.interfaces import LLMConfig
from onyx.llm.model_response import Delta
from onyx.llm.models import AssistantMessage, ImageContentPart, TextContent
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.server.query_and_chat.session_loading import (
    load_session_tools,
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
@pytest.mark.parametrize("failure", ["startup", "temporary_save"])
def test_usage_only_followup_after_unsaved_response(
    db_session: Session, failure: str
) -> None:
    user = create_test_user(db_session, "private-save-failure")
    session = create_chat_session(db_session, user)
    session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    db_session.commit()
    model = ScriptedLLM(
        [
            Delta(content="Retained answer"),
            *([Delta(content="Unsaved answer")] if failure == "temporary_save" else []),
            Delta(content="Follow-up answer"),
            Delta(content="Continued answer"),
        ],
        max_input_tokens=128000,
    )
    try:
        with patch("onyx.chat.process_message.get_llm_for_persona", return_value=model):
            assert (
                final_answer(list(submit_query("Retained question", session.id, user)))
                == "Retained answer"
            )
            failing_boundary = (
                "onyx.chat.execution.ChatTurnExecution"
                if failure == "startup"
                else "onyx.chat.history_store.save_incognito_response"
            )
            with patch(failing_boundary, side_effect=RuntimeError("Unavailable")):
                failed = list(submit_query("Failed turn question", session.id, user))
            assert any(isinstance(part, StreamingError) for part in failed)
            db_session.expire_all()
            failed_row = db_session.scalar(
                select(ChatMessage)
                .where(
                    ChatMessage.chat_session_id == session.id,
                    ChatMessage.message_type == MessageType.ASSISTANT,
                )
                .order_by(ChatMessage.id.desc())
                .limit(1)
            )
            assert failed_row is not None
            assert failed_row.response_status == (
                None if failure == "startup" else RunStatus.COMPLETE
            )
            assert (
                final_answer(
                    list(submit_query("Continue after failure", session.id, user))
                )
                == "Follow-up answer"
            )
            prompt = "\n".join(
                message.model_dump_json() for message in model.requests[-1]["prompt"]
            )
            assert "Retained question" in prompt
            assert "Retained answer" in prompt
            assert "Failed turn question" in prompt
            assert "Unsaved answer" not in prompt
            assert (
                final_answer(list(submit_query("Continue again", session.id, user)))
                == "Continued answer"
            )
    finally:
        teardown_incognito_session(session.id)
        delete_chat_session(user.id, session.id, db_session, hard_delete=True)
        delete_test_user(db_session, user)
        db_session.commit()


@pytest.mark.usefixtures("mock_external_deps", "initialize_file_store")
@pytest.mark.parametrize("branch", ["regenerate", "edit_root", "edit_followup"])
def test_usage_only_attachments_follow_the_selected_branch(
    db_session: Session,
    branch: str,
) -> None:
    class VisionLLM(ScriptedLLM):
        @property
        def config(self) -> LLMConfig:
            return super().config.model_copy(update={"supports_images": True})

    user = create_test_user(db_session, "private-attachments")
    session = create_chat_session(db_session, user)
    session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    db_session.commit()
    file_store = get_default_file_store()
    body = "The private launch approval code is CEDAR-7919."
    document = Document()
    document.add_paragraph(body)
    document_content = BytesIO()
    document.save(document_content)
    model = VisionLLM(
        [
            Delta(content="First answer"),
            Delta(content="Follow-up answer"),
            Delta(content="Replacement answer"),
            Delta(content="Continued answer"),
        ],
        max_input_tokens=128000,
    )
    files: list[UserFile] = []
    try:
        descriptors: list[FileDescriptor] = []
        for filename, content, mime, file_type in (
            (
                "approval.docx",
                document_content.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ChatFileType.DOC,
            ),
            ("diagram.png", b"\x89PNG\r\n\x1a\n", "image/png", ChatFileType.IMAGE),
        ):
            file_id = file_store.save_file(
                content=BytesIO(content),
                display_name=filename,
                file_origin=FileOrigin.CHAT_UPLOAD,
                file_type=mime,
            )
            file = UserFile(
                id=uuid4(),
                user_id=user.id,
                file_id=file_id,
                name=filename,
                file_type=mime,
                token_count=100,
                status=UserFileStatus.PROCESSING
                if file_type == ChatFileType.DOC
                else UserFileStatus.COMPLETED,
            )
            files.append(file)
            db_session.add(file)
            descriptors.append(
                {
                    "id": file_id,
                    "user_file_id": str(file.id),
                    "name": filename,
                    "type": file_type,
                }
            )
        db_session.commit()
        with (
            patch("onyx.chat.process_message.get_llm_for_persona", return_value=model),
            patch(
                "onyx.chat.files._get_or_extract_plaintext",
                wraps=_get_or_extract_plaintext,
            ) as extract_text,
        ):
            first = list(
                handle_stream_message_objects(
                    new_msg_req=SendMessageRequest(
                        chat_session_id=session.id,
                        message="Review the private attachments.",
                        file_descriptors=descriptors,
                    ),
                    user=user,
                )
            )
            assert final_answer(first) == "First answer"
            ids = next(
                part for part in first if isinstance(part, MessageResponseIDInfo)
            )
            assert ids.user_message_id is not None
            assert (
                final_answer(
                    list(submit_query("What was the approval code?", session.id, user))
                )
                == "Follow-up answer"
            )
            parent_id = (
                ids.user_message_id
                if branch == "regenerate"
                else ids.reserved_assistant_message_id
                if branch == "edit_followup"
                else None
            )
            replacement = list(
                handle_stream_message_objects(
                    new_msg_req=SendMessageRequest(
                        chat_session_id=session.id,
                        parent_message_id=parent_id,
                        message="Use the revised question.",
                    ),
                    user=user,
                )
            )
            assert final_answer(replacement) == "Replacement answer"
            assert (
                final_answer(
                    list(
                        submit_query("Continue the selected branch.", session.id, user)
                    )
                )
                == "Continued answer"
            )
        assert extract_text.call_count == 1
        for index, request in enumerate(model.requests):
            prompt = "\n".join(
                message.model_dump_json() for message in request["prompt"]
            )
            retains_attachment = branch != "edit_root" or index < 2
            assert prompt.count(body) == int(retains_attachment)
            assert ("approval.docx" in prompt) == retains_attachment
            assert sum(
                isinstance(part, ImageContentPart)
                for message in request["prompt"]
                if isinstance(message.content, list)
                for part in message.content
            ) == int(retains_attachment)
        for request in model.requests[2:]:
            selected_prompt = "\n".join(
                message.model_dump_json() for message in request["prompt"]
            )
            assert "What was the approval code?" not in selected_prompt
            assert "Follow-up answer" not in selected_prompt
            assert ("First answer" in selected_prompt) == (branch == "edit_followup")
            assert ("Use the revised question." in selected_prompt) == (
                branch != "regenerate"
            )
        db_session.expire_all()
        rows = list(
            db_session.scalars(
                select(ChatMessage).where(ChatMessage.chat_session_id == session.id)
            )
        )
        assert rows and all(not row.message for row in rows)
        assert all(
            "name" not in descriptor for row in rows for descriptor in row.files or []
        )
        assert (
            db_session.scalar(
                select(ChatResponseItem.id)
                .join(ChatMessage)
                .where(ChatMessage.chat_session_id == session.id)
            )
            is None
        )
    finally:
        db_session.rollback()
        teardown_incognito_session(session.id)
        delete_chat_session(user.id, session.id, db_session, hard_delete=True)
        for file in files:
            file_store.delete_file(file.file_id)
            file_store.delete_file(
                plaintext_file_name_for_id(str(file.id)), error_on_missing=False
            )
            db_session.delete(file)
        delete_test_user(db_session, user)
        db_session.commit()


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
                assert "Include supporting evidence." not in followup_prompt
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
@pytest.mark.parametrize("summary_fails", [False, True])
def test_compacted_chat_reloads_continues_and_regenerates_selected_branch(
    db_session: Session,
    summary_fails: bool,
) -> None:
    user = create_test_user(db_session, "compacted-chat")
    session = create_chat_session(db_session, user)
    original_input = "The project is called Kiwi. " + "historical detail " * 10000
    summary = (
        ""
        if summary_fails
        else "The original background establishes that the project is called Kiwi."
    )
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
                side_effect=RuntimeError("Summary unavailable")
                if summary_fails
                else None,
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
            replayed = translate_assistant_message_to_packets(
                saved, load_session_tools([saved], db_session), db_session
            )
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
