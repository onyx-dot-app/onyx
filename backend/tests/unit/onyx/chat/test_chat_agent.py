"""Tests for llm_loop.py, including history construction and empty-response paths."""

from typing import Any, cast
from unittest.mock import Mock

import pytest
from pydantic_ai import messages as pm

from onyx.chat.chat_agent import (
    _REFUSAL_FINISH_REASONS,
    EmptyLLMResponseError,
    _build_empty_llm_response_error,
    construct_message_history,
    count_message_replay_tokens,
    select_reminder_text,
)
from onyx.chat.models import (
    ChatLoadedFile,
    ChatMessageSimple,
    ContextFileMetadata,
    ExtractedContextFiles,
    FileToolMetadata,
    ToolCallSimple,
)
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType
from onyx.llm.interfaces import LLMConfig, ToolChoiceOptions
from onyx.prompts.chat_prompts import IMAGE_GEN_REMINDER, OPEN_URL_REMINDER
from onyx.tools.constants import FILE_READER_TOOL_NAME
from onyx.tools.tool_implementations.search.search_tool import SearchTool


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

    def test_construct_message_history_does_not_duplicate_project_images(
        self,
    ) -> None:
        """Project images are attached upstream in convert_chat_history; this
        function must not re-attach them. Simulates the realistic state where
        the last user message in simple_chat_history already carries the
        project images, and asserts they appear exactly once."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)

        project_image = ChatLoadedFile(
            file_id="project_image",
            content=b"",
            file_type=ChatFileType.IMAGE,
            filename="project.png",
            content_text=None,
            token_count=50,
        )
        # Simulate convert_chat_history's output: the last user message already
        # has the project image attached.
        user_msg = ChatMessageSimple(
            message="What is in this image?",
            token_count=5,
            message_type=MessageType.USER,
            image_files=[project_image],
        )

        simple_chat_history = [user_msg]
        context_files = ExtractedContextFiles(
            file_texts=[],
            image_files=[project_image],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=0,
        )

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
        )

        last_message = result[-1]
        assert last_message.message == "What is in this image?"
        assert last_message.image_files is not None
        assert len(last_message.image_files) == 1
        assert last_message.image_files[0].file_id == "project_image"

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

        assert result == [
            system_prompt,
            user_msg1,
            assistant_with_tool,
            tool_response,
            user_msg2,
        ]

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

    def test_file_metadata_for_tool_produces_message(self) -> None:
        """When context_files has file_metadata_for_tool, a metadata listing
        message should be injected into the history."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg = create_message("Analyze the spreadsheet", MessageType.USER, 5)

        context_files = ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=0,
            file_metadata_for_tool=[
                FileToolMetadata(
                    file_id="xlsx-1",
                    filename="report.xlsx",
                    approx_char_count=100000,
                ),
            ],
        )

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=[user_msg],
            reminder_message=None,
            context_files=context_files,
            available_tokens=1000,
            token_counter=_simple_token_counter,
            available_tool_names={"read_file"},
        )

        # Should have: system, tool_metadata_message, user
        assert len(result) == 3
        metadata_msg = result[1]
        assert metadata_msg.message_type == MessageType.USER
        assert "report.xlsx" in metadata_msg.message
        # read_file is offered, so the listing carries the id it consumes.
        assert "xlsx-1" in metadata_msg.message

    def test_metadata_only_and_text_files_both_present(self) -> None:
        """When both text content and tool metadata are present, both messages
        should appear in the history."""
        system_prompt = create_message("System", MessageType.SYSTEM, 10)
        user_msg = create_message("Summarize everything", MessageType.USER, 5)

        context_files = ExtractedContextFiles(
            file_texts=["Text file content here"],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=100,
            file_metadata=[
                ContextFileMetadata(
                    file_id="txt-1",
                    filename="notes.txt",
                    file_content="Text file content here",
                ),
            ],
            uncapped_token_count=100,
            file_metadata_for_tool=[
                FileToolMetadata(
                    file_id="xlsx-1",
                    filename="data.xlsx",
                    approx_char_count=50000,
                ),
            ],
        )

        result = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=[user_msg],
            reminder_message=None,
            context_files=context_files,
            available_tokens=2000,
            token_counter=_simple_token_counter,
        )

        # Should have: system, context_files_message, tool_metadata_message, user
        assert len(result) == 4
        # Context files message (text content)
        assert "documents" in result[1].message
        assert "Text file content here" in result[1].message
        # Tool metadata message
        assert "data.xlsx" in result[2].message
        assert result[3] == user_msg


