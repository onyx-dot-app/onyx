"""
External dependency unit tests for Python tool.

These tests run against a real Code Interpreter service (no mocking of the service).
They verify code execution, error handling, timeout behavior, and file generation.

Requirements:
- CODE_INTERPRETER_BASE_URL must be configured and point to a running service
- Tests use minimal mocking - only mock run_context infrastructure and db lookups
- File store operations execute for real (files are saved and read back)
"""

import asyncio
import json
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from agents import RunContextWrapper
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from onyx.chat.turn.models import ChatTurnContext
from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.file_store.utils import get_default_file_store
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PythonToolDelta
from onyx.server.query_and_chat.streaming_models import PythonToolStart
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations_v2.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_implementations_v2.python import _python_execution_core
from onyx.tools.tool_implementations_v2.python import python
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmPythonExecutionResult,
)


@pytest.fixture
def mock_run_context() -> RunContextWrapper[ChatTurnContext]:
    """Create a mock run context for testing."""
    # Create mock emitter
    mock_emitter = Mock()
    mock_emitter.emit = Mock()

    # Create mock run dependencies
    mock_dependencies = Mock()
    mock_dependencies.emitter = mock_emitter
    mock_dependencies.db_session = Mock()

    # Create mock context
    mock_context = Mock(spec=ChatTurnContext)
    mock_context.current_run_step = 0
    mock_context.run_dependencies = mock_dependencies
    mock_context.iteration_instructions = []
    mock_context.global_iteration_responses = []
    mock_context.chat_files = []

    # Create run context wrapper
    run_context = Mock(spec=RunContextWrapper)
    run_context.context = mock_context

    return run_context


@pytest.fixture
def code_interpreter_client() -> CodeInterpreterClient:
    """Create a real Code Interpreter client for testing."""
    if not CODE_INTERPRETER_BASE_URL:
        pytest.skip("CODE_INTERPRETER_BASE_URL not configured")
    return CodeInterpreterClient()


def test_python_execution_basic(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
) -> None:
    """Test basic Python execution with simple code."""
    code = 'print("Hello, World!")'

    # Mock get_tool_by_name
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        mock_tool = Mock()
        mock_tool.id = 1
        mock_get_tool.return_value = mock_tool

        # Execute code
        result = _python_execution_core(mock_run_context, code, code_interpreter_client)

    # Verify result
    assert isinstance(result, LlmPythonExecutionResult)
    assert "Hello, World!" in result.stdout
    assert result.stderr == ""
    assert result.exit_code == 0
    assert not result.timed_out
    assert len(result.generated_files) == 0

    # Verify context was updated
    # Note: @tool_accounting increments current_run_step from 0 to 1 before execution
    assert len(mock_run_context.context.iteration_instructions) == 1
    instruction = mock_run_context.context.iteration_instructions[0]
    assert instruction.iteration_nr == 1
    assert instruction.plan and "Python" in instruction.plan

    assert len(mock_run_context.context.global_iteration_responses) == 1
    answer = mock_run_context.context.global_iteration_responses[0]
    assert answer.tool == "PythonTool"
    assert "Hello, World!" in answer.answer

    # Verify streaming packets were emitted
    mock_emitter = mock_run_context.context.run_dependencies.emitter
    emitter_calls = mock_emitter.emit.call_args_list  # type: ignore
    assert len(emitter_calls) >= 2  # At least start and delta

    # Check for PythonToolStart packet
    start_packets = [
        call[0][0]
        for call in emitter_calls
        if isinstance(call[0][0].obj, PythonToolStart)
    ]
    assert len(start_packets) == 1

    # Check for PythonToolDelta packet
    delta_packets = [
        call[0][0]
        for call in emitter_calls
        if isinstance(call[0][0].obj, PythonToolDelta)
    ]
    assert len(delta_packets) >= 1
    assert "Hello, World!" in delta_packets[0].obj.stdout


def test_python_execution_with_syntax_error(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
) -> None:
    """Test Python execution with syntax error."""
    code = "print('missing closing quote"

    # Mock get_tool_by_name
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        mock_tool = Mock()
        mock_tool.id = 1
        mock_get_tool.return_value = mock_tool

        # Execute code
        result = _python_execution_core(mock_run_context, code, code_interpreter_client)

    # Verify error result
    assert isinstance(result, LlmPythonExecutionResult)
    assert result.stdout == ""
    assert len(result.stderr) > 0
    assert "SyntaxError" in result.stderr or "unterminated" in result.stderr.lower()
    assert result.exit_code != 0
    assert not result.timed_out
    assert result.error is not None or len(result.stderr) > 0
    assert len(result.generated_files) == 0


