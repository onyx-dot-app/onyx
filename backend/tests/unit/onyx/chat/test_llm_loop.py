"""Tests for llm_loop.py, specifically the construct_message_history function."""

import pytest

from onyx.chat.llm_loop import construct_message_history
from onyx.chat.models import ChatLoadedFile
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ExtractedProjectFiles
from onyx.chat.models import ProjectFileMetadata
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType


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


def create_project_files(
    num_files: int = 0, num_images: int = 0, tokens_per_file: int = 100
) -> ExtractedProjectFiles:
    """Helper to create ExtractedProjectFiles for testing."""
    project_file_texts = [f"Project file {i} content" for i in range(num_files)]
    project_file_metadata = [
        ProjectFileMetadata(
            file_id=f"file_{i}",
            filename=f"file_{i}.txt",
            file_content=f"Project file {i} content",
        )
        for i in range(num_files)
    ]
    project_image_files = [
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
    return ExtractedProjectFiles(
        project_file_texts=project_file_texts,
        project_image_files=project_image_files,
        project_as_filter=False,
        total_token_count=num_files * tokens_per_file,
        project_file_metadata=project_file_metadata,
        project_uncapped_token_count=num_files * tokens_per_file,
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
        project_files = create_project_files()

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
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
        project_files = create_project_files()

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_agent,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
            available_tokens=1000,
        )

        # Should have: system, user1, assistant1, custom_agent, user2
        assert len(result) == 5
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert result[2] == assistant_msg1
        assert result[3] == custom_agent  # Before last user message
        assert result[4] == user_msg2

    def test_with_project_files(self) -> None:
        """Test that project files are inserted before the last user message."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First message", MessageType.USER, 5)
        user_msg2 = create_message("Second message", MessageType.USER, 5)

        simple_chat_history = [user_msg1, user_msg2]
        project_files = create_project_files(num_files=2, tokens_per_file=50)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
            available_tokens=1000,
        )

        # Should have: system, user1, project_files_message, user2
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
        project_files = create_project_files()

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=reminder,
            project_files=project_files,
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
        tool_call = create_message("search(query='X')", MessageType.TOOL_CALL, 5)
        tool_response = create_message(
            "Search results...", MessageType.TOOL_CALL_RESPONSE, 10
        )

        simple_chat_history = [
            user_msg1,
            assistant_msg1,
            user_msg2,
            tool_call,
            tool_response,
        ]
        project_files = create_project_files()

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
            available_tokens=1000,
        )

        # Should have: system, user1, assistant1, user2, tool_call, tool_response
        assert len(result) == 6
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert result[2] == assistant_msg1
        assert result[3] == user_msg2
        assert result[4] == tool_call
        assert result[5] == tool_response

    def test_custom_agent_and_project_before_last_user_with_tools_after(self) -> None:
        """Test correct ordering with custom agent, project files, and tool calls."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 5)
        user_msg2 = create_message("Second", MessageType.USER, 5)
        tool_call = create_message("tool_call", MessageType.TOOL_CALL, 5)
        custom_agent = create_message("Custom", MessageType.USER, 10)

        simple_chat_history = [user_msg1, user_msg2, tool_call]
        project_files = create_project_files(num_files=1, tokens_per_file=50)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_agent,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
            available_tokens=1000,
        )

        # Should have: system, user1, custom_agent, project_files, user2, tool_call
        assert len(result) == 6
        assert result[0] == system_prompt
        assert result[1] == user_msg1
        assert result[2] == custom_agent  # Before last user message
        assert result[3].message_type == MessageType.USER  # Project files
        assert "documents" in result[3].message
        assert result[4] == user_msg2  # Last user message
        assert result[5] == tool_call  # After last user message

    def test_project_images_attached_to_last_user_message(self) -> None:
        """Test that project images are attached to the last user message."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 5)
        user_msg2 = create_message("Second", MessageType.USER, 5)

        simple_chat_history = [user_msg1, user_msg2]
        project_files = create_project_files(num_files=0, num_images=2)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
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
        project_files = create_project_files(num_files=0, num_images=1)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
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
        project_files = create_project_files()

        # Budget only allows last 3 messages + system (10 + 20 + 20 + 20 = 70 tokens)
        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
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
        tool_call = create_message("tool_call", MessageType.TOOL_CALL, 20)
        tool_response = create_message(
            "tool_response", MessageType.TOOL_CALL_RESPONSE, 20
        )

        simple_chat_history = [user_msg1, user_msg2, tool_call, tool_response]
        project_files = create_project_files()

        # Budget only allows last user message and messages after + system
        # (10 + 20 + 20 + 20 = 70 tokens)
        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
            available_tokens=80,
        )

        # Should have: system, user2, tool_call, tool_response
        # user1 should be truncated, but user2 and everything after preserved
        assert len(result) == 4
        assert result[0] == system_prompt
        assert result[1] == user_msg2  # user1 truncated
        assert result[2] == tool_call
        assert result[3] == tool_response

    def test_empty_history(self) -> None:
        """Test handling of empty chat history."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        custom_agent = create_message("Custom", MessageType.USER, 10)
        reminder = create_message("Reminder", MessageType.USER, 10)

        simple_chat_history: list[ChatMessageSimple] = []
        project_files = create_project_files(num_files=1, tokens_per_file=50)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_agent,
            simple_chat_history=simple_chat_history,
            reminder_message=reminder,
            project_files=project_files,
            available_tokens=1000,
        )

        # Should have: system, custom_agent, project_files, reminder
        assert len(result) == 4
        assert result[0] == system_prompt
        assert result[1] == custom_agent
        assert result[2].message_type == MessageType.USER  # Project files
        assert result[3] == reminder

    def test_no_user_message_raises_error(self) -> None:
        """Test that an error is raised when there's no user message in history."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        assistant_msg = create_message("Response", MessageType.ASSISTANT, 5)
        tool_call = create_message("tool_call", MessageType.TOOL_CALL, 5)

        simple_chat_history = [assistant_msg, tool_call]
        project_files = create_project_files()

        with pytest.raises(ValueError, match="No user message found"):
            construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=None,
                simple_chat_history=simple_chat_history,
                reminder_message=None,
                project_files=project_files,
                available_tokens=1000,
            )

    def test_not_enough_tokens_for_required_elements(self) -> None:
        """Test error when there aren't enough tokens for required elements."""
        system_prompt = create_message("System", MessageType.SYSTEM, 50)
        user_msg = create_message("Message", MessageType.USER, 50)
        custom_agent = create_message("Custom", MessageType.USER, 50)

        simple_chat_history = [user_msg]
        project_files = create_project_files(num_files=1, tokens_per_file=100)

        # Total required: 50 (system) + 50 (custom) + 100 (project) + 50 (user) = 250
        # But only 200 available
        with pytest.raises(ValueError, match="Not enough tokens"):
            construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=custom_agent,
                simple_chat_history=simple_chat_history,
                reminder_message=None,
                project_files=project_files,
                available_tokens=200,
            )

    def test_not_enough_tokens_for_last_user_and_messages_after(self) -> None:
        """Test error when last user message and messages after don't fit."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg1 = create_message("First", MessageType.USER, 10)
        user_msg2 = create_message("Second", MessageType.USER, 30)
        tool_call = create_message("tool_call", MessageType.TOOL_CALL, 30)

        simple_chat_history = [user_msg1, user_msg2, tool_call]
        project_files = create_project_files()

        # Budget: 50 tokens
        # Required: 10 (system) + 30 (user2) + 30 (tool_call) = 70 tokens
        # After subtracting system: 40 tokens available, but need 60 for user2 + tool_call
        with pytest.raises(
            ValueError, match="Not enough tokens to include the last user message"
        ):
            construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=None,
                simple_chat_history=simple_chat_history,
                reminder_message=None,
                project_files=project_files,
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
        tool_call = create_message("search()", MessageType.TOOL_CALL, 10)
        tool_response = create_message("Results", MessageType.TOOL_CALL_RESPONSE, 10)
        custom_agent = create_message("Custom instructions", MessageType.USER, 15)
        reminder = create_message("Cite sources", MessageType.USER, 10)

        simple_chat_history = [
            user_msg1,
            assistant_msg1,
            user_msg2,
            assistant_msg2,
            user_msg3,
            tool_call,
            tool_response,
        ]
        project_files = create_project_files(num_files=2, tokens_per_file=20)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_agent,
            simple_chat_history=simple_chat_history,
            reminder_message=reminder,
            project_files=project_files,
            available_tokens=1000,
        )

        # Expected order:
        # system, user1, assistant1, user2, assistant2,
        # custom_agent, project_files, user3, tool_call, tool_response, reminder
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
        assert result[8] == tool_call  # After last user
        assert result[9] == tool_response  # After last user
        assert result[10] == reminder  # At the very end

    def test_project_files_json_format(self) -> None:
        """Test that project files are formatted correctly as JSON."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg = create_message("Hello", MessageType.USER, 5)

        simple_chat_history = [user_msg]
        project_files = create_project_files(num_files=2, tokens_per_file=50)

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            project_files=project_files,
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
