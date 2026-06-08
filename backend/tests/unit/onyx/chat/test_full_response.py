from onyx.chat import process_message
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.models import ChatFullResponse
from onyx.chat.models import AnswerStream
from onyx.chat.models import StreamingError
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet


def test_chat_full_response_user_message_id_defaults_to_none() -> None:
    """ChatFullResponse.user_message_id defaults to None for backwards compat."""
    response = ChatFullResponse(
        answer="hello",
        answer_citationless="hello",
        top_documents=[],
        citation_info=[],
        message_id=42,
    )
    assert response.user_message_id is None


def test_chat_full_response_user_message_id_explicit() -> None:
    """ChatFullResponse accepts an explicit user_message_id value."""
    response = ChatFullResponse(
        answer="hello",
        answer_citationless="hello",
        top_documents=[],
        citation_info=[],
        message_id=42,
        user_message_id=7,
    )
    assert response.user_message_id == 7


def test_gather_stream_full_captures_user_message_id() -> None:
    """gather_stream_full captures user_message_id from MessageResponseIDInfo."""
    from onyx.chat.chat_state import ChatStateContainer

    packets: AnswerStream = iter(
        [
            MessageResponseIDInfo(
                user_message_id=7,
                reserved_assistant_message_id=42,
            ),
            StreamingError(
                error="test error",
                error_code="TEST_ERROR",
            ),
        ]
    )

    state_container = ChatStateContainer()

    result = process_message.gather_stream_full(packets, state_container)

    assert result.user_message_id == 7
    assert result.message_id == 42
    assert result.error_msg == "test error"


def test_gather_stream_full_user_message_id_none_when_missing() -> None:
    """gather_stream_full defaults user_message_id to None when packet has null."""
    from onyx.chat.chat_state import ChatStateContainer

    packets: AnswerStream = iter(
        [
            MessageResponseIDInfo(
                user_message_id=None,
                reserved_assistant_message_id=42,
            ),
            StreamingError(
                error="test error",
                error_code="TEST_ERROR",
            ),
        ]
    )

    state_container = ChatStateContainer()

    result = process_message.gather_stream_full(packets, state_container)

    assert result.user_message_id is None
    assert result.message_id == 42


def test_gather_stream_full_preserves_all_fields() -> None:
    """gather_stream_full preserves citations, documents, and metadata."""
    from onyx.chat.chat_state import ChatStateContainer
    from onyx.server.query_and_chat.streaming_models import Packet
    from onyx.server.query_and_chat.placement import Placement

    placement = Placement(turn_index=0)
    packets: AnswerStream = iter(
        [
            MessageResponseIDInfo(
                user_message_id=7,
                reserved_assistant_message_id=42,
            ),
            Packet(
                placement=placement,
                obj=CitationInfo(
                    citation_number=1,
                    document_id="doc-1",
                ),
            ),
            Packet(
                placement=placement,
                obj=CitationInfo(
                    citation_number=2,
                    document_id="doc-2",
                ),
            ),
            StreamingError(
                error="test error",
                error_code="TEST_ERROR",
            ),
        ]
    )

    state_container = ChatStateContainer()

    result = process_message.gather_stream_full(packets, state_container)

    assert result.user_message_id == 7
    assert result.message_id == 42
    assert result.error_msg == "test error"
    assert len(result.citation_info) == 2
    assert result.citation_info[0].citation_number == 1
    assert result.citation_info[0].document_id == "doc-1"
    assert result.citation_info[1].citation_number == 2
    assert result.citation_info[1].document_id == "doc-2"
    assert result.answer == ""
