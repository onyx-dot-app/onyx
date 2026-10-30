from onyx.chat import process_message
from onyx.chat.models import AnswerStream
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CitationInfo,
    Packet,
    StreamingError,
)


def test_gather_stream_returns_empty_answer_when_streaming_error_only() -> None:
    packets: AnswerStream = iter(
        [
            MessageResponseIDInfo(
                user_message_id=None,
                reserved_assistant_message_id=42,
            ),
            StreamingError(
                error="OpenAI quota exceeded",
                error_code="BUDGET_EXCEEDED",
                is_retryable=False,
            ),
        ]
    )

    result = process_message.gather_stream(packets)

    assert result.answer == ""
    assert result.answer_citationless == ""
    assert result.error_msg == "OpenAI quota exceeded"
    assert result.message_id == 42


def test_gather_stream_retains_interleaved_root_sections_and_citations() -> None:
    packets = [
        MessageResponseIDInfo(user_message_id=1, reserved_assistant_message_id=2)
    ]
    root = Placement(turn_index=0, tab_index=0)
    child = Placement(turn_index=0, tab_index=0, sub_turn_index=0)
    response = process_message.gather_stream(
        iter(
            [
                *packets,
                Packet(placement=root, obj=AgentResponseStart()),
                Packet(
                    placement=root, obj=AgentResponseDelta(content="First section. ")
                ),
                Packet(
                    placement=root,
                    obj=CitationInfo(citation_number=1, document_id="first"),
                ),
                Packet(placement=child, obj=AgentResponseStart()),
                Packet(placement=child, obj=AgentResponseDelta(content="Child text")),
                Packet(placement=root, obj=AgentResponseStart()),
                Packet(
                    placement=root, obj=AgentResponseDelta(content="Second section.")
                ),
            ]
        )
    )
    assert response.answer == "First section. Second section."
    assert response.citation_info == [
        CitationInfo(citation_number=1, document_id="first")
    ]
