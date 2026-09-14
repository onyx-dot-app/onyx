from typing import cast
from unittest.mock import MagicMock

from onyx.configs.constants import MessageType
from onyx.context.messages import prompt_metadata
from onyx.db.chat_history import (
    _build_tool_call_response_history_message,
    convert_chat_history,
)
from onyx.db.models import ChatMessage
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.prompts.chat_prompts import TOOL_CALL_RESPONSE_CROSS_MESSAGE


class TestBuildToolCallResponseHistoryMessage:
    def test_image_tool_uses_generated_images(self) -> None:
        message = _build_tool_call_response_history_message(
            tool_name="generate_image",
            generated_images=[{"file_id": "img-1", "revised_prompt": "p1"}],
            tool_call_response=None,
        )
        assert message == '[{"file_id": "img-1", "revised_prompt": "p1"}]'

    def test_non_image_tool_uses_placeholder(self) -> None:
        message = _build_tool_call_response_history_message(
            tool_name="web_search",
            generated_images=None,
            tool_call_response='{"raw":"value"}',
        )
        assert message == TOOL_CALL_RESPONSE_CROSS_MESSAGE


class TestConvertChatHistory:
    """Project images attach once, to the last user message in history."""

    def _make_chat_message(
        self,
        message: str,
        message_type: MessageType,
        token_count: int = 5,
    ) -> MagicMock:
        msg = MagicMock()
        msg.agent_transcript = None
        msg.message = message
        msg.message_type = message_type
        msg.token_count = token_count
        msg.files = None
        msg.tool_calls = None
        return msg

    def test_attaches_project_images_to_last_user_message_only_once(
        self,
    ) -> None:
        project_image = ChatLoadedFile(
            file_id="project_image",
            content=b"",
            file_type=ChatFileType.IMAGE,
            filename="project.png",
            content_text=None,
            token_count=50,
        )

        chat_history = [
            self._make_chat_message("First question", MessageType.USER),
            self._make_chat_message("First answer", MessageType.ASSISTANT),
            self._make_chat_message("Second question", MessageType.USER),
        ]

        result = convert_chat_history(
            chat_history=cast(list[ChatMessage], chat_history),
            files=[],
            context_image_files=[project_image],
            additional_context=None,
            token_counter=lambda s: len(s),
            tool_id_to_name_map={},
        )

        user_messages = [m for m in result.messages if m.role == "user"]
        assert len(user_messages) == 2

        # First USER message must NOT carry the project image.
        first_user = user_messages[0]
        assert first_user.text == "First question"
        assert prompt_metadata(first_user).image_files is None

        # Last USER message carries the project image exactly once.
        last_user = user_messages[-1]
        assert last_user.text == "Second question"
        images = prompt_metadata(last_user).image_files
        assert images is not None
        assert len(images) == 1
        assert images[0].file_id == "project_image"

    def test_tool_response_placeholder_token_count_is_measured(self) -> None:
        """Cross-turn tool responses are replayed as a placeholder — its
        budgeted token count must come from the token counter, not a
        hardcoded constant."""
        tool_call = MagicMock()
        tool_call.turn_number = 0
        tool_call.tool_id = 1
        tool_call.tool_call_id = "call-1"
        tool_call.tool_call_arguments = {"queries": ["alpha"]}
        tool_call.tool_call_tokens = 12
        tool_call.generated_images = None
        tool_call.tool_call_response = "original tool output"

        assistant_msg = self._make_chat_message("final answer", MessageType.ASSISTANT)
        assistant_msg.tool_calls = [tool_call]

        chat_history = [
            self._make_chat_message("A question", MessageType.USER),
            assistant_msg,
        ]

        result = convert_chat_history(
            chat_history=cast(list[ChatMessage], chat_history),
            files=[],
            context_image_files=[],
            additional_context=None,
            token_counter=lambda s: len(s),
            tool_id_to_name_map={1: "internal_search"},
        )

        tool_responses = [m for m in result.messages if m.role == "tool_result"]
        assert len(tool_responses) == 1
        assert tool_responses[0].text == TOOL_CALL_RESPONSE_CROSS_MESSAGE
        assert prompt_metadata(tool_responses[0]).token_count == len(
            TOOL_CALL_RESPONSE_CROSS_MESSAGE
        )
