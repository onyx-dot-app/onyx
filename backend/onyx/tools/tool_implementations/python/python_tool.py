import mimetypes
from collections.abc import Generator
from io import BytesIO
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.configs.app_configs import CODE_INTERPRETER_DEFAULT_TIMEOUT_MS
from onyx.configs.app_configs import CODE_INTERPRETER_MAX_OUTPUT_LENGTH
from onyx.configs.constants import FileOrigin
from onyx.file_store.utils import build_full_frontend_file_url
from onyx.file_store.utils import get_default_file_store
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PythonToolDelta
from onyx.server.query_and_chat.streaming_models import PythonToolStart
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import RunContextWrapper
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    ExecuteResponse,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import FileInput
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.tools.tool_result_models import LlmPythonExecutionResult
from onyx.tools.tool_result_models import PythonExecutionFile
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()

_GENERIC_ERROR_MESSAGE = (
    "PythonTool should only be used with v2 tools, not via direct calls to PythonTool."
)


def _truncate_output(output: str, max_length: int, label: str = "output") -> str:
    """
    Truncate output string to max_length and append truncation message if needed.

    Args:
        output: The original output string to truncate
        max_length: Maximum length before truncation
        label: Label for logging (e.g., "stdout", "stderr")

    Returns:
        Truncated string with truncation message appended if truncated
    """
    truncated = output[:max_length]
    if len(output) > max_length:
        truncated += (
            "\n... [output truncated, "
            f"{len(output) - max_length} "
            "characters omitted]"
        )
        logger.debug(f"Truncated {label}: {truncated}")
    return truncated


def _combine_outputs(stdout: str, stderr: str) -> str:
    """
    Combine stdout and stderr into a single string if both exist.

    Args:
        stdout: Standard output string
        stderr: Standard error string

    Returns:
        Combined output string with labels if both exist, or the non-empty one
        if only one exists, or empty string if both are empty
    """
    has_stdout = bool(stdout)
    has_stderr = bool(stderr)

    if has_stdout and has_stderr:
        return f"stdout:\n\n{stdout}\n\nstderr:\n\n{stderr}"
    elif has_stdout:
        return stdout
    elif has_stderr:
        return stderr
    else:
        return ""


