from onyx.chat import process_message
from onyx.chat.models import AnswerStream, StreamingError
from onyx.server.query_and_chat.models import MessageResponseIDInfo


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
