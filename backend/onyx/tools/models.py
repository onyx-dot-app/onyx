from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Callable, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from onyx.configs.constants import MessageType
from onyx.context.models import UserMemoryContext
from onyx.context.search.models import BaseFilters, PersonaSearchInfo, SearchDoc
from onyx.file_store.models import (
    install_lazy_content_loader,
    maybe_materialize_lazy_content,
)
from onyx.tools.constants import FILE_READER_MAX_CHARS
from onyx.tools.tool_implementations.search.models import SearchContext
from onyx.utils.headers import HeaderItemDict


class CustomToolErrorInfo(BaseModel):
    is_unreachable: bool = False
    is_auth_error: bool = False
    status_code: int | None
    message: str


class GeneratedImage(BaseModel):
    file_id: str
    url: str
    revised_prompt: str
    shape: str | None = None


class FileReaderArguments(BaseModel):
    file_id: str = Field(description="The UUID of the file to read.")
    start_char: int = Field(
        default=0,
        description="Character offset to start reading from. Use null for the default of 0.",
    )
    num_chars: int = Field(
        default=FILE_READER_MAX_CHARS,
        description=(
            f"Number of characters to return (max {FILE_READER_MAX_CHARS}). "
            f"Use null for the default of {FILE_READER_MAX_CHARS}."
        ),
    )


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


class MemoryArguments(BaseModel):
    memory: str = Field(
        description=(
            "The text of the memory to add or update. "
            "Should be a concise, standalone statement that "
            "captures the key information. For example: "
            "'User prefers dark mode' or 'User's favorite frontend framework is React'."
        )
    )


class KnowledgeGraphArguments(BaseModel):
    query: str = Field(description="What to search for")


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
    mcp_output_schema: dict[str, JsonValue] | None
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


class ChatToolSelection(BaseModel):
    """The tools and search filters the user selected for a chat; every later
    turn uses them."""

    model_config = ConfigDict(extra="forbid")

    allowed_tool_ids: list[int] | None = None
    preferred_tool_id: int | None = None
    internal_search_filters: BaseFilters | None = None


class ToolCallException(Exception):
    """Exception raised for errors during tool calls."""

    def __init__(self, message: str, llm_facing_message: str):
        # This is the full error message which is used for tracing
        super().__init__(message)
        # LLM made tool calls are acceptable and not flow terminating, this is the message
        # which will populate the tool response.
        self.llm_facing_message = llm_facing_message


class ToolExecutionError(BaseModel):
    """A tool failure that must also be shown to the user."""

    type: Literal["tool_execution_error"] = "tool_execution_error"
    message: str


class ToolExecutionException(Exception):
    """Tool execution failed."""

    def __init__(self, message: str, emit_error_packet: bool = False) -> None:
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
    # JSON field names alone cannot distinguish output from file references.
    tool_result: JsonValue | CustomToolUserFileSnapshot = Field(
        union_mode="left_to_right"
    )
    error: CustomToolErrorInfo | None = None
    # The server's structured content, which code mode programs receive in
    # place of `tool_result`. Live only: not saved or streamed.
    structured_result: dict[str, JsonValue] | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def restore_file_references(self) -> Self:
        if self.response_type in {"image", "csv"}:
            self.tool_result = CustomToolUserFileSnapshot.model_validate(
                self.tool_result
            )
        return self


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


