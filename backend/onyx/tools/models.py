from __future__ import annotations

import abc
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
from onyx.integrations.models import (
    BUILTIN_ACTION_PREFIX,
    ActionSettings,
    ApprovalMode,
)
from onyx.tools.constants import FILE_READER_MAX_CHARS
from onyx.tools.tool_implementations.sandbox.models import (
    PublishedFile,
    SearchFileOffer,
    SpilledOutput,
)
from onyx.tools.tool_implementations.search.models import SearchContext
from onyx.utils.pydantic_util import OMITTED_WHEN_NONE


class ToolArguments[R](BaseModel):
    """The arguments of one tool call as the model sends them. `request`
    converts them into the request that the tool serves. It does not fail:
    the fields hold all validation. Arguments beyond the fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    @abc.abstractmethod
    def request(self) -> R: ...


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
    """A built-in tool of the agent. Integration actions come from
    ``integration_links``."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: int
    name: str
    description: str | None
    display_name: str | None
    in_code_tool_id: str | None
    enabled: bool


class IntegrationLinkConfiguration(BaseModel):
    """An integration that an agent or a task attaches, with its action
    settings."""

    model_config = ConfigDict(frozen=True)

    integration_id: int
    action_settings: ActionSettings


class IntegrationChatRequest(BaseModel):
    """The turn values that the tools of an integration need."""

    model_config = ConfigDict(frozen=True)

    persona_id: int
    integration_links: list[IntegrationLinkConfiguration]
    approval_mode: ApprovalMode
    chat_session_id: UUID | None = None
    message_id: int | None = None
    additional_headers: dict[str, str] = {}
    mcp_headers: dict[str, str] | None = None
    # From the tool options: the integrations to use, each with the action
    # keys to keep (None keeps each). None uses each integration.
    allowed_integrations: dict[int, frozenset[str] | None] | None = None


class PersonaToolConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: int
    persona_name: str
    tools: list[ToolConfiguration]
    search: PersonaSearchInfo
    # The persona__integration rows of the agent. For the default agent they
    # only give settings, such as the bot freeze, to the integrations that
    # are on for the user.
    integration_links: list[IntegrationLinkConfiguration] = []


class CapabilityEntry(BaseModel):
    """A built-in tool of the agent, by its tool row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["capability"] = "capability"
    tool_id: int

    def __str__(self) -> str:
        return f"tool {self.tool_id}"


class IntegrationEntry(BaseModel):
    """An integration of the agent. ``actions`` names the action keys to
    keep; None keeps each action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["integration"] = "integration"
    integration_id: int
    actions: list[str] | None = None


class ActionPreference(BaseModel):
    """One action of an integration, by its action key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["action"] = "action"
    integration_id: int
    action: str

    def __str__(self) -> str:
        return f"action {self.action} of integration {self.integration_id}"


ToolOptionsEntry = Annotated[
    CapabilityEntry | IntegrationEntry, Field(discriminator="type")
]
ToolPreference = Annotated[
    CapabilityEntry | ActionPreference, Field(discriminator="type")
]


class ToolOptions(BaseModel):
    """What a user or a caller picked for a turn. ``allowed`` None means
    each tool and each integration of the agent. The options only narrow: a
    Blocked action and the settings of the agent still win. ``preferred`` is
    a preference that the model can ignore."""

    model_config = ConfigDict(extra="forbid")

    allowed: list[ToolOptionsEntry] | None = None
    preferred: ToolPreference | None = None
    internal_search_filters: BaseFilters | None = None

    @model_validator(mode="before")
    @classmethod
    def _read_plugin_entries(cls, data: Any) -> Any:
        """The released mobile app names an integration by a ``plugin``
        entry, with the integration id as text (``plugin_ids`` of the tool
        list). Read it as the integration entry. An entry with another id
        names no integration, so it goes."""
        if not isinstance(data, dict) or not isinstance(data.get("allowed"), list):
            return data
        allowed: list[Any] = []
        for entry in data["allowed"]:
            if not isinstance(entry, dict) or entry.get("type") != "plugin":
                allowed.append(entry)
                continue
            plugin_id = str(entry.get("plugin_id"))
            if plugin_id.isdecimal():
                allowed.append(
                    {
                        **{k: v for k, v in entry.items() if k != "plugin_id"},
                        "type": "integration",
                        "integration_id": int(plugin_id),
                    }
                )
        return {**data, "allowed": allowed}

    def allows_tool(self, tool_id: int) -> bool:
        return self.allowed is None or any(
            isinstance(entry, CapabilityEntry) and entry.tool_id == tool_id
            for entry in self.allowed
        )

    def allowed_integrations(self) -> dict[int, frozenset[str] | None] | None:
        """The allowed integrations, each with the action keys to keep (None
        keeps each); None allows each integration."""
        if self.allowed is None:
            return None
        integrations: dict[int, frozenset[str] | None] = {}
        for entry in self.allowed:
            if not isinstance(entry, IntegrationEntry):
                continue
            kept = integrations.get(entry.integration_id, frozenset())
            integrations[entry.integration_id] = (
                None
                if entry.actions is None or kept is None
                else kept | frozenset(entry.actions)
            )
        return integrations


class IntegrationActionRef(BaseModel):
    """The integration action that a chat tool calls."""

    model_config = ConfigDict(frozen=True)

    integration_id: int
    action: str


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
    # The integration of an app tool, which has no tool row. The chat reads
    # it to open the sign-in of the integration after an auth error.
    integration_id: Annotated[int | None, OMITTED_WHEN_NONE] = None
    # The server's structured content, which code mode programs receive in
    # place of `tool_result`. Live only: not saved or streamed.
    structured_result: dict[str, JsonValue] | None = Field(default=None, exclude=True)
    # Set, with no `tool_result`, when the output went to the sandbox VM.
    spilled: Annotated[SpilledOutput | None, OMITTED_WHEN_NONE] = None

    @property
    def copies_output(self) -> bool:
        """Whether `tool_result` holds the tool's output, not file references."""
        return not isinstance(self.tool_result, CustomToolUserFileSnapshot)

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