def _simple_token_counter(text: str) -> int:
    """Approximate token counter for tests (~4 chars per token)."""
    return max(1, len(text) // 4)


def _make_file_metadata(
    file_id: str,
    filename: str,
    approx_chars: int = 50_000,
    staged_for_tools: bool = True,
) -> FileToolMetadata:
    return FileToolMetadata(
        file_id=file_id,
        filename=filename,
        approx_char_count=approx_chars,
        staged_for_tools=staged_for_tools,
    )


class TestNonVisionImageBudgeting:
    """When a non-vision model replays history images as text markers, the
    truncation budget must charge the marker cost, not the stored image token
    cost — otherwise history that actually fits gets evicted."""

    @staticmethod
    def _image_user_msg() -> ChatMessageSimple:
        image = ChatLoadedFile(
            file_id="img0",
            content=b"",
            file_type=ChatFileType.IMAGE,
            filename="img0.png",
            content_text=None,
            token_count=500,
        )
        return ChatMessageSimple(
            message="look at this",
            token_count=505,
            message_type=MessageType.USER,
            image_files=[image],
            image_token_count=500,
        )

    def _construct(self, replay_as_markers: bool) -> list[ChatMessageSimple]:
        simple_chat_history = [
            self._image_user_msg(),
            create_message("Response", MessageType.ASSISTANT, 5),
            create_message("Follow-up", MessageType.USER, 5),
        ]
        return construct_message_history(
            system_prompt=None,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=create_context_files(),
            available_tokens=100,
            token_counter=lambda _: 10,
            image_files_replayed_as_markers=replay_as_markers,
        )

    def test_marker_cost_keeps_the_image_message(self) -> None:
        result = self._construct(replay_as_markers=True)
        assert [m.message for m in result] == [
            "look at this",
            "Response",
            "Follow-up",
        ]

    def test_vision_output_budget_keeps_stored_image_cost(self) -> None:
        assert count_message_replay_tokens(self._image_user_msg()) == 505

    def test_image_marker_budget_without_tokenizer(self) -> None:
        assert (
            count_message_replay_tokens(
                self._image_user_msg(), image_files_replayed_as_markers=True
            )
            == 45
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
    lightweight metadata message pointing the LLM at whichever retrieval path
    the deployment actually offers (read_file or internal search).

    This class covers a request that was given the FileReaderTool.
    TestForgottenFilesWithoutFileReader covers one that was not.
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
            available_tool_names={FILE_READER_TOOL_NAME},
        )

    @staticmethod
    def _find_forgotten_message(
        result: list[ChatMessageSimple],
    ) -> ChatMessageSimple | None:
        """Find the forgotten-files metadata message in the result, if any.

        Matches the file listing rather than the header: the header names
        read_file or internal search depending on the deployment.
        """
        for msg in result:
            if 'filename="' in msg.message:
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
        assert forgotten is None, (
            "Should not inject forgotten-files when file is in context"
        )
        # The file message itself should still be present
        assert any(m.file_id == "file-abc" for m in result)

    # ------------------------------------------------------------------
    # Case 2: file message dropped by context-window truncation
    # ------------------------------------------------------------------

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
        assert forgotten is not None, (
            "Orphaned file metadata should trigger forgotten-files message"
        )
        assert "moby_dick.txt" in forgotten.message
        assert "file-abc" in forgotten.message

    # ------------------------------------------------------------------
    # Case 4: multiple files — one survives, one is dropped
    # ------------------------------------------------------------------

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
        assert forgotten is None, (
            "No forgotten-files message when metadata dict is None"
        )

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
            assert forgotten is not None, (
                f"Turn {turn}: forgotten-files message must persist every turn"
            )
            assert "moby_dick.txt" in forgotten.message


def _notice_for_dropped_file(
    available_tool_names: set[str] | None = None,
    staged_for_tools: bool = True,
) -> ChatMessageSimple:
    """Truncate one oversized attachment out of context and return the notice."""
    file_meta = _make_file_metadata(
        "file-abc", "sustainability.pdf", staged_for_tools=staged_for_tools
    )
    file_msg = create_message("x" * 2000, MessageType.USER, 500)
    file_msg.file_id = "file-abc"

    result = construct_message_history(
        system_prompt=create_message("system", MessageType.SYSTEM, 5),
        custom_agent_prompt=None,
        simple_chat_history=[
            create_message("Got it", MessageType.ASSISTANT, 10),
            create_message("Summarize it", MessageType.USER, 10),
        ],
        reminder_message=None,
        context_files=create_context_files(),
        # Too tight for the 500-token file message.
        available_tokens=100,
        token_counter=_simple_token_counter,
        all_injected_file_metadata={"file-abc": file_meta},
        available_tool_names=available_tool_names,
    )
    notice = next((m for m in result if 'filename="' in m.message), None)
    assert notice is not None, "dropped file should still produce a notice"
    return notice


class TestForgottenFilesWithoutFileReader:
    """The forgotten-files notice must not name read_file where the tool is absent.

    FileReaderTool is only attached when the vector DB is disabled (see
    ``FileReaderTool.is_available``), but the notice was emitted whenever the
    persona had the tool row attached. On a vector-DB deployment that told the
    model to call a tool it had never been given, so it reported read_file as
    unavailable and fell back to guessing or web-searching the document.
    """

    def _build_with_dropped_file(
        self, available_tool_names: set[str] | None = None
    ) -> ChatMessageSimple:
        return _notice_for_dropped_file(available_tool_names or {SearchTool.NAME})

    def test_notice_does_not_name_read_file(self) -> None:
        notice = self._build_with_dropped_file()
        assert "read_file" not in notice.message

    def test_notice_points_at_internal_search(self) -> None:
        notice = self._build_with_dropped_file()
        assert "internal search" in notice.message
        assert "sustainability.pdf" in notice.message

    def test_notice_forbids_guessing_and_web_search(self) -> None:
        """The failure this replaced was the model web-searching the document."""
        notice = self._build_with_dropped_file()
        assert "Do not guess" in notice.message
        assert "search the web" in notice.message

    def test_notice_omits_the_file_id(self) -> None:
        """The file_id only means something to read_file; internal search takes
        a query, so showing the UUID invites another dead end.
        """
        notice = self._build_with_dropped_file()
        assert "file-abc" not in notice.message


class TestForgottenFilesNoticeFollowsConstructedTools:
    """The notice names a tool only when this request actually received it.

    Deployment config alone is not enough: internal search can be missing on a
    vector-DB deployment when the persona omits it, ``allowed_tool_ids``
    excludes it, or the search usage setting disables it.
    """

    def test_names_read_file_when_the_request_has_it(self) -> None:
        notice = _notice_for_dropped_file({"read_file", "internal_search"})
        assert "read_file" in notice.message
        # read_file is the one consumer of the UUID, so it comes back with it.
        assert "file-abc" in notice.message

    def test_names_internal_search_when_only_search_is_offered(self) -> None:
        notice = _notice_for_dropped_file({"internal_search"})
        assert "internal search" in notice.message
        assert "read_file" not in notice.message

    def test_names_python_when_it_is_the_only_reader(self) -> None:
        """The python tool is handed the files themselves, so an evicted file is
        still readable there. Calling it unreadable makes the model refuse work
        it could actually do.
        """
        notice = _notice_for_dropped_file({"run_python"})
        assert "python tool" in notice.message
        assert "no tool here can read them" not in notice.message
        assert "sustainability.pdf" in notice.message

    def test_python_tier_omits_the_file_id(self) -> None:
        """The UUID is a read_file identifier; PythonTool never sees it."""
        notice = _notice_for_dropped_file({"run_python"})
        assert "file-abc" not in notice.message

    def test_python_tier_does_not_promise_an_exact_path(self) -> None:
        """PythonTool normalizes and de-duplicates names at staging time, so the
        notice cannot know the sandbox path. It must not assert one.
        """
        notice = _notice_for_dropped_file({"run_python"})
        assert "by filename" not in notice.message
        assert "listing the working directory" in notice.message

    def test_python_tier_skipped_for_summary_truncated_files(self) -> None:
        """Summary truncation filters the message out of chat_history before
        load_all_chat_files runs, so those bytes never reach the python tool.
        Advertising python for them points the model at nothing.
        """
        notice = _notice_for_dropped_file({"run_python"}, staged_for_tools=False)
        assert "python tool" not in notice.message
        assert "no tool here can read them" in notice.message
        assert "sustainability.pdf" in notice.message

    def test_search_wins_over_python_when_both_are_offered(self) -> None:
        """Indexed retrieval beats writing code to parse an oversized file."""
        notice = _notice_for_dropped_file({"internal_search", "run_python"})
        assert "internal search" in notice.message
        assert "python tool" not in notice.message

    def test_python_only_persona_reaches_the_python_tier(self) -> None:
        """Regression for a real deployment: read_file is attached to the
        persona but filtered out by availability, internal_search was never
        attached, and run_python is live.
        """
        notice = _notice_for_dropped_file(
            {"generate_image", "web_search", "run_python", "open_url"}
        )
        assert "python tool" in notice.message
        assert "read_file" not in notice.message
        assert "internal search" not in notice.message

    def test_names_no_tool_when_the_request_has_no_reader(self) -> None:
        """No read_file, no search, no python — do not promise anything."""
        notice = _notice_for_dropped_file({"generate_image", "web_search"})
        assert "read_file" not in notice.message
        assert "internal search" not in notice.message
        assert "python tool" not in notice.message
        assert "no tool here can read them" in notice.message

    def test_still_forbids_guessing_when_no_tool_is_offered(self) -> None:
        notice = _notice_for_dropped_file({"generate_image", "web_search"})
        assert "Do not guess" in notice.message
        assert "search the web" in notice.message
        assert "sustainability.pdf" in notice.message

    def test_python_tier_also_forbids_guessing_and_web_search(self) -> None:
        notice = _notice_for_dropped_file({"run_python"})
        assert "Do not guess" in notice.message
        assert "search the web" in notice.message


class TestEmptyLlmResponseClassification:
    def _make_llm(self, provider: str = "openai", model: str = "gpt-5.2") -> Mock:
        llm = Mock()
        llm.config = LLMConfig(
            model_provider=provider,
            model_name=model,
            temperature=0.0,
            max_input_tokens=4096,
        )
        return llm

    def test_openai_empty_stream_is_classified_as_budget_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "onyx.chat.chat_agent.is_true_openai_model", lambda *_: True
        )

        err = _build_empty_llm_response_error(
            llm=self._make_llm(),
            response=pm.ModelResponse(parts=[]),
            tool_choice=ToolChoiceOptions.AUTO,
        )

        assert isinstance(err, EmptyLLMResponseError)
        assert err.error_code == "BUDGET_EXCEEDED"
        assert err.is_retryable is False
        assert "quota" in err.client_error_msg.lower()

    def test_reasoning_only_response_uses_generic_empty_response_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "onyx.chat.chat_agent.is_true_openai_model", lambda *_: True
        )

        err = _build_empty_llm_response_error(
            llm=self._make_llm(),
            response=pm.ModelResponse(parts=[pm.ThinkingPart("scratchpad only")]),
            tool_choice=ToolChoiceOptions.AUTO,
        )

        assert isinstance(err, EmptyLLMResponseError)
        assert err.error_code == "EMPTY_LLM_RESPONSE"
        assert err.is_retryable is True
        assert "quota" not in err.client_error_msg.lower()

    def test_refusal_finish_reason_is_classified_as_model_refusal(self) -> None:
        """Anthropic refusal: HTTP 200, stop_reason="refusal" (normalized by
        LiteLLM to "content_filter"), no text or tool calls. Must surface as a
        refusal, not a generic empty-stream error."""
        err = _build_empty_llm_response_error(
            llm=self._make_llm(provider="anthropic", model="claude-fable-5"),
            response=pm.ModelResponse(parts=[], finish_reason="content_filter"),
            tool_choice=ToolChoiceOptions.AUTO,
        )

        assert isinstance(err, EmptyLLMResponseError)
        assert err.error_code == "MODEL_REFUSAL"
        assert err.is_retryable is False
        assert err.finish_reason == "content_filter"
        assert "declined" in err.client_error_msg.lower()
        # Anthropic-specific fallback suggestion from the issue.
        assert "Claude Opus 4.8" in err.client_error_msg

    @pytest.mark.parametrize("finish_reason", sorted(_REFUSAL_FINISH_REASONS))
    def test_refusal_finish_reasons_take_precedence_over_budget_heuristic(
        self, monkeypatch: pytest.MonkeyPatch, finish_reason: str
    ) -> None:
        """Native provider refusal reasons may pass through gateways unchanged."""
        monkeypatch.setattr(
            "onyx.chat.chat_agent.is_true_openai_model", lambda *_: True
        )

        err = _build_empty_llm_response_error(
            llm=self._make_llm(),
            response=pm.ModelResponse(
                parts=[], finish_reason=cast(pm.FinishReason, finish_reason)
            ),
            tool_choice=ToolChoiceOptions.AUTO,
        )

        assert err.error_code == "MODEL_REFUSAL"
        assert err.is_retryable is False
        assert err.finish_reason == finish_reason
        assert "Claude Opus 4.8" not in err.client_error_msg


