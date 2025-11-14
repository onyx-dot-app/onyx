import mimetypes
from io import BytesIO

from agents import function_tool
from agents import RunContextWrapper
from pydantic import TypeAdapter

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.turn.models import ChatTurnContext
from onyx.configs.app_configs import CODE_INTERPRETER_DEFAULT_TIMEOUT_MS
from onyx.configs.app_configs import CODE_INTERPRETER_MAX_OUTPUT_LENGTH
from onyx.configs.constants import FileOrigin
from onyx.db.tools import get_tool_by_name
from onyx.file_store.utils import build_frontend_file_url
from onyx.file_store.utils import get_default_file_store
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PythonToolDelta
from onyx.server.query_and_chat.streaming_models import PythonToolStart
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations_v2.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_implementations_v2.code_interpreter_client import ExecuteResponse
from onyx.tools.tool_implementations_v2.code_interpreter_client import FileInput
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmPythonExecutionResult,
)
from onyx.tools.tool_implementations_v2.tool_result_models import PythonExecutionFile
from onyx.utils.logger import setup_logger

logger = setup_logger()


@tool_accounting
def _python_execution_core(
    run_context: RunContextWrapper[ChatTurnContext],
    code: str,
    client: CodeInterpreterClient,
) -> LlmPythonExecutionResult:
    """Core Python execution logic"""
    index = run_context.context.current_run_step
    emitter = run_context.context.run_dependencies.emitter

    # Emit start event
    emitter.emit(
        Packet(
            ind=index,
            obj=PythonToolStart(type="python_tool_start", code=code),
        )
    )

    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="Executing Python code",
            purpose="Running Python code",
            reasoning="Executing provided Python code in secure environment",
        )
    )

    # Get all files from chat context and upload to Code Interpreter
    files_to_stage: list[FileInput] = []
    file_store = get_default_file_store()

    # Access chat files directly from context (available after Step 0 changes)
    chat_files = run_context.context.chat_files

    for chat_file in chat_files:
        try:
            # Use file content already loaded in memory
            file_content = chat_file.content

            # Upload to Code Interpreter
            ci_file_id = client.upload_file(file_content, chat_file.filename)

            # Stage for execution
            files_to_stage.append({"path": chat_file.filename, "file_id": ci_file_id})

            logger.info(f"Staged file for Python execution: {chat_file.filename}")

        except Exception as e:
            logger.warning(f"Failed to stage file {chat_file.filename}: {e}")

    try:
        logger.debug(f"Executing code: {code}")

        # Execute code with fixed timeout
        response: ExecuteResponse = client.execute(
            code=code,
            timeout_ms=CODE_INTERPRETER_DEFAULT_TIMEOUT_MS,
            files=files_to_stage if files_to_stage else None,
        )

        # Truncate output for LLM consumption
        truncated_stdout = response.stdout[:CODE_INTERPRETER_MAX_OUTPUT_LENGTH]
        truncated_stderr = response.stderr[:CODE_INTERPRETER_MAX_OUTPUT_LENGTH]

        stdout_truncated = len(response.stdout) > CODE_INTERPRETER_MAX_OUTPUT_LENGTH
        stderr_truncated = len(response.stderr) > CODE_INTERPRETER_MAX_OUTPUT_LENGTH

        if stdout_truncated:
            truncated_stdout += (
                "\n... [output truncated, "
                f"{len(response.stdout) - CODE_INTERPRETER_MAX_OUTPUT_LENGTH} "
                "characters omitted]"
            )
            logger.debug(f"Truncated stdout: {truncated_stdout}")

        if stderr_truncated:
            truncated_stderr += (
                "\n... [output truncated, "
                f"{len(response.stderr) - CODE_INTERPRETER_MAX_OUTPUT_LENGTH} "
                "characters omitted]"
            )
            logger.debug(f"Truncated stderr: {truncated_stderr}")

        # Handle generated files
        generated_files = []
        file_ids_to_cleanup = []

        for workspace_file in response.files:
            if workspace_file.kind == "file" and workspace_file.file_id:
                try:
                    # Download file from Code Interpreter
                    file_content = client.download_file(workspace_file.file_id)

                    # Determine MIME type from file extension
                    filename = workspace_file.path.split("/")[-1]
                    mime_type, _ = mimetypes.guess_type(filename)
                    if not mime_type:
                        # Default to binary if we can't determine the type
                        mime_type = "application/octet-stream"

                    # Save to Onyx file store directly
                    onyx_file_id = file_store.save_file(
                        content=BytesIO(file_content),
                        display_name=filename,
                        file_origin=FileOrigin.CHAT_UPLOAD,
                        file_type=mime_type,
                    )

                    generated_files.append(
                        PythonExecutionFile(
                            file_id=onyx_file_id,
                            filename=filename,
                            path=workspace_file.path,
                            url=build_frontend_file_url(onyx_file_id),
                        )
                    )

                    # Mark for cleanup
                    file_ids_to_cleanup.append(workspace_file.file_id)

                except Exception as e:
                    logger.error(
                        f"Failed to handle generated file {workspace_file.path}: {e}"
                    )

        # Cleanup Code Interpreter files (both generated and staged input files)
        for ci_file_id in file_ids_to_cleanup:
            try:
                client.delete_file(ci_file_id)
            except Exception as e:
                logger.warning(
                    f"Failed to delete Code Interpreter generated file {ci_file_id}: {e}"
                )

        # Cleanup staged input files
        for file_mapping in files_to_stage:
            try:
                client.delete_file(file_mapping["file_id"])
            except Exception as e:
                logger.warning(
                    f"Failed to delete Code Interpreter staged file {file_mapping['file_id']}: {e}"
                )

        # Emit delta with stdout/stderr and generated files
        emitter.emit(
            Packet(
                ind=index,
                obj=PythonToolDelta(
                    type="python_tool_delta",
                    stdout=truncated_stdout,
                    stderr=truncated_stderr,
                    file_ids=[f.file_id for f in generated_files],
                ),
            )
        )

        # Build result with truncated output
        result = LlmPythonExecutionResult(
            stdout=truncated_stdout,
            stderr=truncated_stderr,
            exit_code=response.exit_code,
            timed_out=response.timed_out,
            duration_ms=response.duration_ms,
            generated_files=generated_files,
            error=None if response.exit_code == 0 else truncated_stderr,
        )

        # Get tool ID from database
        tool_id = get_tool_by_name(
            PythonTool.__name__, run_context.context.run_dependencies.db_session
        ).id

        # Store in iteration answer
        run_context.context.global_iteration_responses.append(
            IterationAnswer(
                tool=PythonTool.__name__,
                tool_id=tool_id,
                iteration_nr=index,
                parallelization_nr=0,
                question="Execute Python code",
                reasoning="Executing Python code in secure environment",
                answer=(
                    truncated_stdout if response.exit_code == 0 else truncated_stderr
                ),
                cited_documents={},
                file_ids=(
                    [f.file_id for f in generated_files] if generated_files else None
                ),
            )
        )

        return result

    except Exception as e:
        logger.error(f"Python execution failed: {e}")
        error_msg = str(e)

        # Emit error delta
        emitter.emit(
            Packet(
                ind=index,
                obj=PythonToolDelta(
                    type="python_tool_delta",
                    stdout="",
                    stderr=error_msg,
                    file_ids=[],
                ),
            )
        )

        # Return error result
        return LlmPythonExecutionResult(
            stdout="",
            stderr=error_msg,
            exit_code=-1,
            timed_out=False,
            duration_ms=0,
            generated_files=[],
            error=error_msg,
        )


