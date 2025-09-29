from __future__ import annotations

import base64
import binascii
import json
import mimetypes
from collections.abc import Generator
from contextlib import closing
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.tools.base_tool import BaseTool
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()


PYTHON_TOOL_RESPONSE_ID = "python_tool_result"
_EXECUTE_PATH = "/execute"
_DEFAULT_RESULT_CHAR_LIMIT = 1200


class PythonToolArgs(BaseModel):
    code: str = Field(
        ...,
        description="Python source code to execute inside the Code Interpreter service",
    )
    stdin: str | None = Field(
        default=None,
        description="Optional standard input payload supplied to the process",
    )
    timeout_ms: int | None = Field(
        default=None,
        ge=1_000,
        description="Optional execution timeout override in milliseconds",
    )


class ExecuteRequestFilePayload(BaseModel):
    path: str
    content_base64: str


class ExecuteRequestPayload(BaseModel):
    code: str
    timeout_ms: int
    stdin: str | None = None
    files: list[ExecuteRequestFilePayload] = Field(default_factory=list)


class WorkspaceFilePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    path: str
    kind: str = Field(default="file")
    content_base64: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, alias="size")


class PythonToolArtifact(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    path: str
    kind: str
    file_id: str | None = None
    display_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    error: str | None = None
    chat_file_type: ChatFileType | None = None


class PythonToolResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    stdout: str
    stderr: str | None = None
    exit_code: int | None = None
    execution_time_ms: int | None = None
    timeout_ms: int
    input_files: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[PythonToolArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


_PYTHON_DESCRIPTION = """
When you send a message containing Python code to python, it will be executed in an isolated environment.

The code you write will be placed into a file called `__main__.py` and run like `python __main__.py`. \
All other files present in the conversation will also be present in this same directory. E.g. if the \
user has uploaded three files, `analytics.csv`, `word.txt`, and `cat.png`, the directory structure will look like:

workspace/
  __main__.py
  analytics.csv
  word.txt
  cat.png

python will respond with the stdout of the `__main__.py` script as well as any new/edited files in the `workspace` directory. \
That means, if you want to get access to some result of the script you can either: 1) `print(<result>)` or 2) save \
a result to a file in the `workspace` directory.

Internet access for this session is disabled. Do not make external web requests or API calls as they will fail.

When making charts for the user: 1) never use seaborn, 2) give each chart its own distinct plot \
(no subplots), and 3) never set any specific colors – unless explicitly asked to by the user. \
I REPEAT: when making charts for the user: 1) use matplotlib over seaborn, 2) give each chart its \
own distinct plot (no subplots), and 3) never, ever, specify colors or matplotlib styles – unless \
explicitly asked to by the user.
""".strip()


class PythonTool(BaseTool):
    _NAME = "run_code_interpreter"
    _DESCRIPTION = _PYTHON_DESCRIPTION
    _DISPLAY_NAME = "Code Interpreter"

    def __init__(
        self,
        tool_id: int,
        base_url: str,
        default_timeout_ms: int,
        request_timeout_seconds: int,
        available_files: list[InMemoryChatFile] | None = None,
    ) -> None:
        if not base_url:
            raise ValueError(
                "Code Interpreter base URL must be configured to use the Python tool"
            )

        self._id = tool_id
        self._base_url = base_url.rstrip("/")
        self._default_timeout_ms = default_timeout_ms
        self._request_timeout_seconds = request_timeout_seconds
        self._available_files: dict[str, InMemoryChatFile] = {
            chat_file.file_id: chat_file for chat_file in available_files or []
        }

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
        return bool(CODE_INTERPRETER_BASE_URL)

    def tool_definition(self) -> dict:
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
        # Not supported for non-tool calling LLMs
        return None

    def run(
        self,
        override_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Generator[ToolResponse, None, None]:
        raw_requested_files = kwargs.pop("files", None)

        try:
            parsed_args = PythonToolArgs.model_validate(kwargs)
        except ValidationError as exc:
            logger.exception("Invalid arguments passed to PythonTool")
            raise ValueError("Invalid arguments supplied to Code Interpreter") from exc

        timeout_ms = parsed_args.timeout_ms or self._default_timeout_ms
        override_files = self._coerce_override_files(override_kwargs)
        requested_files = self._load_requested_files(raw_requested_files)
        request_files, input_metadata = self._prepare_request_files(
            override_files + requested_files
        )

        request_payload = ExecuteRequestPayload(
            code=parsed_args.code,
            timeout_ms=timeout_ms,
            stdin=parsed_args.stdin,
            files=request_files,
        )

        try:
            response = requests.post(
                f"{self._base_url}{_EXECUTE_PATH}",
                json=request_payload.model_dump(exclude_none=True),
                timeout=self._request_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.exception("Code Interpreter execution failed")
            raise ValueError(
                "Failed to reach the Code Interpreter service. Please try again later."
            ) from exc

        response_data = self._parse_response(response)
        artifacts = self._persist_artifacts(response_data.get("files", []))

        python_result = PythonToolResult(
            stdout=self._ensure_text(response_data.get("stdout", "")),
            stderr=self._optional_text(response_data.get("stderr")),
            exit_code=self._safe_int(response_data.get("exit_code")),
            execution_time_ms=self._safe_int(
                response_data.get("execution_time_ms")
                or response_data.get("duration_ms")
            ),
            timeout_ms=timeout_ms,
            input_files=input_metadata,
            artifacts=artifacts,
            metadata=self._extract_metadata(response_data.get("metadata")),
        )

        yield ToolResponse(id=PYTHON_TOOL_RESPONSE_ID, response=python_result)

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        result = self._extract_result(args)
        sections: list[str] = []

        if result.stdout:
            sections.append(self._format_section("stdout", result.stdout))
        if result.stderr:
            sections.append(self._format_section("stderr", result.stderr))

        if result.artifacts:
            file_lines = []
            for artifact in result.artifacts:
                display_name = artifact.display_name or Path(artifact.path).name
                if artifact.error:
                    file_lines.append(f"- {display_name}: {artifact.error}")
                elif artifact.file_id:
                    file_lines.append(
                        f"- {display_name} (file_id={artifact.file_id}, mime={artifact.mime_type or 'unknown'})"
                    )
                else:
                    file_lines.append(f"- {display_name}")
            sections.append("Generated files:\n" + "\n".join(file_lines))

        return (
            "\n\n".join(sections) if sections else "Execution completed with no output."
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        return self._extract_result(args).model_dump()

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        updated_prompt_builder = super().build_next_prompt(
            prompt_builder, tool_call_summary, tool_responses, using_tool_calling_llm
        )

        result = self._extract_result(tool_responses)
        if result.artifacts:
            existing_ids = {
                file.file_id for file in updated_prompt_builder.raw_user_uploaded_files
            }
            for artifact in result.artifacts:
                if not artifact.file_id:
                    continue
                chat_file = self._available_files.get(artifact.file_id)
                if not chat_file or chat_file.file_id in existing_ids:
                    continue
                if chat_file.file_type.is_text_file():
                    updated_prompt_builder.raw_user_uploaded_files.append(chat_file)
                    existing_ids.add(chat_file.file_id)
        return updated_prompt_builder

    def _load_requested_files(self, raw_files: Any) -> list[InMemoryChatFile]:
        if not raw_files:
            return []

        if not isinstance(raw_files, list):
            logger.warning(
                "Ignoring non-list 'files' argument passed to PythonTool: %r",
                type(raw_files),
            )
            return []

        loaded_files: list[InMemoryChatFile] = []
        for descriptor in raw_files:
            file_id: str | None = None
            desired_name: str | None = None

            if isinstance(descriptor, dict):
                raw_id = descriptor.get("id") or descriptor.get("file_id")
                if raw_id is not None:
                    file_id = str(raw_id)
                desired_name = (
                    descriptor.get("path")
                    or descriptor.get("name")
                    or descriptor.get("filename")
                )
            elif isinstance(descriptor, str):
                file_id = descriptor
            else:
                logger.warning(
                    "Skipping unsupported file descriptor passed to PythonTool: %r",
                    descriptor,
                )
                continue

            if not file_id:
                logger.warning("Skipping file descriptor without an id: %r", descriptor)
                continue

            chat_file = self._available_files.get(file_id)
            if not chat_file:
                chat_file = self._load_file_from_store(file_id)

            if not chat_file:
                logger.warning("Requested file '%s' could not be found", file_id)
                continue

            if desired_name and desired_name != chat_file.filename:
                chat_file = InMemoryChatFile(
                    file_id=chat_file.file_id,
                    content=chat_file.content,
                    filename=desired_name,
                    file_type=chat_file.file_type,
                )

            loaded_files.append(chat_file)

        return loaded_files

    def _load_file_from_store(self, file_id: str) -> InMemoryChatFile | None:
        try:
            file_store = get_default_file_store()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Failed to obtain file store instance: %s", exc)
            return None

        try:
            file_record = file_store.read_file_record(file_id)
        except Exception:
            logger.exception(
                "Failed to read file record for '%s' from file store", file_id
            )
            return None

        if not file_record:
            logger.warning("No file record found for requested file '%s'", file_id)
            return None

        try:
            file_io = file_store.read_file(file_id, mode="b")
        except Exception:
            logger.exception(
                "Failed to read file content for '%s' from file store", file_id
            )
            return None

        with closing(file_io):
            data = file_io.read() if hasattr(file_io, "read") else file_io

        if not isinstance(data, (bytes, bytearray)):
            logger.warning("File store returned non-bytes payload for '%s'", file_id)
            return None

        mime_type = (
            getattr(file_record, "file_type", None) or "application/octet-stream"
        )
        display_name = getattr(file_record, "display_name", None) or file_id
        chat_file_type = mime_type_to_chat_file_type(mime_type)

        return InMemoryChatFile(
            file_id=file_id,
            content=bytes(data),
            filename=display_name,
            file_type=chat_file_type,
        )

    def _coerce_override_files(
        self, override_kwargs: dict[str, Any] | None
    ) -> list[InMemoryChatFile]:
        if not override_kwargs:
            return []

        raw_files = override_kwargs.get("files")
        if not raw_files:
            return []

        coerced_files: list[InMemoryChatFile] = []
        for raw_file in raw_files:
            if isinstance(raw_file, InMemoryChatFile):
                coerced_files.append(raw_file)
            else:
                logger.warning(
                    "Ignoring non InMemoryChatFile entry passed to PythonTool override: %r",
                    type(raw_file),
                )
        return coerced_files

    def _prepare_request_files(
        self, chat_files: list[InMemoryChatFile]
    ) -> tuple[list[ExecuteRequestFilePayload], list[dict[str, Any]]]:
        request_files: list[ExecuteRequestFilePayload] = []
        input_metadata: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for chat_file in chat_files:
            file_id = str(chat_file.file_id)
            if file_id in seen_ids:
                continue
            seen_ids.add(file_id)

            self._available_files[file_id] = chat_file
            target_path = self._resolve_target_path(chat_file)

            request_files.append(
                ExecuteRequestFilePayload(
                    path=target_path,
                    content_base64=base64.b64encode(chat_file.content).decode("utf-8"),
                )
            )

            input_metadata.append(
                {
                    "id": file_id,
                    "path": target_path,
                    "name": chat_file.filename or file_id,
                    "chat_file_type": chat_file.file_type.value,
                }
            )

        return request_files, input_metadata

    def _persist_artifacts(self, files: list[Any]) -> list[PythonToolArtifact]:
        artifacts: list[PythonToolArtifact] = []
        if not files:
            return artifacts

        file_store = get_default_file_store()

        for raw_file in files:
            try:
                workspace_file = WorkspaceFilePayload.model_validate(raw_file)
            except ValidationError as exc:
                logger.warning("Skipping malformed workspace file entry: %s", exc)
                continue

            artifact = PythonToolArtifact(
                path=workspace_file.path, kind=workspace_file.kind
            )
            if workspace_file.kind != "file" or not workspace_file.content_base64:
                artifacts.append(artifact)
                continue

            try:
                binary = base64.b64decode(workspace_file.content_base64)
            except binascii.Error as exc:
                artifact.error = f"Failed to decode base64 content: {exc}"
                artifacts.append(artifact)
                continue

            mime_type = self._infer_mime_type(workspace_file, binary)
            display_name = Path(workspace_file.path).name or workspace_file.path

            try:
                file_id = file_store.save_file(
                    content=BytesIO(binary),
                    display_name=display_name,
                    file_origin=FileOrigin.GENERATED_REPORT,
                    file_type=mime_type,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to persist Code Interpreter artifact '%s'",
                    workspace_file.path,
                )
                artifact.error = f"Failed to persist artifact: {exc}"
                artifacts.append(artifact)
                continue

            chat_file_type = mime_type_to_chat_file_type(mime_type)
            chat_file = InMemoryChatFile(
                file_id=file_id,
                content=binary,
                filename=display_name,
                file_type=chat_file_type,
            )
            self._available_files[file_id] = chat_file

            artifact.file_id = file_id
            artifact.display_name = display_name
            artifact.mime_type = mime_type
            artifact.size_bytes = len(binary)
            artifact.chat_file_type = chat_file_type
            artifacts.append(artifact)

        return artifacts

    def _parse_response(self, response: requests.Response) -> dict[str, Any]:
        try:
            response_data = response.json()
        except json.JSONDecodeError as exc:
            logger.exception("Code Interpreter returned invalid JSON")
            raise ValueError(
                "Code Interpreter returned an invalid JSON response"
            ) from exc

        error_payload = response_data.get("error")
        if error_payload:
            if isinstance(error_payload, dict):
                message = error_payload.get("message") or json.dumps(error_payload)
            else:
                message = str(error_payload)
            raise ValueError(f"Code Interpreter reported an error: {message}")

        return response_data

    def _extract_result(self, responses: tuple[ToolResponse, ...]) -> PythonToolResult:
        for response in responses:
            if response.id == PYTHON_TOOL_RESPONSE_ID:
                if isinstance(response.response, PythonToolResult):
                    return response.response
                return PythonToolResult.model_validate(response.response)
        raise ValueError("No python tool result found in tool responses")

    def _resolve_target_path(self, chat_file: InMemoryChatFile) -> str:
        if chat_file.filename:
            return Path(chat_file.filename).name
        return chat_file.file_id

    def _infer_mime_type(
        self, workspace_file: WorkspaceFilePayload, binary: bytes
    ) -> str:
        if workspace_file.mime_type:
            return workspace_file.mime_type

        guess, _ = mimetypes.guess_type(workspace_file.path)
        if guess:
            return guess

        if self._looks_like_text(binary):
            return "text/plain"

        return "application/octet-stream"

    @staticmethod
    def _ensure_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text_value = str(value)
        return text_value if text_value else None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_metadata(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        return None

    @staticmethod
    def _looks_like_text(payload: bytes, sample_size: int = 2048) -> bool:
        sample = payload[:sample_size]
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True

    @staticmethod
    def _format_section(title: str, body: str) -> str:
        truncated = (
            body
            if len(body) <= _DEFAULT_RESULT_CHAR_LIMIT
            else body[: _DEFAULT_RESULT_CHAR_LIMIT - 3] + "..."
        )
        return f"{title}:\n{truncated}"
