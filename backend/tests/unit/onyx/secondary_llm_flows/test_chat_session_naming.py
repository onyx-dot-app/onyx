from typing import cast
from unittest.mock import MagicMock, patch
from uuid import uuid4

from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.secondary_llm_flows.chat_session_naming import (
    DEFAULT_CHAT_SESSION_NAME,
    get_fallback_chat_session_name,
)
from onyx.server.query_and_chat.chat_backend import (
    _generate_or_fallback_chat_session_name,
)


def _chat_message(message: str, message_type: MessageType) -> ChatMessage:
    chat_message = MagicMock()
    chat_message.message = message
    chat_message.message_type = message_type
    return cast(ChatMessage, chat_message)


def test_fallback_chat_session_name_uses_first_user_message() -> None:
    chat_history = [
        _chat_message("Assistant text", MessageType.ASSISTANT),
        _chat_message("A" * 50, MessageType.USER),
        _chat_message("Later user text", MessageType.USER),
    ]

    assert get_fallback_chat_session_name(chat_history) == f"{'A' * 40}..."


def test_fallback_chat_session_name_handles_empty_history() -> None:
    assert get_fallback_chat_session_name([]) == DEFAULT_CHAT_SESSION_NAME


def test_rate_limited_chat_naming_returns_fallback() -> None:
    first_user_message = "Explain cost-based usage metering"
    chat_history = [_chat_message(first_user_message, MessageType.USER)]
    request = MagicMock()
    user = MagicMock()
    user.id = uuid4()

    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.check_token_rate_limits",
            side_effect=OnyxError(OnyxErrorCode.RATE_LIMITED),
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_default_llm"
        ) as get_default_llm,
    ):
        generated_name = _generate_or_fallback_chat_session_name(
            chat_history=chat_history,
            request=request,
            user=user,
            chat_session_id=uuid4(),
        )

    assert generated_name == first_user_message
    get_default_llm.assert_not_called()
