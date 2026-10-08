"""Saved compaction cutoffs survive attachment loading and later chat turns."""

import pytest

from onyx.agents.compaction import working_messages
from onyx.agents.execution_records import CompactionCheckpoint
from onyx.chat.chat_utils import convert_chat_history
from onyx.chat.models import ChatHistoryMessage
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.llm.models import AssistantMessage, TextContent


@pytest.mark.parametrize("file_was_loaded", [False, True])
@pytest.mark.parametrize("summarize_answer", [False, True])
def test_saved_cutoff_survives_file_loading_and_later_turn(
    file_was_loaded: bool, summarize_answer: bool
) -> None:
    question = ChatHistoryMessage(
        id=1,
        message_type=MessageType.USER,
        message="Explain the attachment",
        token_count=4,
        files=[{"id": "attachment", "type": ChatFileType.PLAIN_TEXT}],
        is_clarification=False,
        response_messages=[],
    )
    answer = ChatHistoryMessage(
        id=2,
        message_type=MessageType.ASSISTANT,
        message="First answer",
        token_count=2,
        files=[],
        is_clarification=False,
        response_messages=[
            AssistantMessage(
                id="first-generation", content=[TextContent(text="First answer")]
            )
        ],
    )
    current_question = question.model_copy(
        update={"id": 3, "message": "Continue", "files": []}
    )
    pending_file = ChatLoadedFile(
        file_id="attachment",
        filename="attachment.txt",
        file_type=ChatFileType.PLAIN_TEXT,
        content=b"",
        content_text=None,
        content_pending=True,
        token_count=0,
    )
    source = convert_chat_history(
        [question, answer, current_question],
        files=[pending_file] if file_was_loaded else [],
        context_image_files=[],
        additional_context=None,
        token_counter=len,
    ).messages
    cutoff = source[-2] if summarize_answer else source[-3]
    assert cutoff.id is not None
    checkpoint = CompactionCheckpoint(
        summary="The user asked about the attachment.",
        covered_through_message_id=cutoff.id,
    )
    restored_checkpoint = CompactionCheckpoint.model_validate_json(
        checkpoint.model_dump_json()
    )
    ready_file = pending_file.model_copy(
        update={
            "content_text": "The attachment has finished processing.",
            "content_pending": False,
            "token_count": 8,
        }
    )
    later_question = question.model_copy(
        update={"id": 5, "message": "What next?", "files": []}
    )
    later_answer = answer.model_copy(
        update={
            "id": 4,
            "response_messages": [
                AssistantMessage(
                    id="second-generation", content=[TextContent(text="Next answer")]
                )
            ],
        }
    )
    reloaded = convert_chat_history(
        [question, answer, current_question, later_answer, later_question],
        files=[ready_file],
        context_image_files=[],
        additional_context=None,
        token_counter=len,
    ).messages
    assert reloaded[0].text != source[0].text
    expected_tail = ["Continue", "Next answer", "What next?"]
    if not summarize_answer:
        expected_tail.insert(0, "First answer")
    assert [
        message.text for message in working_messages(reloaded, restored_checkpoint)
    ] == [
        "Conversation summary:\nThe user asked about the attachment.",
        *expected_tail,
    ]
    assert "finished processing" in reloaded[0].text
    assert restored_checkpoint == checkpoint
