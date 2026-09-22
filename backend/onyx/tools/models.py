from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, SerializeAsAny

from onyx.configs.constants import MessageType
from onyx.context.search.models import PersonaSearchInfo, SearchDoc
from onyx.file_store.models import (
    install_lazy_content_loader,
    maybe_materialize_lazy_content,
)
from onyx.utils.headers import HeaderItemDict


class CustomToolErrorInfo(BaseModel):
    is_auth_error: bool = False
    status_code: int
    message: str


class GeneratedImage(BaseModel):
    file_id: str
    url: str
    revised_prompt: str
    shape: str | None = None


class FileReadResult(BaseModel):
    type: Literal["file_read_result"] = "file_read_result"
    file_name: str
    file_id: str
    start_char: int
    end_char: int
    total_chars: int
    preview_start: str = ""
    preview_end: str = ""


class MemoryOperation(str, Enum):
    ADD = "add"
    UPDATE = "update"


class MemoryUpdated(BaseModel):
    type: Literal["memory_result"] = "memory_result"
    memory_text: str
    operation: MemoryOperation
    memory_id: int | None = None
    index: int | None = None


class ToolConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: int
    name: str
    description: str | None
    display_name: str | None
    in_code_tool_id: str | None
    enabled: bool
    openapi_schema: dict[str, JsonValue] | None
    mcp_input_schema: dict[str, JsonValue] | None
    custom_headers: list[HeaderItemDict] | None
    passthrough_auth: bool
    mcp_server_id: int | None
    oauth_config_id: int | None


class PersonaToolConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: int
    persona_name: str
    tools: list[ToolConfiguration]
    search: PersonaSearchInfo


class ToolCallException(Exception):
    """Exception raised for errors during tool calls."""

    def __init__(self, message: str, llm_facing_message: str):
        # This is the full error message which is used for tracing
        super().__init__(message)
        # LLM made tool calls are acceptable and not flow terminating, this is the message
        # which will populate the tool response.
        self.llm_facing_message = llm_facing_message


class ToolExecutionException(Exception):
    """Exception raise for errors during tool execution."""

    def __init__(self, message: str, emit_error_packet: bool = False):
        super().__init__(message)

        self.emit_error_packet = emit_error_packet


class SearchToolUsage(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    AUTO = "auto"


class CustomToolUserFileSnapshot(BaseModel):
    file_ids: list[str]  # References to saved images or CSVs


class CustomToolCallSummary(BaseModel):
    type: Literal["custom_tool_result"] = "custom_tool_result"
    tool_name: str
    response_type: str  # e.g., 'json', 'image', 'csv', 'graph'
    tool_result: CustomToolUserFileSnapshot | JsonValue
    error: CustomToolErrorInfo | None = None


class ChatMinimalTextMessage(BaseModel):
    message: str
    message_type: MessageType


class DynamicSchemaInfo(BaseModel):
    chat_session_id: UUID | None
    message_id: int | None
    user_id: UUID | None = None
    user_email: str | None = None


class ChatFile(BaseModel):
    """File from a chat session that can be passed to tools."""

    filename: str
    content: bytes
    file_id: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def lazy_from_filename(
        cls,
        *,
        filename: str,
        loader: Callable[[], bytes],
        file_id: str | None = None,
    ) -> "ChatFile":
        """Construct a ChatFile whose ``content`` is loaded on first access.

        Existing eager construction (``ChatFile(filename=..., content=...)``)
        is unchanged. PythonTool's ``.content`` access transparently triggers
        the loader and memoizes the result.
        """
        inst = cls(filename=filename, content=b"", file_id=file_id)
        install_lazy_content_loader(inst, loader)
        return inst

    def __getattribute__(self, name: str):
        if name == "content":
            maybe_materialize_lazy_content(self)
        return object.__getattribute__(self, name)


class ToolCallInfo(BaseModel):
    message_id: str
    parent_message_id: str | None = None
    # The parent_tool_call_id is the actual generated tool call id
    # It is NOT the DB ID which often does not exist yet when the ToolCallInfo is created
    # None if attached to the Chat Message directly
    parent_tool_call_id: str | None
    turn_index: int
    tab_index: int
    tool_name: str
    tool_call_id: str
    tool_id: int
    reasoning_tokens: str | None
    tool_call_arguments: dict[str, Any]
    tool_call_response: str
    result_metadata: SerializeAsAny[BaseModel] | None = None
    search_docs: list[SearchDoc] | None = None
    generated_images: list[GeneratedImage] | None = None
    generated_files: list[PythonExecutionFile] | None = None
    # File-store ids of blobs custom tools saved during the call.
    generated_file_ids: list[str] | None = None

    @property
    def execution_key(self) -> tuple[str, str]:
        return self.message_id, self.tool_call_id

    @property
    def parent_execution_key(self) -> tuple[str, str] | None:
        if self.parent_tool_call_id is None:
            return None
        if self.parent_message_id is None:
            raise ValueError("Child tool has no parent message identity")
        return self.parent_message_id, self.parent_tool_call_id


CHAT_SESSION_ID_PLACEHOLDER = "CHAT_SESSION_ID"
MESSAGE_ID_PLACEHOLDER = "MESSAGE_ID"
USER_ID_PLACEHOLDER = "USER_ID"
USER_EMAIL_PLACEHOLDER = "USER_EMAIL"


class BaseCiteableToolResult(BaseModel):
    """Base class for tool results that can be cited."""

    document_citation_number: int
    unique_identifier_to_strip_away: str | None = None
    type: str


class LlmInternalSearchResult(BaseCiteableToolResult):
    """Result from an internal search query"""

    type: Literal["internal_search"] = "internal_search"
    title: str
    excerpt: str
    metadata: dict[str, Any]


class LlmWebSearchResult(BaseCiteableToolResult):
    """Result from a web search query"""

    type: Literal["web_search"] = "web_search"
    url: str
    title: str
    snippet: str


class LlmOpenUrlResult(BaseCiteableToolResult):
    """Result from opening/fetching a URL"""

    type: Literal["open_url"] = "open_url"
    content: str


class PythonExecutionFile(BaseModel):
    """File generated during Python execution"""

    filename: str
    file_link: str


class LlmPythonExecutionResult(BaseModel):
    """Result from Python code execution"""

    type: Literal["python_execution"] = "python_execution"

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    generated_files: list[PythonExecutionFile]
    error: str | None = None
    # Set when some session files are absent
    staging_notice: str | None = None


class LlmBashExecutionResult(BaseModel):
    type: Literal["bash_execution"] = "bash_execution"
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    error: str | None = None