class TestSelectReminderText:
    """The open_url nudge must be suppressed when the open_url tool is disabled,
    otherwise the model is told to call a tool it doesn't have (confusing
    "open_url is not available" replies)."""

    def _select(self, **overrides: Any) -> str | None:
        kwargs: dict[str, Any] = {
            "ran_image_gen": False,
            "just_ran_web_search": False,
            "has_open_url_tool": True,
            "out_of_cycles": False,
            "persona_task_prompt": None,
            "include_citation_reminder": False,
            "include_file_reminder": False,
        }
        kwargs.update(overrides)
        return select_reminder_text(**kwargs)

    def test_open_url_reminder_when_tool_available(self) -> None:
        result = self._select(just_ran_web_search=True, has_open_url_tool=True)
        assert result == OPEN_URL_REMINDER

    def test_no_open_url_reminder_when_tool_disabled(self) -> None:
        """Web search ran but open_url is disabled -> fall back, never nudge open_url."""
        result = self._select(just_ran_web_search=True, has_open_url_tool=False)
        assert result != OPEN_URL_REMINDER
        assert result is None  # nothing else to remind about in this scenario

    def test_open_url_reminder_suppressed_on_last_cycle(self) -> None:
        result = self._select(
            just_ran_web_search=True, has_open_url_tool=True, out_of_cycles=True
        )
        assert result != OPEN_URL_REMINDER

    def test_image_gen_reminder_takes_precedence(self) -> None:
        result = self._select(
            ran_image_gen=True, just_ran_web_search=True, has_open_url_tool=True
        )
        assert result == IMAGE_GEN_REMINDER