def is_builtin_action(integration_id: int | None, action_id: str) -> bool:
    """Whether an approval scope or request is a built-in Onyx action's. A
    request of a deleted integration also has no integration, but an
    integration's action key."""
    return integration_id is None and action_id.startswith(BUILTIN_ACTION_PREFIX)


class ToolApprovalScope(BaseModel):
    """The gated action of a tool whose calls wait for the user's approval."""

    model_config = ConfigDict(frozen=True)

    # None for a built-in Onyx action, which no action policy covers; its
    # action key starts with BUILTIN_ACTION_PREFIX.
    integration_id: int | None
    # The action key: the MCP tool name, the OpenAPI operationId, or
    # `onyx:<operation>` for a built-in action. With the integration, it keys
    # the action policy and session grants.
    action_id: str

    @model_validator(mode="after")
    def builtin_action_has_builtin_key(self) -> Self:
        if self.integration_id is None and not self.action_id.startswith(
            BUILTIN_ACTION_PREFIX
        ):
            raise ValueError(
                f"An action with no integration needs a {BUILTIN_ACTION_PREFIX} key"
            )
        return self


class ToolApprovalDetails(BaseModel):
    """What the approval card of one call shows."""

    # The card's headline.
    display_name: str
    # None shows the call's arguments.
    payload: dict[str, JsonValue] | None = None


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
    # A code mode program made the call: its full value stays in the program's
    # memory, so a tool with a large full value keeps less.
    program_call: bool = False
    # The chat stages the files of search results for the Python tool, so a
    # search result names them by their staged file names.
    python_stages_search_files: bool = False
    # In a sandbox chat: copies the files of a search's shown results into
    # the VM, and the result names them by their paths.
    sandbox_search_files: SearchFileOffer | None = None
    # The name that the model calls a tool by, by its tool name: in code mode,
    # its program function's (ChatFeature.called_name). Results that tell the
    # model to call another tool name it so.
    called_name: Callable[[str], str] = Field(default=str, exclude=True)


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
    # Files that the call published from the sandbox.
    published_files: list[PublishedFile] | None = None

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
    code: str = Field(description="Python source code to execute")


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


class SearchResult(BaseModel):
    """One document of a search-like tool result, as the model and code mode
    programs read it."""

    document: int = Field(description="Citation number. Cite it in the answer as [n].")
    title: str
    updated_at: Annotated[str | None, OMITTED_WHEN_NONE] = None
    authors: Annotated[list[str] | None, OMITTED_WHEN_NONE] = None
    source_type: Annotated[str | None, OMITTED_WHEN_NONE] = None
    url: Annotated[str | None, OMITTED_WHEN_NONE] = None
    document_identifier: Annotated[str | None, OMITTED_WHEN_NONE] = None
    file_name: Annotated[str | None, OMITTED_WHEN_NONE] = None
    content: str
    metadata: Annotated[str | None, OMITTED_WHEN_NONE] = Field(
        default=None, description="JSON-encoded metadata of the document."
    )


class SearchResults(BaseModel):
    """The content of internal search, web search, and open URL results."""

    results: list[SearchResult]
    note: Annotated[str | None, OMITTED_WHEN_NONE] = None
    message: Annotated[str | None, OMITTED_WHEN_NONE] = None


class CodeModeExposure(str, Enum):
    """How code mode offers a tool to the model."""

    # Its own tool beside the code mode run tool, never a function inside programs. Tools
    # that wait for child runs must use this: a program cannot wait for them.
    DIRECT = "direct"
    # A function whose stub the run tool description lists.
    IMMEDIATE = "immediate"
    # A function that programs can call but the description does not list; the
    # model finds it with the program search function.
    DEFERRED = "deferred"


class CodeModeFunctionName(BaseModel):
    """A tool's code mode function name before it becomes a Python identifier:
    `<namespace>__<name>`, or `name` without a namespace."""

    model_config = ConfigDict(frozen=True)

    name: str
    # A group of tools, such as the MCP server of an MCP tool.
    namespace: str | None = None
    # What the namespace's tools are for, from the group's owner, such as an
    # MCP integration's description. The run tool description lists
    # the first line beside each deferred namespace.
    namespace_description: str | None = None

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
    # The program gets the result details as JSON, as `model` (a class of the
    # details) declares them; the content is for the model only.
    DETAILS = "details"


class CodeModeResultSpec(BaseModel):
    """The value a tool returns to a code mode program, and its stub type."""

    model_config = ConfigDict(frozen=True)

    kind: CodeModeResultKind
    # The stub's return annotation; the model's name when unset, else Any.
    annotation: str | None = None
    # The model of the value that the program gets. For DETAILS it is a class
    # of the result details; otherwise the content is its JSON. The stub module
    # declares it, and the models of its fields, as TypedDicts of the same names.
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

    @model_validator(mode="after")
    def details_need_model(self) -> Self:
        if self.kind is CodeModeResultKind.DETAILS and self.model is None:
            raise ValueError("A DETAILS result needs the model of its details")
        return self

    @property
    def type_annotation(self) -> str:
        if self.annotation is not None:
            return self.annotation
        return self.model.__name__ if self.model is not None else "Any"


DEFAULT_CODE_MODE_RESULT = CodeModeResultSpec(kind=CodeModeResultKind.AUTO)
