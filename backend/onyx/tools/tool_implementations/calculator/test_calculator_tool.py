"""Tests for the calculator tool."""

from unittest.mock import MagicMock

import pytest

from onyx.llm.interfaces import LLM
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.calculator.calculator_tool import (
    CALCULATOR_RESPONSE_ID,
    CalculatorTool,
)


@pytest.fixture
def calculator_tool():
    """Create a calculator tool instance for testing."""
    return CalculatorTool()


@pytest.fixture
def mock_llm():
    """Create a mock LLM for testing."""
    return MagicMock(spec=LLM)


def test_calculator_tool_properties(calculator_tool):
    """Test basic properties of the calculator tool."""
    assert calculator_tool.name == "run_calculator"
    assert calculator_tool.display_name == "Calculator Tool"
    assert "mathematical calculations" in calculator_tool.description.lower()


def test_tool_definition(calculator_tool):
    """Test the tool definition structure."""
    definition = calculator_tool.tool_definition()

    assert definition["type"] == "function"
    assert definition["function"]["name"] == "run_calculator"
    assert "expression" in definition["function"]["parameters"]["properties"]
    assert definition["function"]["parameters"]["required"] == ["expression"]


def test_basic_arithmetic_operations(calculator_tool):
    """Test basic arithmetic operations."""
    test_cases = [
        ("2 + 3", 5),
        ("10 - 4", 6),
        ("6 * 7", 42),
        ("15 / 3", 5.0),
        ("17 % 5", 2),
    ]

    for expression, expected in test_cases:
        responses = list(calculator_tool.run(expression=expression))
        assert len(responses) == 1
        assert responses[0].id == CALCULATOR_RESPONSE_ID
        assert responses[0].response == expected


def test_mathematical_functions(calculator_tool):
    """Test mathematical functions."""
    test_cases = [
        ("sqrt(16)", 4.0),
        ("pow(2, 3)", 8),
        ("abs(-5)", 5),
        ("round(3.7)", 4),
    ]

    for expression, expected in test_cases:
        responses = list(calculator_tool.run(expression=expression))
        assert len(responses) == 1
        assert responses[0].id == CALCULATOR_RESPONSE_ID
        assert responses[0].response == expected


def test_power_operator_conversion(calculator_tool):
    """Test that ^ is converted to ** for power operations."""
    responses = list(calculator_tool.run(expression="2^3"))
    assert len(responses) == 1
    assert responses[0].id == CALCULATOR_RESPONSE_ID
    assert responses[0].response == 8


def test_complex_expressions(calculator_tool):
    """Test more complex mathematical expressions."""
    test_cases = [
        ("(2 + 3) * 4", 20),
        ("sqrt(25) + pow(2, 3)", 13.0),
        ("abs(-10) / 2", 5.0),
        ("round(3.14159, 2)", 3.14),
    ]

    for expression, expected in test_cases:
        responses = list(calculator_tool.run(expression=expression))
        assert len(responses) == 1
        assert responses[0].id == CALCULATOR_RESPONSE_ID
        assert responses[0].response == expected


def test_error_handling(calculator_tool):
    """Test error handling for invalid expressions."""
    invalid_expressions = [
        "invalid_expression",
        "2 + ",
        "sqrt(-1)",  # This might work in some Python versions, but let's test
        "1 / 0",
        "undefined_function(5)",
    ]

    for expression in invalid_expressions:
        responses = list(calculator_tool.run(expression=expression))
        assert len(responses) == 1
        assert responses[0].id == CALCULATOR_RESPONSE_ID
        assert "Error calculating result" in str(responses[0].response)


def test_get_args_for_non_tool_calling_llm(calculator_tool, mock_llm):
    """Test argument extraction for non-tool-calling LLMs."""
    math_queries = [
        "What is 2 + 3?",
        "Calculate 10 * 5",
        "5 / 2 equals what?",
        "What's 15 % 4?",
    ]

    for query in math_queries:
        args = calculator_tool.get_args_for_non_tool_calling_llm(
            query=query, history=[], llm=mock_llm, force_run=False
        )
        assert args is not None
        assert "expression" in args
        assert args["expression"] == query

    non_math_queries = [
        "Hello, how are you?",
        "What is the weather like?",
        "Tell me about Python programming",
    ]

    for query in non_math_queries:
        args = calculator_tool.get_args_for_non_tool_calling_llm(
            query=query, history=[], llm=mock_llm, force_run=False
        )
        assert args is None


def test_build_tool_message_content(calculator_tool):
    """Test building tool message content from responses."""
    mock_response = ToolResponse(id=CALCULATOR_RESPONSE_ID, response=42)

    content = calculator_tool.build_tool_message_content(mock_response)
    assert content == "42"


def test_final_result(calculator_tool):
    """Test final result formatting."""
    mock_response = ToolResponse(id=CALCULATOR_RESPONSE_ID, response=42)

    result = calculator_tool.final_result(mock_response)
    assert result == {"result": 42}


def test_build_next_prompt_with_tool_calling(calculator_tool):
    """Test building next prompt for tool-calling LLMs."""
    from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
    from onyx.tools.message import ToolCallSummary

    prompt_builder = MagicMock(spec=AnswerPromptBuilder)
    tool_call_summary = MagicMock(spec=ToolCallSummary)
    tool_call_summary.tool_call_request = "test request"
    tool_call_summary.tool_call_result = "test result"
    tool_responses = []

    result = calculator_tool.build_next_prompt(
        prompt_builder=prompt_builder,
        tool_call_summary=tool_call_summary,
        tool_responses=tool_responses,
        using_tool_calling_llm=True,
    )

    assert prompt_builder.append_message.call_count == 2
    assert result == prompt_builder


def test_build_next_prompt_without_tool_calling(calculator_tool):
    """Test building next prompt for non-tool-calling LLMs."""
    from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
    from onyx.tools.message import ToolCallSummary

    prompt_builder = MagicMock(spec=AnswerPromptBuilder)
    tool_call_summary = MagicMock(spec=ToolCallSummary)
    tool_responses = []

    result = calculator_tool.build_next_prompt(
        prompt_builder=prompt_builder,
        tool_call_summary=tool_call_summary,
        tool_responses=tool_responses,
        using_tool_calling_llm=False,
    )

    prompt_builder.append_message.assert_not_called()
    assert result == prompt_builder