@function_tool
def python(
    run_context: RunContextWrapper[ChatTurnContext],
    code: str,
) -> str:
    """
    Execute Python code in a secure, isolated environment.

    This tool runs Python code with access to libraries like numpy, pandas, scipy,
    matplotlib, and PIL. The code executes in a sandboxed Docker container without
    internet access.

    Use `openpyxl` to read and write Excel files.

    Any files uploaded to the chat will be automatically available in the execution
    environment. Files generated by the code (plots, CSVs, etc.) will be captured
    and returned.

    Args:
        code: Python source code to execute

    Returns:
        JSON string containing stdout, stderr, exit code, execution time, and any generated files
    """
    # Create client
    client = CodeInterpreterClient()

    # Execute
    result = _python_execution_core(run_context, code, client)

    # Serialize and return
    adapter = TypeAdapter(LlmPythonExecutionResult)
    return adapter.dump_json(result).decode()


# Long description for tool documentation
PYTHON_EXECUTION_LONG_DESCRIPTION = """
Use the `python_execution` tool to run Python code for data analysis, computation, visualization, and file processing.

**Capabilities:**
- Data analysis with pandas, numpy, scipy
- Data visualization with matplotlib
- Image processing with PIL
- File generation (CSV, plots, processed data)
- Mathematical computations

**Limitations:**
- No internet access (cannot make HTTP requests, download files)
- Maximum execution time enforced
- Isolated environment (no persistent state between executions)

**Available Libraries:**
numpy, pandas, scipy, matplotlib, PIL, and other common data science libraries.

**File Handling:**
- Files generated by your code (saved to disk) will be automatically captured and returned
- Generated files can include plots, CSVs, processed images, etc.
- Files are available for download by the user
"""
