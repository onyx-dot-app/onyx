"""Tests for llm_loop.py, specifically the construct_message_history function."""

import pytest

from onyx.chat.llm_loop import _should_keep_bedrock_tool_definitions
from onyx.chat.llm_loop import _try_fallback_tool_extraction
from onyx.chat.llm_loop import construct_message_history
from onyx.chat.models import ChatLoadedFile
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ContextFileMetadata
from onyx.chat.models import ExtractedContextFiles
from onyx.chat.models import FileToolMetadata
from onyx.chat.models import LlmStepResult
from onyx.chat.models import ToolCallSimple
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallKickoff


class _StubConfig:
    def __init__(self, model_provider: str) -> None:
        self.model_provider = model_provider


class _StubLLM:
    def __init__(self, model_provider: str) -> None:
        self.config = _StubConfig(model_provider=model_provider)


def create_message(
    content: str, message_type: MessageType, token_count: int | None = None
) -> ChatMessageSimple:
    """Helper to create a ChatMessageSimple for testing."""
    if token_count is None:
        # Simple token estimation: ~1 token per 4 characters
        token_count = max(1, len(content) // 4)
    return ChatMessageSimple(
        message=content,
        token_count=token_count,
        message_type=message_type,
    )


def create_assistant_with_tool_call(
    tool_call_id: str, tool_name: str, token_count: int
) -> ChatMessageSimple:
    """Helper to create an ASSISTANT message with tool_calls for testing."""
    tool_call = ToolCallSimple(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_arguments={},
        token_count=token_count,
    )
    return ChatMessageSimple(
        message="",
        token_count=token_count,
        message_type=MessageType.ASSISTANT,
        tool_calls=[tool_call],
    )


def create_tool_response(
    tool_call_id: str, content: str, token_count: int
) -> ChatMessageSimple:
    """Helper to create a TOOL_CALL_RESPONSE message for testing."""
    return ChatMessageSimple(
        message=content,
        token_count=token_count,
        message_type=MessageType.TOOL_CALL_RESPONSE,
        tool_call_id=tool_call_id,
    )


def create_context_files(
    num_files: int = 0, num_images: int = 0, tokens_per_file: int = 100
) -> ExtractedContextFiles:
    """Helper to create ExtractedContextFiles for testing."""
    file_texts = [f"Project file {i} content" for i in range(num_files)]
    file_metadata = [
        ContextFileMetadata(
            file_id=f"file_{i}",
            filename=f"file_{i}.txt",
            file_content=f"Project file {i} content",
        )
        for i in range(num_files)
    ]
    image_files = [
        ChatLoadedFile(
            file_id=f"image_{i}",
            content=b"",
            file_type=ChatFileType.IMAGE,
            filename=f"image_{i}.png",
            content_text=None,
            token_count=50,
        )
        for i in range(num_images)
    ]
    return ExtractedContextFiles(
        file_texts=file_texts,
        image_files=image_files,
        use_as_search_filter=False,
        total_token_count=num_files * tokens_per_file,
        file_metadata=file_metadata,
        uncapped_token_count=num_files * tokens_per_file,
    )


class TestConstructMessageHistory:
    """Tests for the construct_message_history function."""

    def test_basic_no_truncation(self) -> None:
        """Test basic functionality when all messages fit within token budget."""
        system_prompt = create_message(
            "You are a helpful assistant", MessageType.SYSTEM, 10
        )
        user_msg1 = create_message("Hello", MessageType.USER, 5)
        assistant_msg1 = create_message("Hi there!", MessageType.ASSISTANT, 5)
        user_msg2 = create_message("How are you?", MessageType.USER, 5)

        simple_chat_history = [user_msg1, assistant_msg1, user_msg2]
        context_files = create_context_files()

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        # Should have: system, user1, assistant1, user2
        assert len(result) == 4
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert result[2] == assistant_msg1
        assert result[3] == user_msg2

    def test_with_custom_agent_prompt(self) -> None:
        """Test that custom agent prompt is inserted before the last user message."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First message", MessageType.USER, 5)
        assistant_msg1 = create_message("Response", MessageType.ASSISTANT, 5)
        user_msg2 = create_message("Second message", MessageType.USER, 5)
        custom_agent = create_message("Custom instructions", MessageType.USER, 10)

        simple_chat_history = [user_msg1, assistant_msg1, user_msg2]
        context_files = create_context_files()

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_agent,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        # Should have: system, user1, assistant1, custom_agent, user2
        assert len(result) == 5
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert result[2] == assistant_msg1
        assert result[3] == custom_agent  # Before last user message
        assert result[4] == user_msg2

    def test_with_context_files(self) -> None:
        """Test that project files are inserted before the last user message."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First message", MessageType.USER, 5)
        user_msg2 = create_message("Second message", MessageType.USER, 5)

        simple_chat_history = [user_msg1, user_msg2]
        context_files = create_context_files(num_files=2, tokens_per_file=50)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        # Should have: system, user1, context_files_message, user2
        assert len(result) == 4
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert (
            result[2].message_type == MessageType.USER
        )  # Project files as user message
        assert "documents" in result[2].message  # Should contain JSON structure
        assert result[3] == user_msg2

    def test_with_reminder_message(self) -> None:
        """Test that reminder message is added at the very end."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg = create_message("Hello", MessageType.USER, 5)
        reminder = create_message("Remember to cite sources", MessageType.USER, 10)

        simple_chat_history = [user_msg]
        context_files = create_context_files()

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=reminder,
            context_files=context_files,
            available_tokens=1000,
        )

        # Should have: system, user, reminder
        assert len(result) == 3
        assert result[0] == system_prompt
        assert result[1] == user_msg
        assert result[2] == reminder  # At the end

    def test_tool_calls_after_last_user_message(self) -> None:
        """Test that tool calls and responses after last user message are preserved."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First message", MessageType.USER, 5)
        assistant_msg1 = create_message("Response", MessageType.ASSISTANT, 5)
        user_msg2 = create_message("Search for X", MessageType.USER, 5)
        assistant_with_tool = create_assistant_with_tool_call("tc_1", "search", 5)
        tool_response = create_tool_response("tc_1", "Search results...", 10)

        simple_chat_history = [
            user_msg1,
            assistant_msg1,
            user_msg2,
            assistant_with_tool,
            tool_response,
        ]
        context_files = create_context_files()

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        # Should have: system, user1, assistant1, user2, assistant_with_tool, tool_response
        assert len(result) == 6
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert result[2] == assistant_msg1
        assert result[3] == user_msg2
        assert result[4] == assistant_with_tool
        assert result[5] == tool_response

    def test_custom_agent_and_project_before_last_user_with_tools_after(self) -> None:
        """Test correct ordering with custom agent, project files, and tool calls."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 5)
        user_msg2 = create_message("Second", MessageType.USER, 5)
        assistant_with_tool = create_assistant_with_tool_call("tc_1", "tool", 5)
        custom_agent = create_message("Custom", MessageType.USER, 10)

        simple_chat_history = [user_msg1, user_msg2, assistant_with_tool]
        context_files = create_context_files(num_files=1, tokens_per_file=50)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_agent,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        # Should have: system, user1, custom_agent, context_files, user2, assistant_with_tool
        assert len(result) == 6
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert result[2] == custom_agent  # Before last user message
        assert result[3].message_type == MessageType.USER  # Project files
        assert "documents" in result[3].message
        assert result[4] == user_msg2  # Last user message
        assert result[5] == assistant_with_tool  # After last user message

    def test_project_images_attached_to_last_user_message(self) -> None:
        """Test that project images are attached to the last user message."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 5)
        user_msg2 = create_message("Second", MessageType.USER, 5)

        simple_chat_history = [user_msg1, user_msg2]
        context_files = create_context_files(num_files=0, num_images=2)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        # Last message should have the project images
        last_message = result[-1]
        assert last_message.message == "Second"
        assert last_message.image_files is not None
        assert len(last_message.image_files) == 2
        assert last_message.image_files[0].file_id == "image_0"
        assert last_message.image_files[1].file_id == "image_1"

    def test_project_images_preserve_existing_images(self) -> None:
        """Test that project images are appended to existing images on the user message."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)

        # Create a user message with existing images
        existing_image = ChatLoadedFile(
            file_id="existing_image",
            content=b"",
            file_type=ChatFileType.IMAGE,
            filename="existing.png",
            content_text=None,
            token_count=50,
        )
        user_msg = ChatMessageSimple(
            message="Message with image",
            token_count=5,
            message_type=MessageType.USER,
            image_files=[existing_image],
        )

        simple_chat_history = [user_msg]
        context_files = create_context_files(num_files=0, num_images=1)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        # Last message should have both existing and project images
        last_message = result[-1]
        assert last_message.image_files is not None
        assert len(last_message.image_files) == 2
        assert last_message.image_files[0].file_id == "existing_image"
        assert last_message.image_files[1].file_id == "image_0"

    def test_truncation_from_top(self) -> None:
        """Test that history is truncated from the top when token budget is exceeded."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 20)
        assistant_msg1 = create_message("Response 1", MessageType.ASSISTANT, 20)
        user_msg2 = create_message("Second", MessageType.USER, 20)
        assistant_msg2 = create_message("Response 2", MessageType.ASSISTANT, 20)
        user_msg3 = create_message("Third", MessageType.USER, 20)

        simple_chat_history = [
            user_msg1,
            assistant_msg1,
            user_msg2,
            assistant_msg2,
            user_msg3,
        ]
        context_files = create_context_files()

        # Budget only allows last 3 messages + system (10 + 20 + 20 + 20 = 70 tokens)
        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=80,
        )

        # Should have: system, user2, assistant2, user3
        # user1 and assistant1 should be truncated
        assert len(result) == 4
        assert result[0] == system_prompt
        assert result[1] == user_msg2  # user1 truncated
        assert result[2] == assistant_msg2
        assert result[3] == user_msg3

    def test_truncation_preserves_last_user_and_messages_after(self) -> None:
        """Test that truncation preserves the last user message and everything after it."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 30)
        user_msg2 = create_message("Second", MessageType.USER, 20)
        assistant_with_tool = create_assistant_with_tool_call("tc_1", "tool", 20)
        tool_response = create_tool_response("tc_1", "tool_response", 20)

        simple_chat_history = [user_msg1, user_msg2, assistant_with_tool, tool_response]
        context_files = create_context_files()

        # Budget only allows last user message and messages after + system
        # (10 + 20 + 20 + 20 = 70 tokens)
        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=80,
        )

        # Should have: system, user2, assistant_with_tool, tool_response
        # user1 should be truncated, but user2 and everything after preserved
        assert len(result) == 4
        assert result[0] == system_prompt
        assert result[1] == user_msg2  # user1 truncated
        assert result[2] == assistant_with_tool
        assert result[3] == tool_response

    def test_truncation_drops_orphaned_tool_response(self) -> None:
        """If truncation drops an assistant tool call, its orphaned tool response is removed."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 10)
        assistant_with_tool = create_assistant_with_tool_call("tc_1", "tool", 25)
        tool_response = create_tool_response("tc_1", "tool_response", 5)
        assistant_msg1 = create_message("Used the tool above", MessageType.ASSISTANT, 5)
        user_msg2 = create_message("Latest question", MessageType.USER, 10)

        simple_chat_history = [
            user_msg1,
            assistant_with_tool,
            tool_response,
            assistant_msg1,
            user_msg2,
        ]
        context_files = create_context_files()

        # Remaining history budget is 10 tokens (30 total - 10 system - 10 last user):
        # keeps [tool_response, assistant_msg1] from history_before_last_user,
        # but drops assistant_with_tool, making tool_response orphaned.
        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=30,
        )

        # Orphaned tool response should be removed from final history.
        assert len(result) == 3
        assert result[0] == system_prompt
        assert result[1] == assistant_msg1
        assert result[2] == user_msg2

    def test_preserves_non_orphaned_tool_response(self) -> None:
        """Tool responses remain when their assistant tool call is present."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 10)
        assistant_with_tool = create_assistant_with_tool_call("tc_1", "tool", 20)
        tool_response = create_tool_response("tc_1", "tool_response", 5)
        user_msg2 = create_message("Latest question", MessageType.USER, 10)

        simple_chat_history = [user_msg1, assistant_with_tool, tool_response, user_msg2]
        context_files = create_context_files()

        # Remaining history budget is 25 tokens (45 total - 10 system - 10 last user):
        # keeps both assistant_with_tool and tool_response in history_before_last_user.
        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=45,
        )

        assert len(result) == 4
        assert result[0] == system_prompt
        assert result[1] == assistant_with_tool
        assert result[2] == tool_response
        assert result[3] == user_msg2

    def test_empty_history(self) -> None:
        """Test handling of empty chat history."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        custom_agent = create_message("Custom", MessageType.USER, 10)
        reminder = create_message("Reminder", MessageType.USER, 10)

        simple_chat_history: list[ChatMessageSimple] = []
        context_files = create_context_files(num_files=1, tokens_per_file=50)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_agent,
            simple_chat_history=simple_chat_history,
            reminder_message=reminder,
            context_files=context_files,
            available_tokens=1000,
        )

        # Should have: system, custom_agent, context_files, reminder
        assert len(result) == 4
        assert result[0] == system_prompt
        assert result[1] == custom_agent
        assert result[2].message_type == MessageType.USER  # Project files
        assert result[3] == reminder

    def test_no_user_message_raises_error(self) -> None:
        """Test that an error is raised when there's no user message in history."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        assistant_msg = create_message("Response", MessageType.ASSISTANT, 5)
        assistant_with_tool = create_assistant_with_tool_call("tc_1", "tool", 5)

        simple_chat_history = [assistant_msg, assistant_with_tool]
        context_files = create_context_files()

        with pytest.raises(ValueError, match="No user message found"):
            construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=None,
                simple_chat_history=simple_chat_history,
                reminder_message=None,
                context_files=context_files,
                available_tokens=1000,
            )

    def test_not_enough_tokens_for_required_elements(self) -> None:
        """Test error when there aren't enough tokens for required elements."""
        system_prompt = create_message("System", MessageType.SYSTEM, 50)
        user_msg = create_message("Message", MessageType.USER, 50)
        custom_agent = create_message("Custom", MessageType.USER, 50)

        simple_chat_history = [user_msg]
        context_files = create_context_files(num_files=1, tokens_per_file=100)

        # Total required: 50 (system) + 50 (custom) + 100 (project) + 50 (user) = 250
        # But only 200 available
        with pytest.raises(ValueError, match="Not enough tokens"):
            construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=custom_agent,
                simple_chat_history=simple_chat_history,
                reminder_message=None,
                context_files=context_files,
                available_tokens=200,
            )

    def test_not_enough_tokens_for_last_user_and_messages_after(self) -> None:
        """Test error when last user message and messages after don't fit."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 10)
        user_msg2 = create_message("Second", MessageType.USER, 30)
        assistant_with_tool = create_assistant_with_tool_call("tc_1", "tool", 30)

        simple_chat_history = [user_msg1, user_msg2, assistant_with_tool]
        context_files = create_context_files()

        # Budget: 50 tokens
        # Required: 10 (system) + 30 (user2) + 30 (assistant_with_tool) = 70 tokens
        # After subtracting system: 40 tokens available, but need 60 for user2 + assistant_with_tool
        with pytest.raises(
            ValueError, match="Not enough tokens to include the last user message"
        ):
            construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=None,
                simple_chat_history=simple_chat_history,
                reminder_message=None,
                context_files=context_files,
                available_tokens=50,
            )

    def test_complex_scenario_all_elements(self) -> None:
        """Test a complex scenario with all elements combined."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 10)
        assistant_msg1 = create_message("Response 1", MessageType.ASSISTANT, 10)
        user_msg2 = create_message("Second", MessageType.USER, 10)
        assistant_msg2 = create_message("Response 2", MessageType.ASSISTANT, 10)
        user_msg3 = create_message("Third", MessageType.USER, 10)
        assistant_with_tool = create_assistant_with_tool_call("tc_1", "search", 10)
        tool_response = create_tool_response("tc_1", "Results", 10)
        custom_agent = create_message("Custom instructions", MessageType.USER, 15)
        reminder = create_message("Cite sources", MessageType.USER, 10)

        simple_chat_history = [
            user_msg1,
            assistant_msg1,
            user_msg2,
            assistant_msg2,
            user_msg3,
            assistant_with_tool,
            tool_response,
        ]
        context_files = create_context_files(num_files=2, tokens_per_file=20)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_agent,
            simple_chat_history=simple_chat_history,
            reminder_message=reminder,
            context_files=context_files,
            available_tokens=1000,
        )

        # Expected order:
        # system, user1, assistant1, user2, assistant2,
        # custom_agent, context_files, user3, assistant_with_tool, tool_response, reminder
        assert len(result) == 11
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert result[2] == assistant_msg1
        assert result[3] == user_msg2
        assert result[4] == assistant_msg2
        assert result[5] == custom_agent  # Before last user
        assert (
            result[6].message_type == MessageType.USER
        )  # Project files before last user
        assert "documents" in result[6].message
        assert result[7] == user_msg3  # Last user message
        assert result[8] == assistant_with_tool  # After last user
        assert result[9] == tool_response  # After last user
        assert result[10] == reminder  # At the very end

    def test_context_files_json_format(self) -> None:
        """Test that project files are formatted correctly as JSON."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg = create_message("Hello", MessageType.USER, 5)

        simple_chat_history = [user_msg]
        context_files = create_context_files(num_files=2, tokens_per_file=50)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        # Find the project files message
        project_message = result[1]  # Should be between system and user

        # Verify it's formatted as JSON
        assert "Here are some documents provided for context" in project_message.message
        assert '"documents"' in project_message.message
        assert '"document": 1' in project_message.message
        assert '"document": 2' in project_message.message
        assert '"contents"' in project_message.message
        assert "Project file 0 content" in project_message.message
        assert "Project file 1 content" in project_message.message


def _simple_token_counter(text: str) -> int:
    """Approximate token counter for tests (~4 chars per token)."""
    return max(1, len(text) // 4)


def _make_file_metadata(
    file_id: str, filename: str, approx_chars: int = 50_000
) -> FileToolMetadata:
    return FileToolMetadata(
        file_id=file_id, filename=filename, approx_char_count=approx_chars
    )


class TestForgottenFileMetadata:
    """Tests for the forgotten-files mechanism in construct_message_history.

    These cover the scenario where a user attaches a large file to a chat
    message. On the first turn the file content message is in the context
    window. On subsequent turns, it may be truncated by either:
      a) context-window budget limits, or
      b) summary-based truncation removing the message before
         convert_chat_history ever runs — leaving an "orphaned" metadata
         entry with no corresponding file_id-tagged ChatMessageSimple.

    The forgotten-files mechanism must detect both cases and inject a
    lightweight metadata message so the LLM knows to use read_file.
    """

    def _build(
        self,
        simple_chat_history: list[ChatMessageSimple],
        available_tokens: int = 10_000,
        all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
    ) -> list[ChatMessageSimple]:
        """Shorthand wrapper around construct_message_history."""
        return construct_message_history(
            system_prompt=create_message("system", MessageType.SYSTEM, 5),
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=create_context_files(),
            available_tokens=available_tokens,
            token_counter=_simple_token_counter,
            all_injected_file_metadata=all_injected_file_metadata,
        )

    @staticmethod
    def _find_forgotten_message(
        result: list[ChatMessageSimple],
    ) -> ChatMessageSimple | None:
        """Find the forgotten-files metadata message in the result, if any."""
        for msg in result:
            if "Use the read_file tool" in msg.message:
                return msg
        return None

    # ------------------------------------------------------------------
    # Case 1: file message is still in context — no forgotten-files needed
    # ------------------------------------------------------------------

    def test_file_message_present_no_forgotten_metadata(self) -> None:
        """When the file message fits in context, no forgotten-file message
        should be injected.
        """
        file_meta = _make_file_metadata("file-abc", "moby_dick.txt")
        file_msg = create_message("Contents of moby dick...", MessageType.USER, 50)
        file_msg.file_id = "file-abc"

        history = [
            file_msg,
            create_message("Summarize this", MessageType.ASSISTANT, 20),
            create_message("What's chapter 1?", MessageType.USER, 10),
        ]
        result = self._build(
            history,
            available_tokens=10_000,
            all_injected_file_metadata={"file-abc": file_meta},
        )

        forgotten = self._find_forgotten_message(result)
        assert (
            forgotten is None
        ), "Should not inject forgotten-files when file is in context"
        # The file message itself should still be present
        assert any(m.file_id == "file-abc" for m in result)

    # ------------------------------------------------------------------
    # Case 2: file message dropped by context-window truncation
    # ------------------------------------------------------------------

    def test_file_message_dropped_by_truncation_gets_forgotten_metadata(self) -> None:
        """When the context budget is too tight and the file message gets
        truncated, a forgotten-files metadata message must appear.
        """
        file_meta = _make_file_metadata("file-abc", "moby_dick.txt")
        file_msg = create_message("x" * 2000, MessageType.USER, 500)
        file_msg.file_id = "file-abc"

        history = [
            file_msg,
            create_message("Got it", MessageType.ASSISTANT, 10),
            create_message("Tell me about ch1", MessageType.USER, 10),
        ]

        # Budget is just enough for the system prompt + last messages but
        # NOT the 500-token file message.
        result = self._build(
            history,
            available_tokens=100,
            all_injected_file_metadata={"file-abc": file_meta},
        )

        forgotten = self._find_forgotten_message(result)
        assert forgotten is not None, "Forgotten-files message should be injected"
        assert "moby_dick.txt" in forgotten.message
        assert "file-abc" in forgotten.message

        # The original file message should NOT be in context
        assert not any(
            getattr(m, "file_id", None) == "file-abc"
            and m.message_type == MessageType.USER
            for m in result
            if m is not forgotten
        )

    # ------------------------------------------------------------------
    # Case 3: file message removed by summary truncation ("orphaned" metadata)
    # ------------------------------------------------------------------

    def test_orphaned_metadata_triggers_forgotten_files(self) -> None:
        """Simulates the scenario where summary truncation in process_message
        removed the file's original message BEFORE convert_chat_history ran,
        so no ChatMessageSimple has the file_id tag. The metadata is still
        passed via all_injected_file_metadata and must be treated as dropped.
        """
        file_meta = _make_file_metadata("file-abc", "moby_dick.txt")

        # History has no file_id-tagged message — it was already removed by
        # summary truncation. Only later conversation remains.
        history = [
            create_message("Summary of earlier convo", MessageType.ASSISTANT, 20),
            create_message("Now tell me about chapter 2", MessageType.USER, 10),
        ]

        result = self._build(
            history,
            available_tokens=10_000,
            all_injected_file_metadata={"file-abc": file_meta},
        )

        forgotten = self._find_forgotten_message(result)
        assert (
            forgotten is not None
        ), "Orphaned file metadata should trigger forgotten-files message"
        assert "moby_dick.txt" in forgotten.message
        assert "file-abc" in forgotten.message

    # ------------------------------------------------------------------
    # Case 4: multiple files — one survives, one is dropped
    # ------------------------------------------------------------------

    def test_mixed_files_only_dropped_ones_appear_in_forgotten(self) -> None:
        """When two files exist but only one's message is truncated, only the
        truncated file should appear in the forgotten-files metadata.
        """
        meta_a = _make_file_metadata("file-a", "big_file.txt")
        meta_b = _make_file_metadata("file-b", "small_file.txt")

        # file-a has a huge message that will be dropped, file-b fits
        file_msg_a = create_message("x" * 2000, MessageType.USER, 500)
        file_msg_a.file_id = "file-a"
        file_msg_b = create_message("small content", MessageType.USER, 5)
        file_msg_b.file_id = "file-b"

        history = [
            file_msg_a,
            create_message("ok", MessageType.ASSISTANT, 3),
            file_msg_b,
            create_message("ok", MessageType.ASSISTANT, 3),
            create_message("Compare the two files", MessageType.USER, 10),
        ]

        # Tight budget: system(5) + last-user(10) = 15 min. Give ~50 so
        # file_msg_b(5)+assistant(3)+assistant(3) fit but file_msg_a(500) won't.
        result = self._build(
            history,
            available_tokens=80,
            all_injected_file_metadata={"file-a": meta_a, "file-b": meta_b},
        )

        forgotten = self._find_forgotten_message(result)
        assert forgotten is not None
        assert "big_file.txt" in forgotten.message
        assert "file-a" in forgotten.message
        # file-b should NOT be in the forgotten message — it's still in context
        assert "small_file.txt" not in forgotten.message

    # ------------------------------------------------------------------
    # Case 5: no metadata dict → no forgotten-files message even if dropped
    # ------------------------------------------------------------------

    def test_no_metadata_dict_means_no_forgotten_message(self) -> None:
        """If all_injected_file_metadata is None (FileReaderTool not enabled),
        no forgotten-files message should be emitted even if file messages
        are dropped by truncation.
        """
        file_msg = create_message("x" * 2000, MessageType.USER, 500)
        file_msg.file_id = "file-abc"

        history = [
            file_msg,
            create_message("Got it", MessageType.ASSISTANT, 10),
            create_message("Tell me more", MessageType.USER, 10),
        ]

        result = self._build(
            history,
            available_tokens=100,
            all_injected_file_metadata=None,
        )

        forgotten = self._find_forgotten_message(result)
        assert (
            forgotten is None
        ), "No forgotten-files message when metadata dict is None"

    # ------------------------------------------------------------------
    # Case 6: orphaned metadata with multiple files, all summarized away
    # ------------------------------------------------------------------

    def test_multiple_orphaned_files_all_appear_in_forgotten(self) -> None:
        """All files from summarized-away messages should be listed in the
        forgotten-files message.
        """
        meta_a = _make_file_metadata("file-a", "report.pdf")
        meta_b = _make_file_metadata("file-b", "data.csv")

        # Both original messages were removed by summary truncation;
        # only post-summary messages remain.
        history = [
            create_message("Earlier discussion summarized", MessageType.ASSISTANT, 15),
            create_message("What patterns do you see?", MessageType.USER, 10),
        ]

        result = self._build(
            history,
            available_tokens=10_000,
            all_injected_file_metadata={"file-a": meta_a, "file-b": meta_b},
        )

        forgotten = self._find_forgotten_message(result)
        assert forgotten is not None
        assert "report.pdf" in forgotten.message
        assert "data.csv" in forgotten.message

    # ------------------------------------------------------------------
    # Case 7: file metadata persists across many turns after truncation
    # ------------------------------------------------------------------

    def test_forgotten_metadata_persists_across_many_turns(self) -> None:
        """Simulates the real bug: after the file's original message is
        summarized away, every subsequent turn should still include the
        forgotten-files metadata — not just the first turn after truncation.
        """
        file_meta = _make_file_metadata("file-abc", "moby_dick.txt")

        # Build several turns AFTER the file was already summarized away.
        # Each turn, construct_message_history is called fresh with the
        # same all_injected_file_metadata.
        for turn in range(5):
            messages = [
                create_message("Summary", MessageType.ASSISTANT, 15),
            ]
            # Add some back-and-forth after the summary
            for i in range(turn):
                messages.append(create_message(f"Question {i}", MessageType.USER, 5))
                messages.append(create_message(f"Answer {i}", MessageType.ASSISTANT, 5))
            messages.append(
                create_message(f"Latest question (turn {turn})", MessageType.USER, 5)
            )

            result = self._build(
                messages,
                available_tokens=10_000,
                all_injected_file_metadata={"file-abc": file_meta},
            )

            forgotten = self._find_forgotten_message(result)
            assert (
                forgotten is not None
            ), f"Turn {turn}: forgotten-files message must persist every turn"
            assert "moby_dick.txt" in forgotten.message


class TestBedrockToolConfigGuard:
    def test_bedrock_with_tool_history_keeps_tool_definitions(self) -> None:
        llm = _StubLLM(LlmProviderNames.BEDROCK)
        history = [
            create_message("Question", MessageType.USER, 5),
            create_assistant_with_tool_call("tc_1", "search", 5),
            create_tool_response("tc_1", "Tool output", 5),
        ]

        assert _should_keep_bedrock_tool_definitions(llm, history) is True

    def test_bedrock_without_tool_history_does_not_keep_tool_definitions(self) -> None:
        llm = _StubLLM(LlmProviderNames.BEDROCK)
        history = [
            create_message("Question", MessageType.USER, 5),
            create_message("Answer", MessageType.ASSISTANT, 5),
        ]

        assert _should_keep_bedrock_tool_definitions(llm, history) is False

    def test_non_bedrock_with_tool_history_does_not_keep_tool_definitions(self) -> None:
        llm = _StubLLM(LlmProviderNames.OPENAI)
        history = [
            create_message("Question", MessageType.USER, 5),
            create_assistant_with_tool_call("tc_1", "search", 5),
            create_tool_response("tc_1", "Tool output", 5),
        ]

        assert _should_keep_bedrock_tool_definitions(llm, history) is False


class TestFallbackToolExtraction:
    def _tool_defs(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "internal_search",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "queries": {
                                "type": "array",
                                "items": {"type": "string"},
                            }
                        },
                        "required": ["queries"],
                    },
                },
            }
        ]

    def test_noop_if_fallback_was_already_attempted(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=True,
            tool_defs=self._tool_defs(),
            turn_index=0,
        )

        assert result is llm_step_result
        assert attempted is False

    def test_extracts_from_answer_when_required_and_no_tool_calls(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=3,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {"queries": ["alpha"]}
        assert result.tool_calls[0].placement == Placement(turn_index=3)

    def test_falls_back_to_reasoning_when_answer_has_no_tool_calls(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning='{"name":"internal_search","arguments":{"queries":["beta"]}}',
            answer="I should search first.",
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=5,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {"queries": ["beta"]}
        assert result.tool_calls[0].placement == Placement(turn_index=5)

    def test_extracts_xml_style_invoke_from_answer_when_required(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer=(
                '<function_calls><invoke name="internal_search">'
                '<parameter name="queries" string="false">'
                '["Onyx documentation", "Onyx docs", "Onyx platform"]'
                "</parameter></invoke></function_calls>"
            ),
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=7,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {
            "queries": ["Onyx documentation", "Onyx docs", "Onyx platform"]
        }
        assert result.tool_calls[0].placement == Placement(turn_index=7)

    def test_extracts_xml_style_invoke_from_answer_when_auto(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            # Runtime-faithful shape: filtered answer is empty, raw answer has XML payload.
            answer=None,
            raw_answer=(
                '<function_calls><invoke name="internal_search">'
                '<parameter name="queries" string="false">'
                '["Onyx documentation", "Onyx docs", "Onyx internal docs"]'
                "</parameter></invoke></function_calls>"
            ),
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.AUTO,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=9,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {
            "queries": ["Onyx documentation", "Onyx docs", "Onyx internal docs"]
        }
        assert result.tool_calls[0].placement == Placement(turn_index=9)

    def test_extracts_from_raw_answer_when_filtered_answer_has_no_xml(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer="",
            raw_answer=(
                '<function_calls><invoke name="internal_search">'
                '<parameter name="queries" string="false">'
                '["Onyx documentation", "Onyx docs"]'
                "</parameter></invoke></function_calls>"
            ),
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.AUTO,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=10,
        )

        assert attempted is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "internal_search"
        assert result.tool_calls[0].tool_args == {
            "queries": ["Onyx documentation", "Onyx docs"]
        }
        assert result.tool_calls[0].placement == Placement(turn_index=10)

    def test_does_not_attempt_fallback_for_auto_without_tool_call_hints(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer="Here is a normal answer with no tool call payload.",
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.AUTO,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=2,
        )

        assert result is llm_step_result
        assert attempted is False

    def test_returns_unchanged_when_required_but_nothing_extractable(self) -> None:
        llm_step_result = LlmStepResult(
            reasoning="Need more info.",
            answer="Let me think.",
            tool_calls=None,
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=1,
        )

        assert result is llm_step_result
        assert attempted is True
        assert result.tool_calls is None

    def test_noop_when_tool_calls_already_present(self) -> None:
        existing_call = ToolCallKickoff(
            tool_call_id="call_existing",
            tool_name="internal_search",
            tool_args={"queries": ["already-set"]},
            placement=Placement(turn_index=0),
        )
        llm_step_result = LlmStepResult(
            reasoning=None,
            answer='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
            tool_calls=[existing_call],
        )

        result, attempted = _try_fallback_tool_extraction(
            llm_step_result=llm_step_result,
            tool_choice=ToolChoiceOptions.REQUIRED,
            fallback_extraction_attempted=False,
            tool_defs=self._tool_defs(),
            turn_index=0,
        )

        assert result is llm_step_result
        assert attempted is False
