# """
# External dependency unit tests for Python tool.

# These tests run against a real Code Interpreter service (no mocking of the service).
# They verify code execution, error handling, timeout behavior, and file generation.

# Requirements:
# - CODE_INTERPRETER_BASE_URL must be configured and point to a running service
# - Tests use minimal mocking - only mock run_context infrastructure and db lookups
# - File store operations execute for real (files are saved and read back)
# """

# import asyncio
# import io
# import json
# from unittest.mock import Mock
# from unittest.mock import patch

# import pytest
# from agents import RunContextWrapper
# from openpyxl import load_workbook
# from pydantic import TypeAdapter
# from sqlalchemy.orm import Session

# from onyx.chat.turn.models import ChatTurnContext
# from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
# from onyx.file_store.models import ChatFileType
# from onyx.file_store.models import InMemoryChatFile
# from onyx.file_store.utils import get_default_file_store
# from onyx.server.query_and_chat.streaming_models import Packet
# from onyx.server.query_and_chat.streaming_models import PythonToolDelta
# from onyx.server.query_and_chat.streaming_models import PythonToolStart
# from onyx.tools.tool_implementations.python.python_tool import PythonTool
# from onyx.tools.tool_implementations_v2.code_interpreter_client import (
#     CodeInterpreterClient,
# )
# from onyx.tools.tool_implementations_v2.python import _python_execution_core
# from onyx.tools.tool_implementations_v2.python import python
# from onyx.tools.tool_implementations_v2.tool_result_models import (
#     LlmPythonExecutionResult,
# )


# # Apply initialize_file_store fixture to all tests in this module
# pytestmark = pytest.mark.usefixtures("initialize_file_store")


# @pytest.fixture
# def mock_run_context() -> RunContextWrapper[ChatTurnContext]:
#     """Create a mock run context for testing."""
#     # Create mock emitter
#     mock_emitter = Mock()
#     mock_emitter.emit = Mock()

#     # Create mock run dependencies
#     mock_dependencies = Mock()
#     mock_dependencies.emitter = mock_emitter
#     mock_dependencies.db_session = Mock()

#     # Create mock context
#     mock_context = Mock(spec=ChatTurnContext)
#     mock_context.current_run_step = 0
#     mock_context.run_dependencies = mock_dependencies
#     mock_context.iteration_instructions = []
#     mock_context.global_iteration_responses = []
#     mock_context.chat_files = []

#     # Create run context wrapper
#     run_context = Mock(spec=RunContextWrapper)
#     run_context.context = mock_context

#     return run_context


# @pytest.fixture
# def code_interpreter_client() -> CodeInterpreterClient:
#     """Create a real Code Interpreter client for testing."""
#     if not CODE_INTERPRETER_BASE_URL:
#         pytest.skip("CODE_INTERPRETER_BASE_URL not configured")
#     return CodeInterpreterClient()


# def test_python_execution_basic(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
# ) -> None:
#     """Test basic Python execution with simple code."""
#     code = 'print("Hello, World!")'

#     # Mock get_tool_by_name
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Execute code
#         result = _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert "Hello, World!" in result.stdout
#     assert result.stderr == ""
#     assert result.exit_code == 0
#     assert not result.timed_out
#     assert len(result.generated_files) == 0

#     # Verify context was updated
#     # Note: @tool_accounting increments current_run_step from 0 to 1 before execution
#     assert len(mock_run_context.context.iteration_instructions) == 1
#     instruction = mock_run_context.context.iteration_instructions[0]
#     assert instruction.iteration_nr == 1
#     assert instruction.plan and "Python" in instruction.plan

#     assert len(mock_run_context.context.global_iteration_responses) == 1
#     answer = mock_run_context.context.global_iteration_responses[0]
#     assert answer.tool == "PythonTool"
#     assert "Hello, World!" in answer.answer

#     # Verify streaming packets were emitted
#     mock_emitter = mock_run_context.context.run_dependencies.emitter
#     emitter_calls = mock_emitter.emit.call_args_list  # type: ignore
#     assert len(emitter_calls) >= 2  # At least start and delta

#     # Check for PythonToolStart packet
#     start_packets = [
#         call[0][0]
#         for call in emitter_calls
#         if isinstance(call[0][0].obj, PythonToolStart)
#     ]
#     assert len(start_packets) == 1

#     # Check for PythonToolDelta packet
#     delta_packets = [
#         call[0][0]
#         for call in emitter_calls
#         if isinstance(call[0][0].obj, PythonToolDelta)
#     ]
#     assert len(delta_packets) >= 1
#     assert "Hello, World!" in delta_packets[0].obj.stdout


# def test_python_execution_with_syntax_error(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
# ) -> None:
#     """Test Python execution with syntax error."""
#     code = "print('missing closing quote"

#     # Mock get_tool_by_name
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Execute code
#         result = _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify error result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.stdout == ""
#     assert len(result.stderr) > 0
#     assert "SyntaxError" in result.stderr or "unterminated" in result.stderr.lower()
#     assert result.exit_code != 0
#     assert not result.timed_out
#     assert result.error is not None or len(result.stderr) > 0
#     assert len(result.generated_files) == 0