def test_python_execution_with_runtime_error(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
) -> None:
    """Test Python execution with runtime error."""
    code = """
x = 10
y = 0
result = x / y  # Division by zero
print(result)
"""

    # Mock get_tool_by_name
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        mock_tool = Mock()
        mock_tool.id = 1
        mock_get_tool.return_value = mock_tool

        # Execute code
        result = _python_execution_core(mock_run_context, code, code_interpreter_client)

    # Verify error result
    assert isinstance(result, LlmPythonExecutionResult)
    assert result.exit_code != 0
    assert "ZeroDivisionError" in result.stderr or "division" in result.stderr.lower()
    assert result.error is not None or len(result.stderr) > 0


def test_python_execution_timeout(
    mock_run_context: RunContextWrapper[ChatTurnContext],
) -> None:
    """Test execution timeout handling."""
    # Code that will run longer than the timeout
    code = """
import time
time.sleep(10)
print("Should not reach here")
"""

    # Create client with short timeout (override via execute method)
    if not CODE_INTERPRETER_BASE_URL:
        pytest.skip("CODE_INTERPRETER_BASE_URL not configured")

    client = CodeInterpreterClient()

    # Mock get_tool_by_name
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        mock_tool = Mock()
        mock_tool.id = 1
        mock_get_tool.return_value = mock_tool

        # Mock the config to use a short timeout
        with patch(
            "onyx.tools.tool_implementations_v2.python.CODE_INTERPRETER_DEFAULT_TIMEOUT_MS",
            1000,
        ):
            # Execute code
            result = _python_execution_core(mock_run_context, code, client)

    # Verify timeout result
    assert isinstance(result, LlmPythonExecutionResult)
    assert result.timed_out


def test_python_execution_file_generation(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
    db_session: Session,  # Needed to initialize DB engine for file_store
) -> None:
    """Test file generation and retrieval."""
    code = """
import csv

# Create a CSV file
with open('test_output.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Name', 'Age', 'City'])
    writer.writerow(['Alice', '30', 'New York'])
    writer.writerow(['Bob', '25', 'San Francisco'])

print("CSV file created successfully")
"""

    # Mock only get_tool_by_name (database lookup)
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        mock_tool = Mock()
        mock_tool.id = 1
        mock_get_tool.return_value = mock_tool

        # Execute code - file store operations happen for real
        result = _python_execution_core(mock_run_context, code, code_interpreter_client)

    # Verify result
    assert isinstance(result, LlmPythonExecutionResult)
    assert result.exit_code == 0
    assert "CSV file created successfully" in result.stdout
    assert len(result.generated_files) == 1

    # Verify file metadata
    generated_file = result.generated_files[0]
    assert generated_file.filename == "test_output.csv"
    assert generated_file.file_link  # File link exists
    assert generated_file.file_link.startswith("http://localhost:3000/api/chat/file/")

    # Extract file_id from file_link
    file_id = generated_file.file_link.split("/")[-1]

    # Verify we can read the file back from the file store
    file_store = get_default_file_store()
    file_io = file_store.read_file(file_id)
    file_content = file_io.read()

    # Verify file content
    assert b"Name,Age,City" in file_content
    assert b"Alice,30,New York" in file_content
    assert b"Bob,25,San Francisco" in file_content

    # Verify iteration answer includes file_ids
    assert len(mock_run_context.context.global_iteration_responses) == 1
    answer = mock_run_context.context.global_iteration_responses[0]
    assert answer.file_ids == [file_id]


