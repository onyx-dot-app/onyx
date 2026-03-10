"""Tests for LLM span recording utilities."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.llm.model_response import ChatCompletionMessageToolCall
from onyx.llm.model_response import Choice
from onyx.llm.model_response import FunctionCall as ModelResponseFunctionCall
from onyx.llm.model_response import Message
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import Usage
from onyx.llm.models import FunctionCall
from onyx.llm.models import ToolCall
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.llm_utils import record_llm_response
from onyx.tracing.llm_utils import record_llm_span_output


@pytest.fixture
def mock_span() -> MagicMock:
    """Create a mock span with GenerationSpanData."""
    span = MagicMock()
    span.span_data = GenerationSpanData()
    return span


class TestRecordLlmResponse:
    """Tests for record_llm_response function."""

    def test_records_content_from_response(self, mock_span: MagicMock) -> None:
        """Test that content is correctly extracted and recorded."""
        response = ModelResponse(
            id="test-id",
            created="2024-01-01",
            choice=Choice(
                message=Message(content="Hello, world!", role="assistant"),
            ),
        )

        record_llm_response(mock_span, response)

        assert mock_span.span_data.output == [
            {"role": "assistant", "content": "Hello, world!"}
        ]

    def test_records_reasoning_from_response(self, mock_span: MagicMock) -> None:
        """Test that reasoning/extended thinking is recorded."""
        response = ModelResponse(
            id="test-id",
            created="2024-01-01",
            choice=Choice(
                message=Message(
                    content="The answer is 42.",
                    role="assistant",
                    reasoning_content="Let me think step by step...",
                ),
            ),
        )

        record_llm_response(mock_span, response)

        assert mock_span.span_data.output == [
            {"role": "assistant", "content": "The answer is 42."}
        ]
        assert mock_span.span_data.reasoning == "Let me think step by step..."

    def test_records_tool_calls_from_response(self, mock_span: MagicMock) -> None:
        """Test that tool calls are correctly extracted and recorded."""
        tool_call = ChatCompletionMessageToolCall(
            id="call-123",
            type="function",
            function=ModelResponseFunctionCall(
                name="search_documents",
                arguments='{"query": "test query"}',
            ),
        )
        response = ModelResponse(
            id="test-id",
            created="2024-01-01",
            choice=Choice(
                message=Message(
                    content=None,
                    role="assistant",
                    tool_calls=[tool_call],
                ),
            ),
        )

        record_llm_response(mock_span, response)

        output = mock_span.span_data.output
        assert len(output) == 1
        assert output[0]["role"] == "assistant"
        assert "tool_calls" in output[0]
        assert len(output[0]["tool_calls"]) == 1
        assert output[0]["tool_calls"][0]["id"] == "call-123"
        assert output[0]["tool_calls"][0]["function"]["name"] == "search_documents"

    def test_records_usage_from_response(self, mock_span: MagicMock) -> None:
        """Test that usage metrics are correctly recorded."""
        response = ModelResponse(
            id="test-id",
            created="2024-01-01",
            choice=Choice(
                message=Message(content="Test", role="assistant"),
            ),
            usage=Usage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cache_creation_input_tokens=10,
                cache_read_input_tokens=20,
            ),
        )

        record_llm_response(mock_span, response)

        assert mock_span.span_data.usage is not None
        assert mock_span.span_data.usage["input_tokens"] == 100
        assert mock_span.span_data.usage["output_tokens"] == 50
        assert mock_span.span_data.usage["total_tokens"] == 150
        assert mock_span.span_data.usage["cache_read_input_tokens"] == 20
        assert mock_span.span_data.usage["cache_creation_input_tokens"] == 10

    def test_handles_none_content(self, mock_span: MagicMock) -> None:
        """Test that None content is handled (e.g., tool-only response)."""
        response = ModelResponse(
            id="test-id",
            created="2024-01-01",
            choice=Choice(
                message=Message(content=None, role="assistant"),
            ),
        )

        record_llm_response(mock_span, response)

        # Content should not be in output dict when None
        assert mock_span.span_data.output == [{"role": "assistant"}]

    def test_handles_no_usage(self, mock_span: MagicMock) -> None:
        """Test that missing usage is handled gracefully."""
        response = ModelResponse(
            id="test-id",
            created="2024-01-01",
            choice=Choice(
                message=Message(content="Test", role="assistant"),
            ),
            usage=None,
        )

        record_llm_response(mock_span, response)

        # Usage should remain None/unset
        assert mock_span.span_data.usage is None

    def test_records_all_fields_together(self, mock_span: MagicMock) -> None:
        """Test recording a response with all fields present."""
        tool_call = ChatCompletionMessageToolCall(
            id="call-456",
            type="function",
            function=ModelResponseFunctionCall(
                name="analyze",
                arguments='{"text": "sample"}',
            ),
        )
        response = ModelResponse(
            id="test-id",
            created="2024-01-01",
            choice=Choice(
                message=Message(
                    content="Here's my analysis:",
                    role="assistant",
                    reasoning_content="I need to think about this carefully...",
                    tool_calls=[tool_call],
                ),
            ),
            usage=Usage(
                prompt_tokens=200,
                completion_tokens=100,
                total_tokens=300,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=50,
            ),
        )

        record_llm_response(mock_span, response)

        # Check output
        output = mock_span.span_data.output
        assert len(output) == 1
        assert output[0]["role"] == "assistant"
        assert output[0]["content"] == "Here's my analysis:"
        assert len(output[0]["tool_calls"]) == 1

        # Check reasoning
        assert (
            mock_span.span_data.reasoning == "I need to think about this carefully..."
        )

        # Check usage
        assert mock_span.span_data.usage["input_tokens"] == 200
        assert mock_span.span_data.usage["output_tokens"] == 100


class TestRecordLlmSpanOutput:
    """Tests for record_llm_span_output function (streaming scenarios)."""

    def test_records_string_output(self, mock_span: MagicMock) -> None:
        """Test recording a simple string output."""
        record_llm_span_output(mock_span, "Hello, world!")

        assert mock_span.span_data.output == [
            {"role": "assistant", "content": "Hello, world!"}
        ]

    def test_records_none_output(self, mock_span: MagicMock) -> None:
        """Test recording None output."""
        record_llm_span_output(mock_span, None)

        assert mock_span.span_data.output == [{"role": "assistant", "content": None}]

    def test_records_sequence_output(self, mock_span: MagicMock) -> None:
        """Test recording a sequence of message dicts."""
        messages: list[dict[str, Any]] = [
            {"role": "assistant", "content": "Part 1"},
            {"role": "assistant", "content": "Part 2"},
        ]

        record_llm_span_output(mock_span, messages)

        assert mock_span.span_data.output == messages

    def test_records_usage(self, mock_span: MagicMock) -> None:
        """Test recording usage information."""
        usage = MagicMock()
        usage.prompt_tokens = 50
        usage.completion_tokens = 25
        usage.total_tokens = 75
        usage.cache_read_input_tokens = 10
        usage.cache_creation_input_tokens = 5

        record_llm_span_output(mock_span, "Test output", usage=usage)

        assert mock_span.span_data.usage is not None
        assert mock_span.span_data.usage["input_tokens"] == 50
        assert mock_span.span_data.usage["output_tokens"] == 25

    def test_records_reasoning(self, mock_span: MagicMock) -> None:
        """Test recording reasoning content."""
        record_llm_span_output(
            mock_span, "Final answer", reasoning="Step by step thinking..."
        )

        assert mock_span.span_data.reasoning == "Step by step thinking..."

    def test_records_tool_calls(self, mock_span: MagicMock) -> None:
        """Test recording tool calls in streaming scenario."""
        tool_calls = [
            ToolCall(
                id="call-789",
                type="function",
                function=FunctionCall(
                    name="get_weather",
                    arguments='{"location": "NYC"}',
                ),
            )
        ]

        record_llm_span_output(mock_span, "Checking weather...", tool_calls=tool_calls)

        output = mock_span.span_data.output
        assert len(output) == 1
        assert output[0]["content"] == "Checking weather..."
        assert "tool_calls" in output[0]
        assert len(output[0]["tool_calls"]) == 1
        assert output[0]["tool_calls"][0]["id"] == "call-789"

    def test_records_tool_calls_with_none_output(self, mock_span: MagicMock) -> None:
        """Test recording tool calls when output is None."""
        tool_calls = [
            ToolCall(
                id="call-abc",
                type="function",
                function=FunctionCall(
                    name="search",
                    arguments='{"q": "test"}',
                ),
            )
        ]

        record_llm_span_output(mock_span, None, tool_calls=tool_calls)

        output = mock_span.span_data.output
        assert len(output) == 1
        assert output[0]["content"] is None
        assert len(output[0]["tool_calls"]) == 1

    def test_records_all_streaming_fields(self, mock_span: MagicMock) -> None:
        """Test recording all fields in streaming scenario."""
        usage = MagicMock()
        usage.prompt_tokens = 100
        usage.completion_tokens = 50
        usage.total_tokens = 150
        usage.cache_read_input_tokens = 0
        usage.cache_creation_input_tokens = 0

        tool_calls = [
            ToolCall(
                id="call-xyz",
                type="function",
                function=FunctionCall(
                    name="calculator",
                    arguments='{"expr": "2+2"}',
                ),
            )
        ]

        record_llm_span_output(
            mock_span,
            output="Computing...",
            usage=usage,
            reasoning="Let me calculate this.",
            tool_calls=tool_calls,
        )

        # Check all fields
        output = mock_span.span_data.output
        assert output[0]["content"] == "Computing..."
        assert len(output[0]["tool_calls"]) == 1
        assert mock_span.span_data.reasoning == "Let me calculate this."
        assert mock_span.span_data.usage["input_tokens"] == 100