# def test_python_execution_with_runtime_error(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
# ) -> None:
#     """Test Python execution with runtime error."""
#     code = """
# x = 10
# y = 0
# result = x / y  # Division by zero
# print(result)
# """

#     # Mock get_tool_by_name
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Execute code
#         result = _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify error result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.exit_code != 0
#     assert "ZeroDivisionError" in result.stderr or "division" in result.stderr.lower()
#     assert result.error is not None or len(result.stderr) > 0


# def test_python_execution_timeout(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
# ) -> None:
#     """Test execution timeout handling."""
#     # Code that will run longer than the timeout
#     code = """
# import time
# time.sleep(10)
# print("Should not reach here")
# """

#     # Create client with short timeout (override via execute method)
#     if not CODE_INTERPRETER_BASE_URL:
#         pytest.skip("CODE_INTERPRETER_BASE_URL not configured")

#     client = CodeInterpreterClient()

#     # Mock get_tool_by_name
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Mock the config to use a short timeout
#         with patch(
#             "onyx.tools.tool_implementations_v2.python.CODE_INTERPRETER_DEFAULT_TIMEOUT_MS",
#             1000,
#         ):
#             # Execute code
#             result = _python_execution_core(mock_run_context, code, client)

#     # Verify timeout result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.timed_out


# def test_python_execution_file_generation(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
#     db_session: Session,  # Needed to initialize DB engine for file_store
# ) -> None:
#     """Test file generation and retrieval."""
#     code = """
# import csv

# # Create a CSV file
# with open('test_output.csv', 'w', newline='') as f:
#     writer = csv.writer(f)
#     writer.writerow(['Name', 'Age', 'City'])
#     writer.writerow(['Alice', '30', 'New York'])
#     writer.writerow(['Bob', '25', 'San Francisco'])

# print("CSV file created successfully")
# """

#     # Mock only get_tool_by_name (database lookup)
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Execute code - file store operations happen for real
#         result = _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.exit_code == 0
#     assert "CSV file created successfully" in result.stdout
#     assert len(result.generated_files) == 1

#     # Verify file metadata
#     generated_file = result.generated_files[0]
#     assert generated_file.filename == "test_output.csv"
#     assert generated_file.file_link  # File link exists
#     assert generated_file.file_link.startswith("http://localhost:3000/api/chat/file/")

#     # Extract file_id from file_link
#     file_id = generated_file.file_link.split("/")[-1]

#     # Verify we can read the file back from the file store
#     file_store = get_default_file_store()
#     file_io = file_store.read_file(file_id)
#     file_content = file_io.read()

#     # Verify file content
#     assert b"Name,Age,City" in file_content
#     assert b"Alice,30,New York" in file_content
#     assert b"Bob,25,San Francisco" in file_content

#     # Verify iteration answer includes file_ids
#     assert len(mock_run_context.context.global_iteration_responses) == 1
#     answer = mock_run_context.context.global_iteration_responses[0]
#     assert answer.file_ids == [file_id]


# def test_python_execution_with_matplotlib(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
#     db_session: Session,  # Needed to initialize DB engine for file_store
# ) -> None:
#     """Test matplotlib plot generation."""
#     code = """
# import matplotlib
# matplotlib.use('Agg')  # Use non-interactive backend
# import matplotlib.pyplot as plt
# import numpy as np

# # Generate data
# x = np.linspace(0, 10, 100)
# y = np.sin(x)

# # Create plot
# plt.figure(figsize=(10, 6))
# plt.plot(x, y)
# plt.title('Sine Wave')
# plt.xlabel('x')
# plt.ylabel('sin(x)')
# plt.grid(True)

# # Save plot
# plt.savefig('sine_wave.png')
# print("Plot saved successfully")
# """

#     # Mock only get_tool_by_name (database lookup)
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Execute code - file store operations happen for real
#         result = _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.exit_code == 0
#     assert "Plot saved successfully" in result.stdout
#     assert len(result.generated_files) == 1

#     # Verify file metadata
#     generated_file = result.generated_files[0]
#     assert generated_file.filename == "sine_wave.png"
#     assert ".png" in generated_file.filename

#     # Extract file_id from file_link
#     file_id = generated_file.file_link.split("/")[-1]

#     # Verify we can read the file back from the file store
#     file_store = get_default_file_store()
#     file_io = file_store.read_file(file_id)
#     file_content = file_io.read()

#     # Verify the file is a valid PNG (check PNG magic bytes)
#     # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
#     assert file_content[:8] == b"\x89PNG\r\n\x1a\n"
#     assert len(file_content) > 1000  # PNG should be substantial


# def test_python_execution_context_updates(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
# ) -> None:
#     """Test that run_context is properly updated."""
#     code = 'print("Context update test")'

#     # Mock get_tool_by_name
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 42
#         mock_get_tool.return_value = mock_tool

#         # Set specific run step - will be incremented to 6 by @tool_accounting
#         mock_run_context.context.current_run_step = 5

#         # Execute code
#         _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify iteration_instructions was updated
#     # Note: @tool_accounting increments from 5 to 6
#     assert len(mock_run_context.context.iteration_instructions) == 1
#     instruction = mock_run_context.context.iteration_instructions[0]
#     assert instruction.iteration_nr == 6
#     assert instruction.plan == "Executing Python code"
#     assert instruction.purpose == "Running Python code"
#     assert "secure environment" in instruction.reasoning