class ToolContext(BaseModel):
    """Application data available to each tool in an agent step."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_memory_context: UserMemoryContext | None = None
    user_info: str | None = None
    citation_mapping: dict[int, str] = Field(default_factory=dict)
    next_citation_num: int = 1
    # On repeat searches, defer to the model's new queries instead of repeating
    # the expansion flow that may have produced poor results on the first pass.
    skip_search_query_expansion: bool = False
    search_context: SearchContext = Field(default_factory=SearchContext)
    chat_files: list[ChatFile] = Field(default_factory=list)
    url_snippet_map: dict[str, str] = Field(default_factory=dict)
    # When False, don't pass memory context to search tools for query expansion
    # (but still pass it to the memory tool for persistence)
    inject_memories_in_prompt: bool = True


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
    # None for a tool that has no tool row, such as code mode.
    tool_id: int | None
    reasoning_tokens: str | None
    tool_call_arguments: dict[str, Any]
    tool_call_response: str
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


class PythonArguments(BaseModel):
    code: str


class PythonExecutionFile(BaseModel):
    """File generated during Python execution"""

    filename: str
    file_link: str


class PythonExecutionDelta(BaseModel):
    """New process output from Python execution."""

    stdout: str = ""
    stderr: str = ""


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


class BashArguments(BaseModel):
    cmd: str


class LlmBashExecutionResult(BaseModel):
    type: Literal["bash_execution"] = "bash_execution"
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    error: str | None = None


def _is_none(value: object) -> bool:
    return value is None


# A key that the JSON leaves out when it has no value.
_OMITTED_WHEN_NONE = Field(exclude_if=_is_none)


class SearchResult(BaseModel):
    """One document of a search-like tool result, as the model and code mode
    programs read it."""

    document: int = Field(description="Citation number. Cite it in the answer as [n].")
    title: str
    updated_at: Annotated[str | None, _OMITTED_WHEN_NONE] = None
    authors: Annotated[list[str] | None, _OMITTED_WHEN_NONE] = None
    source_type: Annotated[str | None, _OMITTED_WHEN_NONE] = None
    url: Annotated[str | None, _OMITTED_WHEN_NONE] = None
    document_identifier: Annotated[str | None, _OMITTED_WHEN_NONE] = None
    file_name: Annotated[str | None, _OMITTED_WHEN_NONE] = None
    content: str
    metadata: Annotated[str | None, _OMITTED_WHEN_NONE] = Field(
        default=None, description="JSON-encoded metadata of the document."
    )


class SearchResults(BaseModel):
    """The content of internal search, web search, and open URL results."""

    results: list[SearchResult]
    note: Annotated[str | None, _OMITTED_WHEN_NONE] = None
    message: Annotated[str | None, _OMITTED_WHEN_NONE] = None


class CodeModeExposure(str, Enum):
    """How code mode offers a tool to the model."""

    # Its own tool beside `execute_code`, never a function inside programs. Tools
    # that wait for child runs must use this: a program cannot wait for them.
    DIRECT = "direct"
    # A function whose stub the `execute_code` description lists.
    IMMEDIATE = "immediate"
    # A function that programs can call but the description does not list; the
    # model finds it with `tool_search`.
    DEFERRED = "deferred"


class CodeModeFunctionName(BaseModel):
    """A tool's code mode function name before it becomes a Python identifier:
    `<namespace>__<name>`, or `name` without a namespace."""

    model_config = ConfigDict(frozen=True)

    name: str
    # A group of tools, such as the MCP server of an MCP tool.
    namespace: str | None = None

    @property
    def qualified(self) -> str:
        return self.name if self.namespace is None else f"{self.namespace}__{self.name}"


class CodeModeResultKind(str, Enum):
    """How a code mode program receives a tool's result content."""

    # The content is a JSON object; anything else is raised as an error.
    JSON_OBJECT = "json_object"
    # The content is passed to the program as a string.
    TEXT = "text"
    # JSON when the content parses, else the string.
    AUTO = "auto"
    # An MCP result envelope `{"tool_result": value}`; the program gets the value.
    MCP = "mcp"


class CodeModeResultSpec(BaseModel):
    """The value a tool returns to a code mode program, and its stub type."""

    model_config = ConfigDict(frozen=True)

    kind: CodeModeResultKind
    # The stub's return annotation; the model's name when unset, else Any.
    annotation: str | None = None
    # The model whose JSON the content is. The stub module declares it, and the
    # models of its fields, as TypedDicts of the same names.
    model: type[BaseModel] | None = None
    # JSON Schema of the value, from the tool's server. The stub types the value
    # from it, and declares a top-level object as a TypedDict.
    output_schema: dict[str, JsonValue] | None = None
    # Docstring note on the returned value.
    returns: str | None = None
    # Docstring note on how a program should call the tool, such as batching.
    usage: str | None = None
    # The tool numbers its results for citation and needs a citation block.
    cites: bool = False

    @property
    def type_annotation(self) -> str:
        if self.annotation is not None:
            return self.annotation
        return self.model.__name__ if self.model is not None else "Any"


DEFAULT_CODE_MODE_RESULT = CodeModeResultSpec(kind=CodeModeResultKind.AUTO)