def test_python_execution_with_matplotlib(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
    db_session: Session,  # Needed to initialize DB engine for file_store
) -> None:
    """Test matplotlib plot generation."""
    code = """
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

# Generate data
x = np.linspace(0, 10, 100)
y = np.sin(x)

# Create plot
plt.figure(figsize=(10, 6))
plt.plot(x, y)
plt.title('Sine Wave')
plt.xlabel('x')
plt.ylabel('sin(x)')
plt.grid(True)

# Save plot
plt.savefig('sine_wave.png')
print("Plot saved successfully")
"""

    # Mock only get_tool_by_name (database lookup)
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        mock_tool = Mock()
        mock_tool.id = 1
        mock_get_tool.return_value = mock_tool

        # Execute code - file store operations happen for real
        result = _python_execution_core(mock_run_context, code, code_interpreter_client)

    # Verify result
    assert isinstance(result, LlmPythonExecutionResult)
    assert result.exit_code == 0
    assert "Plot saved successfully" in result.stdout
    assert len(result.generated_files) == 1

    # Verify file metadata
    generated_file = result.generated_files[0]
    assert generated_file.filename == "sine_wave.png"
    assert ".png" in generated_file.filename

    # Extract file_id from file_link
    file_id = generated_file.file_link.split("/")[-1]

    # Verify we can read the file back from the file store
    file_store = get_default_file_store()
    file_io = file_store.read_file(file_id)
    file_content = file_io.read()

    # Verify the file is a valid PNG (check PNG magic bytes)
    # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
    assert file_content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(file_content) > 1000  # PNG should be substantial


def test_python_execution_context_updates(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
) -> None:
    """Test that run_context is properly updated."""
    code = 'print("Context update test")'

    # Mock get_tool_by_name
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        mock_tool = Mock()
        mock_tool.id = 42
        mock_get_tool.return_value = mock_tool

        # Set specific run step - will be incremented to 6 by @tool_accounting
        mock_run_context.context.current_run_step = 5

        # Execute code
        _python_execution_core(mock_run_context, code, code_interpreter_client)

    # Verify iteration_instructions was updated
    # Note: @tool_accounting increments from 5 to 6
    assert len(mock_run_context.context.iteration_instructions) == 1
    instruction = mock_run_context.context.iteration_instructions[0]
    assert instruction.iteration_nr == 6
    assert instruction.plan == "Executing Python code"
    assert instruction.purpose == "Running Python code"
    assert "secure environment" in instruction.reasoning

    # Verify global_iteration_responses was updated
    assert len(mock_run_context.context.global_iteration_responses) == 1
    answer = mock_run_context.context.global_iteration_responses[0]
    assert answer.tool == "PythonTool"
    assert answer.tool_id == 42
    assert answer.iteration_nr == 6
    assert answer.parallelization_nr == 0
    assert answer.question == "Execute Python code"
    assert answer.reasoning and "secure environment" in answer.reasoning
    assert "Context update test" in answer.answer
    assert answer.cited_documents == {}

    # Verify packets were emitted with correct index
    mock_emitter = mock_run_context.context.run_dependencies.emitter
    emitter_calls = mock_emitter.emit.call_args_list  # type: ignore
    for call in emitter_calls:
        packet = call[0][0]
        assert isinstance(packet, Packet)
        assert packet.ind == 6


def test_python_tool_availability_with_url_set(db_session: Session) -> None:
    """Test PythonTool.is_available() returns True when URL is configured."""
    with patch(
        "onyx.configs.app_configs.CODE_INTERPRETER_BASE_URL", "http://localhost:8000"
    ):
        assert PythonTool.is_available(db_session) is True


def test_python_tool_availability_without_url(db_session: Session) -> None:
    """Test PythonTool.is_available() returns False when URL is not configured."""
    with patch("onyx.configs.app_configs.CODE_INTERPRETER_BASE_URL", None):
        assert PythonTool.is_available(db_session) is False

    with patch("onyx.configs.app_configs.CODE_INTERPRETER_BASE_URL", ""):
        assert PythonTool.is_available(db_session) is False


def test_python_function_tool_wrapper(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
) -> None:
    """Test the @function_tool decorated python() wrapper function."""
    code = 'print("Testing function tool wrapper")'

    # Mock get_tool_by_name and patch CodeInterpreterClient to use our fixture
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        with patch(
            "onyx.tools.tool_implementations_v2.python.CodeInterpreterClient"
        ) as mock_client_class:
            mock_tool = Mock()
            mock_tool.id = 1
            mock_get_tool.return_value = mock_tool
            mock_client_class.return_value = code_interpreter_client

            # Call the function tool wrapper
            result_coro = python.on_invoke_tool(mock_run_context, json.dumps({"code": code}))  # type: ignore
            result_json: str = asyncio.run(result_coro)  # type: ignore

    # Verify result is JSON string
    assert isinstance(result_json, str)

    # Parse and verify result
    adapter = TypeAdapter(LlmPythonExecutionResult)
    result = adapter.validate_json(result_json)

    assert isinstance(result, LlmPythonExecutionResult)
    assert "Testing function tool wrapper" in result.stdout
    assert result.exit_code == 0