#     # Verify global_iteration_responses was updated
#     assert len(mock_run_context.context.global_iteration_responses) == 1
#     answer = mock_run_context.context.global_iteration_responses[0]
#     assert answer.tool == "PythonTool"
#     assert answer.tool_id == 42
#     assert answer.iteration_nr == 6
#     assert answer.parallelization_nr == 0
#     assert answer.question == "Execute Python code"
#     assert answer.reasoning and "secure environment" in answer.reasoning
#     assert "Context update test" in answer.answer
#     assert answer.cited_documents == {}

#     # Verify packets were emitted with correct index
#     mock_emitter = mock_run_context.context.run_dependencies.emitter
#     emitter_calls = mock_emitter.emit.call_args_list  # type: ignore
#     for call in emitter_calls:
#         packet = call[0][0]
#         assert isinstance(packet, Packet)
#         assert packet.ind == 6


# def test_python_tool_availability_with_url_set(db_session: Session) -> None:
#     """Test PythonTool.is_available() returns True when URL is configured."""
#     with patch(
#         "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
#         "http://localhost:8000",
#     ):
#         assert PythonTool.is_available(db_session) is True


# def test_python_tool_availability_without_url(db_session: Session) -> None:
#     """Test PythonTool.is_available() returns False when URL is not configured."""
#     with patch(
#         "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
#         None,
#     ):
#         assert PythonTool.is_available(db_session) is False

#     with patch(
#         "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
#         "",
#     ):
#         assert PythonTool.is_available(db_session) is False


# def test_python_function_tool_wrapper(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
# ) -> None:
#     """Test the @function_tool decorated python() wrapper function."""
#     code = 'print("Testing function tool wrapper")'

