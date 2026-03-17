from unittest.mock import Mock

import pytest

from onyx.chat import process_message
from onyx.chat.models import AnswerStream
from onyx.chat.models import StreamingError
from onyx.configs import app_configs
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.models import SendMessageRequest


def test_mock_llm_response_requires_integration_mode() -> None:
    assert (
        app_configs.INTEGRATION_TESTS_MODE is False
    ), "Unit tests expect INTEGRATION_TESTS_MODE=false."
    assert (
        process_message.INTEGRATION_TESTS_MODE is False
    ), "process_message should reflect INTEGRATION_TESTS_MODE=false in unit tests."

    request = SendMessageRequest(
        message="test",
        mock_llm_response='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
    )
    mock_user = Mock()
    mock_user.id = "user-id"
    mock_user.is_anonymous = False
    mock_user.email = "user@example.com"

    with pytest.raises(
        ValueError,
        match="mock_llm_response can only be used when INTEGRATION_TESTS_MODE=true",
    ):
        next(
            process_message.handle_stream_message_objects(
                new_msg_req=request,
                user=mock_user,
                db_session=Mock(),
            )
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