@tool_accounting
def _python_execution_core(
    run_context: RunContextWrapper[Any],
    code: str,
    client: CodeInterpreterClient,
    tool_id: int,
) -> LlmPythonExecutionResult:
    """Core Python execution logic"""
    index = run_context.context.current_run_step
    emitter = run_context.context.run_dependencies.emitter

    # Emit start event
    emitter.emit(
        Packet(
            ind=index,
            obj=PythonToolStart(code=code),
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

    for ind, chat_file in enumerate(chat_files):
        file_name = chat_file.filename or f"file_{ind}"
        try:
            # Use file content already loaded in memory
            file_content = chat_file.content

            # Upload to Code Interpreter
            ci_file_id = client.upload_file(file_content, file_name)

            # Stage for execution
            files_to_stage.append({"path": file_name, "file_id": ci_file_id})

            logger.info(f"Staged file for Python execution: {file_name}")

        except Exception as e:
            logger.warning(f"Failed to stage file {file_name}: {e}")

    try:
        logger.debug(f"Executing code: {code}")

        # Execute code with fixed timeout
        response: ExecuteResponse = client.execute(
            code=code,
            timeout_ms=CODE_INTERPRETER_DEFAULT_TIMEOUT_MS,
            files=files_to_stage or None,
        )

        # Truncate output for LLM consumption
        truncated_stdout = _truncate_output(
            response.stdout, CODE_INTERPRETER_MAX_OUTPUT_LENGTH, "stdout"
        )
        truncated_stderr = _truncate_output(
            response.stderr, CODE_INTERPRETER_MAX_OUTPUT_LENGTH, "stderr"
        )

        # Handle generated files
        generated_files: list[PythonExecutionFile] = []
        generated_file_ids: list[str] = []
        file_ids_to_cleanup: list[str] = []

        for workspace_file in response.files:
            if workspace_file.kind != "file" or not workspace_file.file_id:
                continue

            try:
                # Download file from Code Interpreter
                file_content = client.download_file(workspace_file.file_id)

                # Determine MIME type from file extension
                filename = workspace_file.path.split("/")[-1]
                mime_type, _ = mimetypes.guess_type(filename)
                # Default to binary if we can't determine the type
                mime_type = mime_type or "application/octet-stream"

                # Save to Onyx file store directly
                onyx_file_id = file_store.save_file(
                    content=BytesIO(file_content),
                    display_name=filename,
                    file_origin=FileOrigin.CHAT_UPLOAD,
                    file_type=mime_type,
                )

                generated_files.append(
                    PythonExecutionFile(
                        filename=filename,
                        file_link=build_full_frontend_file_url(onyx_file_id),
                    )
                )
                generated_file_ids.append(onyx_file_id)

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
                # TODO: add TTL on code interpreter files themselves so they are automatically
                # cleaned up after some time.
                logger.error(
                    f"Failed to delete Code Interpreter generated file {ci_file_id}: {e}"
                )

        # Cleanup staged input files
        for file_mapping in files_to_stage:
            try:
                client.delete_file(file_mapping["file_id"])
            except Exception as e:
                # TODO: add TTL on code interpreter files themselves so they are automatically
                # cleaned up after some time.
                logger.error(
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
                    file_ids=generated_file_ids,
                ),
            )
        )

        # Build result with truncated output
        result = LlmPythonExecutionResult(
            stdout=truncated_stdout,
            stderr=truncated_stderr,
            exit_code=response.exit_code,
            timed_out=response.timed_out,
            generated_files=generated_files,
            error=None if response.exit_code == 0 else truncated_stderr,
        )

        # Store in iteration answer
        run_context.context.global_iteration_responses.append(
            IterationAnswer(
                tool=PythonTool.__name__,
                tool_id=tool_id,
                iteration_nr=index,
                parallelization_nr=0,
                question="Execute Python code",
                reasoning="Executing Python code in secure environment",
                answer=_combine_outputs(truncated_stdout, truncated_stderr),
                cited_documents={},
                file_ids=generated_file_ids,
                additional_data={
                    "stdout": truncated_stdout,
                    "stderr": truncated_stderr,
                    "code": code,
                },
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
            generated_files=[],
            error=error_msg,
        )


class PythonTool(Tool[None]):
    """
    Wrapper class for Python code execution tool.

    This class provides availability checking and integrates with the Tool infrastructure.
    Actual execution is handled by the v2 function-based implementation.
    """

    _NAME = "python"
    _DESCRIPTION = "Execute Python code in a secure, isolated environment. Never call this tool directly."
    # in the UI, call it `Code Interpreter` since this is a well known term for this tool
    _DISPLAY_NAME = "Code Interpreter"

    def __init__(self, tool_id: int) -> None:
        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """
        Available if Code Interpreter service URL is configured.

        Only checks if CODE_INTERPRETER_BASE_URL is set - does not perform health check.
        Service failures will be handled gracefully at execution time.
        """
        is_available = bool(CODE_INTERPRETER_BASE_URL)
        logger.info(
            "PythonTool.is_available() called: "
            f"CODE_INTERPRETER_BASE_URL={CODE_INTERPRETER_BASE_URL!r}, "
            f"returning {is_available}"
        )

        return is_available

    def tool_definition(self) -> dict:
        """Tool definition for LLMs that support explicit tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python source code to execute",
                        },
                    },
                    "required": ["code"],
                },
            },
        }

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def run_v2(
        self,
        run_context: RunContextWrapper[Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Run Python code execution via the v2 implementation.

        Returns:
            JSON string containing execution results (stdout, stderr, exit code, files)
        """
        code = kwargs.get("code")
        if not code:
            raise ValueError("code is required for python execution")

        # Create client and call the core implementation
        client = CodeInterpreterClient()
        result = _python_execution_core(run_context, code, client, self._id)

        # Serialize and return
        adapter = TypeAdapter(LlmPythonExecutionResult)
        return adapter.dump_json(result).decode()

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)