#     # Mock get_tool_by_name and patch CodeInterpreterClient to use our fixture
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         with patch(
#             "onyx.tools.tool_implementations_v2.python.CodeInterpreterClient"
#         ) as mock_client_class:
#             mock_tool = Mock()
#             mock_tool.id = 1
#             mock_get_tool.return_value = mock_tool
#             mock_client_class.return_value = code_interpreter_client

#             # Call the function tool wrapper
#             result_coro = python.on_invoke_tool(mock_run_context, json.dumps({"code": code}))  # type: ignore
#             result_json: str = asyncio.run(result_coro)  # type: ignore

#     # Verify result is JSON string
#     assert isinstance(result_json, str)

#     # Parse and verify result
#     adapter = TypeAdapter(LlmPythonExecutionResult)
#     result = adapter.validate_json(result_json)

#     assert isinstance(result, LlmPythonExecutionResult)
#     assert "Testing function tool wrapper" in result.stdout
#     assert result.exit_code == 0


# def test_python_execution_output_truncation(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
# ) -> None:
#     """Test that large outputs are properly truncated."""
#     # Generate code that produces output larger than truncation limit
#     code = """
# for i in range(10000):
#     print(f"Line {i}: " + "x" * 100)
# """

#     # Mock get_tool_by_name
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         # Set a small truncation limit for testing
#         with patch(
#             "onyx.tools.tool_implementations_v2.python.CODE_INTERPRETER_MAX_OUTPUT_LENGTH",
#             5000,
#         ):
#             mock_tool = Mock()
#             mock_tool.id = 1
#             mock_get_tool.return_value = mock_tool

#             # Execute code
#             result = _python_execution_core(
#                 mock_run_context, code, code_interpreter_client
#             )

#     # Verify output was truncated
#     assert len(result.stdout) <= 5000 + 200  # Allow for truncation message
#     assert "output truncated" in result.stdout
#     assert "characters omitted" in result.stdout


# def test_python_execution_multiple_files(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
#     db_session: Session,  # Needed to initialize DB engine for file_store
# ) -> None:
#     """Test generation of multiple files."""
#     code = """
# # Create multiple files
# with open('file1.txt', 'w') as f:
#     f.write('Content of file 1')

# with open('file2.txt', 'w') as f:
#     f.write('Content of file 2')

# with open('file3.txt', 'w') as f:
#     f.write('Content of file 3')

# print("Created 3 files")
# """

#     # Mock only get_tool_by_name (database lookup)
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Execute code - file store operations happen for real
#         result = _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.exit_code == 0
#     assert "Created 3 files" in result.stdout
#     assert len(result.generated_files) == 3

#     # Verify all files have unique IDs and proper metadata
#     file_ids_result = [f.file_link.split("/")[-1] for f in result.generated_files]
#     assert len(set(file_ids_result)) == 3  # All unique

#     # Verify filenames
#     filenames = [f.filename for f in result.generated_files]
#     assert "file1.txt" in filenames
#     assert "file2.txt" in filenames
#     assert "file3.txt" in filenames

#     # Verify we can read all files back from the file store
#     file_store = get_default_file_store()

#     # Create a mapping of filename to generated file for easier verification
#     files_by_name = {f.filename: f for f in result.generated_files}

#     # Verify each expected file
#     for i in range(1, 4):
#         filename = f"file{i}.txt"
#         assert filename in files_by_name, f"Expected file {filename} not found"

#         generated_file = files_by_name[filename]
#         file_id = generated_file.file_link.split("/")[-1]
#         file_io = file_store.read_file(file_id)
#         file_content = file_io.read()
#         expected_content = f"Content of file {i}".encode()
#         assert (
#             expected_content in file_content
#         ), f"Expected content not found in {filename}"


# def test_python_execution_client_error_handling(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
# ) -> None:
#     """Test error handling when Code Interpreter service fails."""
#     code = 'print("Test")'

#     # Create a client that will fail
#     if not CODE_INTERPRETER_BASE_URL:
#         pytest.skip("CODE_INTERPRETER_BASE_URL not configured")

#     client = CodeInterpreterClient()

#     # Mock the execute method to raise an exception
#     with patch.object(client, "execute", side_effect=Exception("Service unavailable")):
#         # Execute code
#         result = _python_execution_core(mock_run_context, code, client)

#     # Verify error result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.exit_code == -1
#     error_msg = result.error or ""
#     assert "Service unavailable" in result.stderr or "Service unavailable" in error_msg
#     assert not result.timed_out
#     assert len(result.generated_files) == 0

#     # Verify error delta was emitted
#     mock_emitter = mock_run_context.context.run_dependencies.emitter
#     emitter_calls = mock_emitter.emit.call_args_list  # type: ignore
#     delta_packets = [
#         call[0][0]
#         for call in emitter_calls
#         if isinstance(call[0][0].obj, PythonToolDelta)
#     ]
#     assert len(delta_packets) >= 1
#     assert "Service unavailable" in delta_packets[-1].obj.stderr


# def test_python_execution_with_excel_file(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
#     db_session: Session,  # Needed to initialize DB engine for file_store
# ) -> None:
#     """Test Excel file generation with financial data."""
#     code = """
# import pandas as pd

# # Create financial sample data
# data = {
#     'Segment': ['Government', 'Government', 'Midmarket', 'Midmarket', 'Enterprise'],
#     'Country': ['Canada', 'Germany', 'France', 'Germany', 'Canada'],
#     'Product': ['Carretera', 'Carretera', 'Carretera', 'Carretera', 'Amarilla'],
#     'Units Sold': [1618.5, 1321, 2178, 888, 2470],
#     'Manufacturing Price': [3, 3, 3, 3, 260],
#     'Sale Price': [20, 20, 20, 20, 300],
#     'Gross Sales': [32370, 26420, 43560, 17760, 741000],
#     'Discounts': [0, 0, 0, 0, 0],
#     'Sales': [32370, 26420, 43560, 17760, 741000],
#     'COGS': [16850, 13940, 22800, 9390, 642000],
#     'Profit': [15520, 12480, 20760, 8370, 99000],
#     'Month': ['January', 'January', 'June', 'April', 'September']
# }

# # Create DataFrame
# df = pd.DataFrame(data)

# # Write to Excel
# df.to_excel('financial_report.xlsx', index=False, sheet_name='Financial Data')

# print(f"Excel file created with {len(df)} rows")
# """

#     # Mock only get_tool_by_name (database lookup)
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Execute code - file store operations happen for real
#         result = _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.exit_code == 0
#     assert "Excel file created with 5 rows" in result.stdout
#     assert len(result.generated_files) == 1

#     # Verify file metadata
#     generated_file = result.generated_files[0]
#     assert generated_file.filename == "financial_report.xlsx"
#     assert ".xlsx" in generated_file.filename

#     # Extract file_id from file_link
#     file_id = generated_file.file_link.split("/")[-1]

#     # Verify we can read the file back from the file store
#     file_store = get_default_file_store()
#     file_io = file_store.read_file(file_id)
#     file_content = file_io.read()

#     # Verify the file is a valid Excel file (check ZIP magic bytes - xlsx is a ZIP archive)
#     # ZIP magic bytes: 50 4B 03 04
#     assert file_content[:4] == b"PK\x03\x04"
#     assert len(file_content) > 1000  # Excel file should be substantial

#     # Verify we can parse the Excel file with openpyxl directly
#     file_io = io.BytesIO(file_content)
#     workbook = load_workbook(file_io)
#     sheet = workbook["Financial Data"]

#     # Verify data structure - get headers from first row
#     first_row = list(sheet.iter_rows(min_row=1, max_row=1, values_only=True))[0]
#     headers = list(first_row) if first_row else []
#     expected_columns = [
#         "Segment",
#         "Country",
#         "Product",
#         "Units Sold",
#         "Manufacturing Price",
#         "Sale Price",
#         "Gross Sales",
#         "Discounts",
#         "Sales",
#         "COGS",
#         "Profit",
#         "Month",
#     ]
#     assert headers == expected_columns

#     # Verify row count (excluding header)
#     assert sheet.max_row == 6  # 1 header + 5 data rows

#     # Read data rows
#     rows = []
#     for row in sheet.iter_rows(min_row=2, values_only=True):
#         rows.append(row)

#     assert len(rows) == 5

#     # Verify some sample data
#     segments = [row[0] for row in rows]
#     countries = [row[1] for row in rows]
#     units_sold = [float(row[3]) if row[3] is not None else 0.0 for row in rows]  # type: ignore
#     profits = [float(row[10]) if row[10] is not None else 0.0 for row in rows]  # type: ignore

#     assert "Government" in segments
#     assert "Canada" in countries
#     assert sum(units_sold) > 8000  # Total units sold
#     assert sum(profits) > 155000  # Total profit


# def test_python_execution_with_excel_file_input(
#     mock_run_context: RunContextWrapper[ChatTurnContext],
#     code_interpreter_client: CodeInterpreterClient,
#     db_session: Session,  # Needed to initialize DB engine for file_store
# ) -> None:
#     """Test processing an uploaded Excel file - reading and analyzing it."""
#     # Load the sample Excel file
#     import os

#     test_file_path = os.path.join(
#         os.path.dirname(__file__), "data", "financial-sample.xlsx"
#     )

#     with open(test_file_path, "rb") as f:
#         file_content = f.read()

#     # Create InMemoryChatFile with the Excel file
#     chat_file = InMemoryChatFile(
#         file_id="test-financial-sample",
#         content=file_content,
#         file_type=ChatFileType.DOC,
#         filename="financial-sample.xlsx",
#     )

#     # Add the file to the mock context's chat_files
#     mock_run_context.context.chat_files = [chat_file]

#     # Code to analyze the uploaded Excel file
#     code = """
# import pandas as pd
# import matplotlib
# matplotlib.use('Agg')
# import matplotlib.pyplot as plt
# from openpyxl import load_workbook

# # Read the uploaded Excel file using openpyxl directly
# workbook = load_workbook('financial-sample.xlsx')
# sheet = workbook.active

# # Convert to pandas DataFrame
# data = []
# headers = [cell.value for cell in sheet[1]]
# for row in sheet.iter_rows(min_row=2, values_only=True):
#     data.append(row)

# df = pd.DataFrame(data, columns=headers)

# print(f"Loaded Excel file with {len(df)} rows and {len(df.columns)} columns")
# print(f"\\nColumns: {', '.join(df.columns.tolist())}")

# # Perform analysis
# print(f"\\n=== Analysis ===")

# # Group by segment and calculate total sales and profit
# segment_summary = df.groupby('Segment').agg({
#     ' Sales': 'sum',
#     'Profit': 'sum',
#     'Units Sold': 'sum'
# }).round(2)

# print(f"\\nSales by Segment:")
# print(segment_summary)

# # Find top 5 products by profit
# top_products = df.groupby('Product')['Profit'].sum().sort_values(ascending=False).head(5)
# print(f"\\nTop 5 Products by Profit:")
# print(top_products)

# # Calculate profit margin
# total_sales = df[' Sales'].sum()
# total_profit = df['Profit'].sum()
# profit_margin = (total_profit / total_sales * 100) if total_sales > 0 else 0
# print(f"\\nOverall Profit Margin: {profit_margin:.2f}%")

# # Create a visualization
# fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

# # Sales by Segment
# segment_summary[' Sales'].plot(kind='bar', ax=ax1, color='steelblue')
# ax1.set_title('Total Sales by Segment')
# ax1.set_xlabel('Segment')
# ax1.set_ylabel('Sales ($)')
# ax1.tick_params(axis='x', rotation=45)

# # Top 5 Products by Profit
# top_products.plot(kind='barh', ax=ax2, color='seagreen')
# ax2.set_title('Top 5 Products by Profit')
# ax2.set_xlabel('Profit ($)')
# ax2.set_ylabel('Product')

# plt.tight_layout()
# plt.savefig('financial_analysis.png', dpi=100, bbox_inches='tight')
# print(f"\\nVisualization saved as financial_analysis.png")

# # Create summary report Excel file
# summary_data = {
#     'Metric': ['Total Sales', 'Total Profit', 'Profit Margin %', 'Total Units Sold', 'Number of Records'],
#     'Value': [
#         f"${total_sales:,.2f}",
#         f"${total_profit:,.2f}",
#         f"{profit_margin:.2f}%",
#         f"{df['Units Sold'].sum():,.0f}",
#         len(df)
#     ]
# }
# summary_df = pd.DataFrame(summary_data)

# with pd.ExcelWriter('financial_summary.xlsx') as writer:
#     summary_df.to_excel(writer, sheet_name='Summary', index=False)
#     segment_summary.to_excel(writer, sheet_name='By Segment')

# print(f"Summary report saved as financial_summary.xlsx")
# """

#     # Mock only get_tool_by_name (database lookup)
#     with patch(
#         "onyx.tools.tool_implementations_v2.python.get_tool_by_name"
#     ) as mock_get_tool:
#         mock_tool = Mock()
#         mock_tool.id = 1
#         mock_get_tool.return_value = mock_tool

#         # Execute code - file store operations happen for real
#         result = _python_execution_core(mock_run_context, code, code_interpreter_client)

#     # Verify result
#     assert isinstance(result, LlmPythonExecutionResult)
#     assert result.exit_code == 0
#     assert "Loaded Excel file" in result.stdout
#     assert "Analysis" in result.stdout
#     assert "Sales by Segment" in result.stdout
#     assert "Top 5 Products by Profit" in result.stdout
#     assert "Profit Margin" in result.stdout

#     # Should generate 2 files: PNG visualization and Excel summary
#     assert len(result.generated_files) == 2

#     # Verify generated files
#     filenames = [f.filename for f in result.generated_files]
#     assert "financial_analysis.png" in filenames
#     assert "financial_summary.xlsx" in filenames

#     # Verify we can read and validate the generated files
#     file_store = get_default_file_store()

#     # Check the PNG file
#     png_file = next(
#         f for f in result.generated_files if f.filename == "financial_analysis.png"
#     )
#     png_file_id = png_file.file_link.split("/")[-1]
#     png_io = file_store.read_file(png_file_id)
#     png_content = png_io.read()
#     assert png_content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
#     assert len(png_content) > 5000  # Should be substantial

#     # Check the Excel summary file
#     xlsx_file = next(
#         f for f in result.generated_files if f.filename == "financial_summary.xlsx"
#     )
#     xlsx_file_id = xlsx_file.file_link.split("/")[-1]
#     xlsx_io = file_store.read_file(xlsx_file_id)
#     xlsx_content = xlsx_io.read()
#     assert xlsx_content[:4] == b"PK\x03\x04"  # ZIP/Excel magic bytes

#     # Parse and verify the summary Excel file using openpyxl directly
#     xlsx_io_obj = io.BytesIO(xlsx_content)
#     workbook = load_workbook(xlsx_io_obj)
#     sheet = workbook["Summary"]

#     # Read headers from first row
#     first_row = list(sheet.iter_rows(min_row=1, max_row=1, values_only=True))[0]
#     headers = list(first_row) if first_row else []
#     assert "Metric" in headers
#     assert "Value" in headers

#     # Read all rows and extract metrics
#     metrics = []
#     for row in sheet.iter_rows(min_row=2, values_only=True):
#         if row[0]:  # Metric column
#             metrics.append(row[0])

#     assert "Total Sales" in metrics
#     assert "Total Profit" in metrics
#     assert "Profit Margin %" in metrics


# if __name__ == "__main__":
#     # Run with: python -m pytest tests/external_dependency_unit/tools/test_python_tool.py -v
#     pytest.main([__file__, "-v"])


from __future__ import annotations

import io
import json
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

import onyx.tools.tool_implementations.python.code_interpreter_client as ci_mod
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.models import Persona
from onyx.db.tools import get_builtin_tool
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import FileDescriptor
from onyx.server.features.projects.api import upload_user_files
from onyx.server.query_and_chat.chat_backend import get_chat_session
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PythonToolDelta
from onyx.server.query_and_chat.streaming_models import PythonToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from tests.external_dependency_unit.answer.stream_test_builder import StreamTestBuilder
from tests.external_dependency_unit.answer.stream_test_utils import create_chat_session
from tests.external_dependency_unit.answer.stream_test_utils import create_placement
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.mock_llm import LLMAnswerResponse
from tests.external_dependency_unit.mock_llm import LLMToolCallResponse
from tests.external_dependency_unit.mock_llm import use_mock_llm


# ---------------------------------------------------------------------------
# Mock Code Interpreter Server
# ---------------------------------------------------------------------------


class CapturedRequest:
    """A single HTTP request captured by the mock server."""

    def __init__(self, method: str, path: str, body: bytes) -> None:
        self.method = method
        self.path = path
        self.body = body

    def json_body(self) -> dict[str, Any]:
        return json.loads(self.body)


class _MockCIHandler(BaseHTTPRequestHandler):
    """HTTP handler that records every request and returns canned responses."""

    server: MockCodeInterpreterServer

    def do_POST(self) -> None:
        body = self._read_body()
        self._capture("POST", body)

        if self.path == "/v1/files":
            self.server._file_counter += 1
            self._respond_json(
                200, {"file_id": f"mock-ci-file-{self.server._file_counter}"}
            )
        elif self.path == "/v1/execute/stream":
            if self.server.streaming_enabled:
                self._respond_sse(
                    [
                        (
                            "output",
                            {"stream": "stdout", "data": "mock output\n"},
                        ),
                        (
                            "result",
                            {
                                "exit_code": 0,
                                "timed_out": False,
                                "duration_ms": 50,
                                "files": [],
                            },
                        ),
                    ]
                )
            else:
                self._respond_json(404, {"error": "not found"})
        elif self.path == "/v1/execute":
            self._respond_json(
                200,
                {
                    "stdout": "mock output\n",
                    "stderr": "",
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_ms": 50,
                    "files": [],
                },
            )
        else:
            self._respond_json(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        self._capture("DELETE", b"")
        self.send_response(200)
        self.end_headers()

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _capture(self, method: str, body: bytes) -> None:
        self.server.captured_requests.append(
            CapturedRequest(method=method, path=self.path, body=body)
        )

    def _respond_json(self, status: int, data: dict[str, Any]) -> None:
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _respond_sse(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        frames = []
        for event_type, data in events:
            frames.append(f"event: {event_type}\ndata: {json.dumps(data)}\n\n")
        payload = "".join(frames).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class MockCodeInterpreterServer(HTTPServer):
    """HTTPServer wrapper that records requests for assertions."""

    def __init__(self) -> None:
        super().__init__(("localhost", 0), _MockCIHandler)
        self.captured_requests: list[CapturedRequest] = []
        self._file_counter = 0
        self.streaming_enabled: bool = True

    @property
    def url(self) -> str:
        host, port = self.server_address
        return f"http://{host!s}:{port}"

    def start(self) -> None:
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def get_requests(
        self,
        method: str | None = None,
        path: str | None = None,
    ) -> list[CapturedRequest]:
        results = self.captured_requests
        if method:
            results = [r for r in results if r.method == method]
        if path:
            results = [r for r in results if r.path == path]
        return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mock_ci_server() -> Generator[MockCodeInterpreterServer, None, None]:
    server = MockCodeInterpreterServer()
    server.start()
    yield server
    server.shutdown()


@pytest.fixture()
def _attach_python_tool_to_default_persona(db_session: Session) -> None:
    """Ensure the default persona (id=0) has the PythonTool attached."""
    python_tool_db = get_builtin_tool(db_session, PythonTool)
    persona = db_session.get(Persona, 0)
    assert persona is not None, "Default persona (id=0) not found"

    if python_tool_db not in persona.tools:
        persona.tools.append(python_tool_db)
        db_session.commit()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_code_interpreter_receives_chat_files(
    db_session: Session,
    mock_ci_server: MockCodeInterpreterServer,
    _attach_python_tool_to_default_persona: None,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    mock_ci_server.captured_requests.clear()
    mock_ci_server._file_counter = 0
    mock_url = mock_ci_server.url

    user = create_test_user(db_session, "ci_test_admin")
    chat_session = create_chat_session(db_session=db_session, user=user)

    # Upload a test CSV
    csv_content = b"name,age,city\nAlice,30,NYC\nBob,25,SF\n"
    result = upload_user_files(
        files=[
            UploadFile(
                file=io.BytesIO(csv_content),
                filename="data.csv",
                size=len(csv_content),
                headers=Headers({"content-type": "text/csv"}),
            )
        ],
        project_id=None,
        temp_id_map=json.dumps({"0|data.csv": "data.csv"}),
        user=user,
        db_session=db_session,
    )
    assert len(result.user_files) == 1
    user_file = result.user_files[0]

    file_descriptor: FileDescriptor = {
        "id": user_file.file_id,
        "type": ChatFileType.CSV,
        "name": "data.csv",
        "user_file_id": str(user_file.id),
    }

    code = "import pandas as pd\ndf = pd.read_csv('data.csv')\nprint(df)"
    msg_req = SendMessageRequest(
        message="Read the CSV and print it.",
        chat_session_id=chat_session.id,
        file_descriptors=[file_descriptor],
        stream=True,
    )

    original_defaults = ci_mod.CodeInterpreterClient.__init__.__defaults__
    with (
        use_mock_llm() as mock_llm,
        patch(
            "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
        patch(
            "onyx.tools.tool_implementations.python.code_interpreter_client.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
    ):
        mock_llm.add_response(
            LLMToolCallResponse(
                tool_name="python",
                tool_call_id="call_test_1",
                tool_call_argument_tokens=[json.dumps({"code": code})],
            )
        )
        mock_llm.forward_till_end()

        ci_mod.CodeInterpreterClient.__init__.__defaults__ = (mock_url,)
        try:
            list(
                handle_stream_message_objects(
                    new_msg_req=msg_req, user=user, db_session=db_session
                )
            )
        finally:
            ci_mod.CodeInterpreterClient.__init__.__defaults__ = original_defaults

    # Verify: file uploaded, code executed via streaming, staged file cleaned up
    assert len(mock_ci_server.get_requests(method="POST", path="/v1/files")) == 1
    assert (
        len(mock_ci_server.get_requests(method="POST", path="/v1/execute/stream")) == 1
    )

    delete_requests = mock_ci_server.get_requests(method="DELETE")
    assert len(delete_requests) == 1
    assert delete_requests[0].path.startswith("/v1/files/")

    execute_body = mock_ci_server.get_requests(
        method="POST", path="/v1/execute/stream"
    )[0].json_body()
    assert execute_body["code"] == code
    assert len(execute_body["files"]) == 1
    assert execute_body["files"][0]["path"] == "data.csv"


def test_code_interpreter_replay_packets_include_code_and_output(
    db_session: Session,
    mock_ci_server: MockCodeInterpreterServer,
    _attach_python_tool_to_default_persona: None,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    """After a code interpreter message completes, retrieving the message
    via translate_assistant_message_to_packets should emit PythonToolStart
    (containing the executed code) and PythonToolDelta (containing
    stdout/stderr), not generic CustomTool packets."""
    mock_ci_server.captured_requests.clear()
    mock_ci_server._file_counter = 0
    mock_url = mock_ci_server.url

    user = create_test_user(db_session, "ci_replay_test")
    chat_session = create_chat_session(db_session=db_session, user=user)

    code = 'x = 2 + 2\nprint(f"Result: {x}")'
    msg_req = SendMessageRequest(
        message="Calculate 2 + 2",
        chat_session_id=chat_session.id,
        stream=True,
    )

    original_defaults = ci_mod.CodeInterpreterClient.__init__.__defaults__
    with (
        use_mock_llm() as mock_llm,
        patch(
            "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
        patch(
            "onyx.tools.tool_implementations.python.code_interpreter_client.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
    ):
        answer_tokens = ["The ", "result ", "is ", "4."]

        ci_mod.CodeInterpreterClient.__init__.__defaults__ = (mock_url,)
        try:
            handler = StreamTestBuilder(llm_controller=mock_llm)

            stream = handle_stream_message_objects(
                new_msg_req=msg_req, user=user, db_session=db_session
            )
            # First packet is always MessageResponseIDInfo
            next(stream)

            # Phase 1: LLM requests python tool execution.
            handler.add_response(
                LLMToolCallResponse(
                    tool_name="python",
                    tool_call_id="call_replay_test",
                    tool_call_argument_tokens=[json.dumps({"code": code})],
                )
            ).expect(
                Packet(
                    placement=create_placement(0),
                    obj=PythonToolStart(code=code),
                ),
                forward=2,
            ).expect(
                Packet(
                    placement=create_placement(0),
                    obj=PythonToolDelta(stdout="mock output\n", stderr="", file_ids=[]),
                ),
                forward=False,
            ).expect(
                Packet(
                    placement=create_placement(0),
                    obj=SectionEnd(),
                ),
                forward=False,
            ).run_and_validate(
                stream=stream
            )

            # Phase 2: LLM produces a final answer after tool execution.
            handler.add_response(
                LLMAnswerResponse(answer_tokens=answer_tokens)
            ).expect_agent_response(
                answer_tokens=answer_tokens,
                turn_index=1,
            ).run_and_validate(
                stream=stream
            )

            with pytest.raises(StopIteration):
                next(stream)

        finally:
            ci_mod.CodeInterpreterClient.__init__.__defaults__ = original_defaults

    # Retrieve the chat session through the same endpoint the frontend uses
    chat_detail = get_chat_session(
        session_id=chat_session.id,
        user=user,
        db_session=db_session,
    )

    assert (
        len(mock_ci_server.get_requests(method="POST", path="/v1/execute/stream")) == 1
    )

    # The response contains `packets` — a list of packet-lists, one per
    # assistant message. We should have exactly one assistant message.
    assert (
        len(chat_detail.packets) == 1
    ), f"Expected 1 assistant packet list, got {len(chat_detail.packets)}"
    packets = chat_detail.packets[0]

    # Extract PythonToolStart packets – these must contain the code
    start_packets = [p for p in packets if isinstance(p.obj, PythonToolStart)]
    assert len(start_packets) == 1, (
        f"Expected 1 PythonToolStart packet, got {len(start_packets)}. "
        f"Packet types: {[type(p.obj).__name__ for p in packets]}"
    )
    start_obj = start_packets[0].obj
    assert isinstance(start_obj, PythonToolStart)
    assert start_obj.code == code

    # Extract PythonToolDelta packets – these must contain stdout/stderr
    delta_packets = [p for p in packets if isinstance(p.obj, PythonToolDelta)]
    assert len(delta_packets) >= 1, (
        f"Expected at least 1 PythonToolDelta packet, got {len(delta_packets)}. "
        f"Packet types: {[type(p.obj).__name__ for p in packets]}"
    )
    # The mock CI server returns "mock output\n" as stdout
    delta_obj = delta_packets[0].obj
    assert isinstance(delta_obj, PythonToolDelta)
    assert "mock output" in delta_obj.stdout


def test_code_interpreter_streaming_fallback_to_batch(
    db_session: Session,
    mock_ci_server: MockCodeInterpreterServer,
    _attach_python_tool_to_default_persona: None,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    """When the streaming endpoint is not available (older code-interpreter),
    execute_streaming should fall back to the batch /v1/execute endpoint."""
    mock_ci_server.captured_requests.clear()
    mock_ci_server._file_counter = 0
    mock_ci_server.streaming_enabled = False
    mock_url = mock_ci_server.url

    user = create_test_user(db_session, "ci_fallback_test")
    chat_session = create_chat_session(db_session=db_session, user=user)

    code = 'print("fallback test")'
    msg_req = SendMessageRequest(
        message="Print fallback test",
        chat_session_id=chat_session.id,
        stream=True,
    )

    original_defaults = ci_mod.CodeInterpreterClient.__init__.__defaults__
    with (
        use_mock_llm() as mock_llm,
        patch(
            "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
        patch(
            "onyx.tools.tool_implementations.python.code_interpreter_client.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
    ):
        mock_llm.add_response(
            LLMToolCallResponse(
                tool_name="python",
                tool_call_id="call_fallback",
                tool_call_argument_tokens=[json.dumps({"code": code})],
            )
        )
        mock_llm.forward_till_end()

        ci_mod.CodeInterpreterClient.__init__.__defaults__ = (mock_url,)
        try:
            packets = list(
                handle_stream_message_objects(
                    new_msg_req=msg_req, user=user, db_session=db_session
                )
            )
        finally:
            ci_mod.CodeInterpreterClient.__init__.__defaults__ = original_defaults
            mock_ci_server.streaming_enabled = True

    # Streaming was attempted first (returned 404), then fell back to batch
    assert (
        len(mock_ci_server.get_requests(method="POST", path="/v1/execute/stream")) == 1
    )
    assert len(mock_ci_server.get_requests(method="POST", path="/v1/execute")) == 1

    # Verify output still made it through
    delta_packets = [
        p
        for p in packets
        if isinstance(p, Packet) and isinstance(p.obj, PythonToolDelta)
    ]
    assert len(delta_packets) >= 1
    first_delta = delta_packets[0].obj
    assert isinstance(first_delta, PythonToolDelta)
    assert "mock output" in first_delta.stdout