def test_python_execution_output_truncation(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
) -> None:
    """Test that large outputs are properly truncated."""
    # Generate code that produces output larger than truncation limit
    code = """
for i in range(10000):
    print(f"Line {i}: " + "x" * 100)
"""

    # Mock get_tool_by_name
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        # Set a small truncation limit for testing
        with patch(
            "onyx.tools.tool_implementations_v2.python.CODE_INTERPRETER_MAX_OUTPUT_LENGTH",
            5000,
        ):
            mock_tool = Mock()
            mock_tool.id = 1
            mock_get_tool.return_value = mock_tool

            # Execute code
            result = _python_execution_core(
                mock_run_context, code, code_interpreter_client
            )

    # Verify output was truncated
    assert len(result.stdout) <= 5000 + 200  # Allow for truncation message
    assert "output truncated" in result.stdout
    assert "characters omitted" in result.stdout


def test_python_execution_multiple_files(
    mock_run_context: RunContextWrapper[ChatTurnContext],
    code_interpreter_client: CodeInterpreterClient,
    db_session: Session,  # Needed to initialize DB engine for file_store
) -> None:
    """Test generation of multiple files."""
    code = """
# Create multiple files
with open('file1.txt', 'w') as f:
    f.write('Content of file 1')

with open('file2.txt', 'w') as f:
    f.write('Content of file 2')

with open('file3.txt', 'w') as f:
    f.write('Content of file 3')

print("Created 3 files")
"""

    # Mock only get_tool_by_name (database lookup)
    with patch(
        "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
    ) as mock_get_tool:
        mock_tool = Mock()
        mock_tool.id = 1
        mock_get_tool.return_value = mock_tool

        # Execute code - file store operations happen for real
        result = _python_execution_core(mock_run_context, code, code_interpreter_client)

    # Verify result
    assert isinstance(result, LlmPythonExecutionResult)
    assert result.exit_code == 0
    assert "Created 3 files" in result.stdout
    assert len(result.generated_files) == 3

    # Verify all files have unique IDs and proper metadata
    file_ids_result = [f.file_link.split("/")[-1] for f in result.generated_files]
    assert len(set(file_ids_result)) == 3  # All unique

    # Verify filenames
    filenames = [f.filename for f in result.generated_files]
    assert "file1.txt" in filenames
    assert "file2.txt" in filenames
    assert "file3.txt" in filenames

    # Verify we can read all files back from the file store
    file_store = get_default_file_store()

    for i, generated_file in enumerate(result.generated_files, 1):
        file_id = generated_file.file_link.split("/")[-1]
        file_io = file_store.read_file(file_id)
        file_content = file_io.read()
        expected_content = f"Content of file {i}".encode()
        assert expected_content in file_content


def test_python_execution_client_error_handling(
    mock_run_context: RunContextWrapper[ChatTurnContext],
) -> None:
    """Test error handling when Code Interpreter service fails."""
    code = 'print("Test")'

    # Create a client that will fail
    if not CODE_INTERPRETER_BASE_URL:
        pytest.skip("CODE_INTERPRETER_BASE_URL not configured")

    client = CodeInterpreterClient()

    # Mock the execute method to raise an exception
    with patch.object(client, "execute", side_effect=Exception("Service unavailable")):
        # Execute code
        result = _python_execution_core(mock_run_context, code, client)

    # Verify error result
    assert isinstance(result, LlmPythonExecutionResult)
    assert result.exit_code == -1
    error_msg = result.error or ""
    assert "Service unavailable" in result.stderr or "Service unavailable" in error_msg
    assert not result.timed_out
    assert len(result.generated_files) == 0

    # Verify error delta was emitted
    mock_emitter = mock_run_context.context.run_dependencies.emitter
    emitter_calls = mock_emitter.emit.call_args_list  # type: ignore
    delta_packets = [
        call[0][0]
        for call in emitter_calls
        if isinstance(call[0][0].obj, PythonToolDelta)
    ]
    assert len(delta_packets) >= 1
    assert "Service unavailable" in delta_packets[-1].obj.stderr


if __name__ == "__main__":
    # Run with: python -m pytest tests/external_dependency_unit/tools/test_python_tool.py -v
    pytest.main([__file__, "-v"])
