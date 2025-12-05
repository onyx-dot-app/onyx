import mimetypes
from io import BytesIO
from typing import Any
from typing import cast

from pydantic import TypeAdapter
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.configs.app_configs import CODE_INTERPRETER_DEFAULT_TIMEOUT_MS
from onyx.configs.app_configs import CODE_INTERPRETER_MAX_OUTPUT_LENGTH
from onyx.configs.constants import FileOrigin
from onyx.file_store.utils import build_full_frontend_file_url
from onyx.file_store.utils import get_default_file_store
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PythonToolDelta
from onyx.server.query_and_chat.streaming_models import PythonToolStart
from onyx.tools.models import LlmPythonExecutionResult
from onyx.tools.models import PythonExecutionFile
from onyx.tools.models import PythonToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import FileInput
from onyx.utils.logger import setup_logger


logger = setup_logger()

CODE_FIELD = "code"


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


class PythonTool(Tool[PythonToolOverrideKwargs]):
    """
    Python code execution tool using an external Code Interpreter service.

    This tool allows executing Python code in a secure, isolated sandbox environment.
    It supports uploading files from the chat session and downloading generated files.
    """

    NAME = "python"
    DISPLAY_NAME = "Code Interpreter"
    DESCRIPTION = "Execute Python code in an isolated sandbox environment."

    def __init__(self, tool_id: int, emitter: Emitter) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        is_available = bool(CODE_INTERPRETER_BASE_URL)
        return is_available

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        CODE_FIELD: {
                            "type": "string",
                            "description": "Python source code to execute",
                        },
                    },
                    "required": [CODE_FIELD],
                },
            },
        }

    def emit_start(self, turn_index: int) -> None:
        """Emit start packet for this tool. Code will be emitted in run() method."""
        # Note: PythonToolStart requires code, but we don't have it in emit_start
        # The code is available in run() method via llm_kwargs
        # We'll emit the start packet in run() instead

    def run(
        self,
        turn_index: int,
        override_kwargs: PythonToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """
        Execute Python code in the Code Interpreter service.

        Args:
            turn_index: The turn index for this tool execution
            override_kwargs: Contains chat_files to stage for execution
            **llm_kwargs: Contains 'code' parameter from LLM

        Returns:
            ToolResponse with execution results
        """
        code = cast(str, llm_kwargs[CODE_FIELD])
        chat_files = override_kwargs.chat_files if override_kwargs else []

        # Emit start event with the code
        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                obj=PythonToolStart(code=code),
            )
        )

        # Create Code Interpreter client
        client = CodeInterpreterClient()

        # Stage chat files for execution
        files_to_stage: list[FileInput] = []
        for ind, chat_file in enumerate(chat_files):
            file_name = chat_file.filename or f"file_{ind}"
            try:
                # Upload to Code Interpreter
                ci_file_id = client.upload_file(chat_file.content, file_name)

                # Stage for execution
                files_to_stage.append({"path": file_name, "file_id": ci_file_id})

                logger.info(f"Staged file for Python execution: {file_name}")

            except Exception as e:
                logger.warning(f"Failed to stage file {file_name}: {e}")

        try:
            logger.debug(f"Executing code: {code}")

            # Execute code with timeout
            response = client.execute(
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
            file_store = get_default_file_store()

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

                    # Save to Onyx file store
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

            # Cleanup Code Interpreter files (generated files)
            for ci_file_id in file_ids_to_cleanup:
                try:
                    client.delete_file(ci_file_id)
                except Exception as e:
                    logger.error(
                        f"Failed to delete Code Interpreter generated file {ci_file_id}: {e}"
                    )

            # Cleanup staged input files
            for file_mapping in files_to_stage:
                try:
                    client.delete_file(file_mapping["file_id"])
                except Exception as e:
                    logger.error(
                        f"Failed to delete Code Interpreter staged file {file_mapping['file_id']}: {e}"
                    )

            # Emit delta with stdout/stderr and generated files
            self.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    obj=PythonToolDelta(
                        stdout=truncated_stdout,
                        stderr=truncated_stderr,
                        file_ids=generated_file_ids,
                    ),
                )
            )

            # Build result
            result = LlmPythonExecutionResult(
                stdout=truncated_stdout,
                stderr=truncated_stderr,
                exit_code=response.exit_code,
                timed_out=response.timed_out,
                generated_files=generated_files,
                error=None if response.exit_code == 0 else truncated_stderr,
            )

            # Serialize result for LLM
            adapter = TypeAdapter(LlmPythonExecutionResult)
            llm_response = adapter.dump_json(result).decode()

            return ToolResponse(
                rich_response=None,  # No rich response needed for Python tool
                llm_facing_response=llm_response,
            )

        except Exception as e:
            logger.error(f"Python execution failed: {e}")
            error_msg = str(e)

            # Emit error delta
            self.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    obj=PythonToolDelta(
                        stdout="",
                        stderr=error_msg,
                        file_ids=[],
                    ),
                )
            )

            # Return error result
            result = LlmPythonExecutionResult(
                stdout="",
                stderr=error_msg,
                exit_code=-1,
                timed_out=False,
                generated_files=[],
                error=error_msg,
            )

            adapter = TypeAdapter(LlmPythonExecutionResult)
            llm_response = adapter.dump_json(result).decode()

            return ToolResponse(
                rich_response=None,
                llm_facing_response=llm_response,
            )
