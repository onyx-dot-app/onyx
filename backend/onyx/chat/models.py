from collections.abc import Iterator
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    TypeAdapter,
    field_serializer,
    field_validator,
)

from onyx.agents.models import (
    AgentInfo,
    CompactionCheckpoint,
    CompactionMetadata,
    RunFailure,
    RunStatus,
    StepRecord,
    messages_from_steps,
)
from onyx.agents.tools import InputDecision
from onyx.cache.interface import CacheBackend
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.configs.constants import MessageType
from onyx.context.models import UserMemoryContext
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.db.enums import IncognitoRecordMode
from onyx.deep_research.models import ResearchAgentCallResult, ResearchConfiguration
from onyx.file_store.models import (
    ChatLoadedFile,
    ExtractedContextFiles,
    FileDescriptor,
    FileToolMetadata,
)
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import (
    GenerationRequestParams,
    Message,
    ReasoningEffort,
    ToolResultMessage,
)
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.models import (
    MessageResponseIDInfo,
    MultiModelMessageResponseIDInfo,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    CitationInfo,
    Packet,
    StreamingError,
)
from onyx.tools.file_snapshot import SavedChatFile, SavedContextFiles
from onyx.tools.models import (
    ChatFile,
    GeneratedImage,
    PersonaToolConfiguration,
    SearchToolUsage,
    ToolCallInfo,
)
from onyx.tools.tool_implementations.custom.base_tool_types import ToolResultType
from onyx.tools.tool_implementations.search.models import SearchToolState

MAX_DISCOVERED_AGENTS = 128
_MESSAGE_ADAPTER = TypeAdapter(Message)
_INCOGNITO_SOURCE_DETAILS = TypeAdapter(
    Annotated[SearchDocsResponse | ResearchAgentCallResult, Field(discriminator="type")]
)


class PromptMetadata(CompactionMetadata):
    token_count: int | None = None
    image_files: list[ChatLoadedFile] | None = None
    image_token_count: int = 0
    should_cache: bool = False
    file_id: str | None = None
    is_reminder: bool = False
    omit_tool_result_content: bool = False


class FileContextResult(BaseModel):
    """Result of building a file's LLM context representation."""

    message: Message
    tool_metadata: FileToolMetadata


class CitationMode(str, Enum):
    """Defines how citations should be handled in the output.

    REMOVE: Citations are completely removed from output text.
            No CitationInfo objects are emitted.
            Use case: When you need to remove citations from the output if they are not shared with the user
            (e.g. in discord bot, public slack bot).

    KEEP_MARKERS: Original citation markers like [1], [2] are preserved unchanged.
                  No CitationInfo objects are emitted.
                  Use case: When you need to track citations in research agent and later process
                  them with collapse_citations() to renumber.

    HYPERLINK: Citations are replaced with markdown links like [[1]](url).
               CitationInfo objects are emitted for UI tracking.
               Use case: Final reports shown to users with clickable links.
    """

    REMOVE = "remove"
    KEEP_MARKERS = "keep_markers"
    HYPERLINK = "hyperlink"


class PresentationMode(str, Enum):
    ANSWER = "answer"
    PLAN = "plan"
    REPORT = "report"
    CODING_THINKING = "coding_thinking"
    CODING_ANSWER = "coding_answer"
    SILENT = "silent"


class MessageRendering(BaseModel):
    """Chat display settings retained with one generated message for history replay."""

    mode: PresentationMode = PresentationMode.ANSWER
    text_as_thinking: bool = False
    think_tool: str | None = None
    is_clarification: bool = False
    citation_mode: CitationMode | None = None
    citation_documents: dict[int, str] = Field(default_factory=dict)
    document_ids: list[str] = Field(default_factory=list)
    pre_answer_seconds: float | None = None


class ResponseRecord(BaseModel):
    """Accepted steps and execution outcomes, without live application objects."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    agent_id: str | None = None
    agent_path: str = "/root"
    agent_description: str = ""
    restoration_config: ResearchConfiguration | None = None
    previous_run_id: str | None = None
    parent_run_id: str | None = None
    parent_tool_call_id: str | None = None
    # The model message containing the call, within parent_run_id.
    parent_message_id: str | None = None
    input_messages: list[Message] = Field(default_factory=list)
    steps: list[StepRecord] = Field(default_factory=list)
    answer_step_index: int | None = None
    child_runs: list["ResponseRecord"] = Field(default_factory=list)
    status: RunStatus
    failure: RunFailure | None = None
    checkpoint: CompactionCheckpoint | None = None

    @property
    def messages(self) -> list[Message]:
        return messages_from_steps(self.steps)


class HistoryLink(BaseModel):
    id: int
    parent_message_id: int | None
    chat_session_id: UUID


class SessionAncestor(BaseModel):
    id: UUID
    agent_name: str | None
    parent_id: UUID | None


class SavedResponse(BaseModel):
    message_id: int
    root_message_id: int
    root_session_id: UUID
    agent: AgentInfo
    response: ResponseRecord


class ResponseStatus(BaseModel):
    message_id: int
    root_message_id: int
    root_session_id: UUID
    parent_agent_id: str | None
    status: RunStatus


class ResponseAncestry(BaseModel):
    message_id: int
    session_id: UUID
    status: RunStatus | None
    spawned_by_message_id: int | None
    parent_session_id: UUID | None
    parent_response_id: int | None


class ChatBranch(BaseModel):
    chat_session_id: UUID
    message_ids: list[int]


class ResponseLink(BaseModel):
    id: int
    chat_session_id: UUID
    previous_response_id: int | None
    root_id: int
    status: RunStatus


class IncognitoContext(BaseModel):
    """A session's history plus the version that makes save a compare-and-set."""

    version: int
    messages: list[Message]
    previous_run_id: str | None = None


class IncognitoAgentState(BaseModel):
    parent_agent_id: str | None = None
    agent_id: str
    agent_path: str
    description: str
    configuration: ResearchConfiguration | None
    responses: list[ResponseRecord]
    sources: dict[int, SearchDoc] = Field(default_factory=dict)


class IncognitoAgentResponse(BaseModel):
    replay_digest: str
    agents: list[IncognitoAgentState] = Field(default_factory=list)


def _read_incognito_message(value: dict[str, JsonValue] | Message) -> Message:
    if not isinstance(value, dict):
        return value
    data = dict(value)
    metadata = PromptMetadata.model_validate(data.pop("metadata", {}))
    details = data.pop("details", None)
    message = _MESSAGE_ADAPTER.validate_python(data)
    message.metadata = metadata
    if details is not None and isinstance(message, ToolResultMessage):
        message.details = _INCOGNITO_SOURCE_DETAILS.validate_python(details)
    return message


def serialize_incognito_message(message: Message) -> dict[str, JsonValue]:
    """Retain replay text and citation sources, excluding execution files and state."""
    metadata = (
        message.metadata
        if isinstance(message.metadata, PromptMetadata)
        else PromptMetadata()
    )
    data: dict[str, JsonValue] = message.model_dump(mode="json", exclude={"details"})
    data["metadata"] = metadata.model_dump(exclude={"image_files", "image_token_count"})
    if isinstance(message, ToolResultMessage):
        if isinstance(message.details, SearchDocsResponse):
            data["details"] = message.details.model_dump(
                mode="json", include={"type", "search_docs", "citation_mapping"}
            )
        elif isinstance(message.details, ResearchAgentCallResult):
            data["details"] = message.details.model_dump(mode="json")
    return data


IncognitoMessage = Annotated[
    Message,
    BeforeValidator(_read_incognito_message),
    PlainSerializer(serialize_incognito_message),
]


class IncognitoState(BaseModel):
    version: int = Field(default=0, ge=0, le=999_999_999_999_999)
    messages: list[IncognitoMessage] = Field(default_factory=list)
    previous_run_id: str | None = None
    responses: dict[str, IncognitoAgentResponse] = Field(default_factory=dict)


class SavedAgentContext(BaseModel):
    """Saved history, settings, and sources used to rebuild an agent."""

    agent_id: str
    configuration: ResearchConfiguration | None
    messages: list[Message]
    checkpoint: CompactionCheckpoint | None = None
    previous_run_id: str | None = None
    sources: dict[int, SearchDoc] = Field(default_factory=dict)


class ChatMessageMetadata(BaseModel):
    """Source references and display settings attached to a generated chat message."""

    sources: dict[int, SearchDoc] = Field(default_factory=dict)
    documents: list[SearchDoc] = Field(default_factory=list)
    include_citations: bool = True
    elapsed_seconds: float = 0


class ToolRecordReference(BaseModel):
    message_id: str
    tool_call_id: str
    record_id: int


class ChatExecutionRecord(BaseModel):
    response: ResponseRecord
    presentation: dict[str, MessageRendering] = Field(default_factory=dict)
    tool_records: list[ToolRecordReference] = Field(default_factory=list)


class ChatHistoryMessage(BaseModel):
    id: int
    message_type: MessageType
    message: str
    token_count: int
    files: list[FileDescriptor]
    is_clarification: bool
    response_messages: list[Message]
    checkpoint: CompactionCheckpoint | None = None


class CustomToolResponse(BaseModel):
    response: ToolResultType
    tool_name: str


class CreateChatSessionID(BaseModel):
    chat_session_id: UUID
    # Echoes the pinned mode so the client can verify the server honored an
    # incognito request. A server that omits it did not.
    incognito: bool = False


AnswerStreamPart = (
    Packet
    | MessageResponseIDInfo
    | MultiModelMessageResponseIDInfo
    | StreamingError
    | CreateChatSessionID
)

AnswerStream = Iterator[AnswerStreamPart]


class ToolCallResponse(BaseModel):
    """Tool call with full details for non-streaming response."""

    tool_name: str
    tool_arguments: dict[str, Any]
    tool_result: str
    search_docs: list[SearchDoc] | None = None
    generated_images: list[GeneratedImage] | None = None
    # Reasoning that led to the tool call
    pre_reasoning: str | None = None


class ChatBasicResponse(BaseModel):
    # This is built piece by piece, any of these can be None as the flow could break
    answer: str
    answer_citationless: str

    top_documents: list[SearchDoc]

    error_msg: str | None
    message_id: int
    citation_info: list[CitationInfo]


class ChatFullResponse(BaseModel):
    """Complete non-streaming response with all available data.
    NOTE: This model is used for the core flow of the Onyx application, any changes to it should be reviewed and approved by an
    experienced team member. It is very important to 1. avoid bloat and 2. that this remains backwards compatible across versions.
    """

    # Core response fields
    answer: str
    answer_citationless: str
    pre_answer_reasoning: str | None = None
    tool_calls: list[ToolCallResponse] = []

    # Documents & citations
    top_documents: list[SearchDoc]
    citation_info: list[CitationInfo]

    # Metadata
    message_id: int
    chat_session_id: UUID | None = None
    # Echoes the pinned mode for newly-created sessions, like the streaming
    # packet does. A server that omits it did not honor an incognito request.
    incognito: bool = False
    error_msg: str | None = None


class ChatHistoryResult(BaseModel):
    """Result of converting chat history to simple format.

    Bundles the simple messages with metadata for every text file that was
    injected into the history. After context-window truncation drops older
    messages, callers compare surviving ``file_id`` tags against this map
    to discover "forgotten" files whose metadata should be provided to the
    FileReaderTool.
    """

    messages: list[Message]
    all_injected_file_metadata: dict[str, FileToolMetadata]


class PreparedHistory(BaseModel):
    history: ChatHistoryResult
    files: list[ChatFile]


class SearchParams(BaseModel):
    """Resolved search filter IDs and search-tool usage for a chat turn."""

    project_id_filter: int | None
    persona_id_filter: int | None
    search_usage: SearchToolUsage


class ChatSearchResult(SearchDocsResponse):
    """Search documents with files staged before the tool result is committed."""

    staged_files: list[ChatFile]

    @field_serializer("staged_files")
    def serialize_staged_files(self, files: list[ChatFile]) -> list[SavedChatFile]:
        return [SavedChatFile.capture(file) for file in files]

    @field_validator("staged_files", mode="before")
    @classmethod
    def restore_staged_files(cls, value: object) -> list[ChatFile]:
        if not isinstance(value, list):
            raise ValueError("Staged files must be a list")
        return [
            file
            if isinstance(file, ChatFile)
            else SavedChatFile.model_validate(file).restore()
            for file in value
        ]


class ToolHistorySnapshot(BaseModel):
    """Application records derived from accepted tool results."""

    model_config = ConfigDict(frozen=True)

    tool_calls: list[ToolCallInfo]
    all_search_docs: dict[str, SearchDoc]
    citation_to_doc: dict[int, SearchDoc]


class ChatResponseSnapshot(BaseModel):
    """Detached response data for one persistence attempt."""

    model_config = ConfigDict(frozen=True)

    answer: str | None
    reasoning: str | None
    request_params: GenerationRequestParams | None
    citation_to_doc: dict[int, SearchDoc]
    tool_calls: list[ToolCallInfo]
    is_clarification: bool
    all_search_docs: dict[str, SearchDoc]
    citation_info: list[CitationInfo] = Field(default_factory=list)
    top_documents: list[SearchDoc] = Field(default_factory=list)
    pre_answer_processing_time: float | None
    response: ResponseRecord | None
    presentation: dict[str, MessageRendering] = Field(default_factory=dict)
    cancelled: bool
    delivery_failed: bool = False
    error: str | None = None


class PersistenceStatus(str, Enum):
    SAVED = "saved"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"


PERSISTENCE_ERROR_MESSAGES = {
    PersistenceStatus.FAILED: "The response could not be saved. Please try again.",
    PersistenceStatus.UNCONFIRMED: "The response save has not completed. Reload this conversation.",
}


class PendingChatResponseSave(BaseModel):
    response: ChatResponseSnapshot
    deadline: float


class ChatResponseOutcome(BaseModel):
    """Frozen execution output and the application's persistence outcome."""

    model_config = ConfigDict(frozen=True)

    response: ChatResponseSnapshot
    persistence_status: PersistenceStatus

    @property
    def error(self) -> str | None:
        errors = [
            self.response.error,
            PERSISTENCE_ERROR_MESSAGES.get(self.persistence_status),
        ]
        return "\n".join(error for error in errors if error) or None


class AvailableFiles(BaseModel):
    """Separated file IDs for the FileReaderTool so it knows which loader to use."""

    # IDs from the ``user_file`` table (project / persona-attached files).
    user_file_ids: list[UUID] = []
    # IDs from the ``file_record`` table (chat-attached files).
    chat_file_ids: list[UUID] = []


class ChatReminderContext(BaseModel):
    ran_image_gen: bool
    has_open_url_tool: bool
    out_of_cycles: bool
    persona_task_prompt: str | None
    has_context_documents: bool


class ContextDocument(BaseModel):
    document: int
    title: str | None = None
    contents: str


class ContextDocuments(BaseModel):
    documents: list[ContextDocument] = Field(default_factory=list)


class SearchPassage(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    document: int
    content: str


class SearchPassages(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    results: list[SearchPassage]


class ChatPrompt(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    system_prompt: Message | None
    user_info_prompt: Message | None = None
    custom_prompt: Message | None
    reminder: Message | None


class PersonaPromptConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    system_prompt: str | None
    task_prompt: str | None
    datetime_aware: bool
    replace_base_system_prompt: bool


class ChatFeatureState(BaseModel):
    """Chat settings and accumulated state needed to resume suspended execution."""

    kind: Literal["chat.state.v1"] = "chat.state.v1"
    persona: PersonaPromptConfig | None
    context_files: SavedContextFiles
    file_metadata: dict[str, FileToolMetadata] | None
    memory: UserMemoryContext | None
    reasoning_effort: ReasoningEffort
    include_citations: bool
    inject_memories: bool
    forced_tool_id: int | None
    base_prompt: str
    custom_prompt: str | None
    reminders_enabled: bool

    elapsed_seconds: float
    citation_sources: dict[int, SearchDoc]
    citation_mapping: dict[int, str]
    gathered_documents: list[SearchDoc]
    chat_files: list[SavedChatFile]
    has_called_search_tool: bool
    ran_image_gen: bool
    search_tools: dict[str, SearchToolState]


class ReservedChatResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    llm: LLM
    message_id: int
    display_name: str


class ChatTurnSetup(BaseModel):
    """Request values and service references shared by model executions."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    new_msg_req: SendMessageRequest
    chat_session_id: UUID
    chat_session_project_id: int | None
    # The session's pinned recording policy. None is an ordinary chat.
    incognito_record_mode: IncognitoRecordMode | None
    persona_id: int
    persona: PersonaPromptConfig
    base_system_prompt: str
    tool_configuration: PersonaToolConfiguration
    research_tool_id: int | None
    checkpoint: CompactionCheckpoint | None
    user_message_id: int
    user_identity: LLMUserIdentity
    responses: list[ReservedChatResponse]
    messages: list[Message]
    input_messages: list[Message]
    previous_run_id: str | None = None
    extracted_context_files: ExtractedContextFiles
    # Fences processing status and identifies the buffered stream.
    stream_id: int
    reasoning_effort: ReasoningEffort
    search_params: SearchParams
    all_injected_file_metadata: dict[str, FileToolMetadata]
    available_files: AvailableFiles
    forced_tool_id: int | None
    chat_files_for_tools: list[ChatFile]
    custom_agent_prompt: str | None
    user_memory_context: UserMemoryContext
    # For deep research: was the last assistant message a clarification request?
    skip_clarification: bool
    cache: CacheBackend
    admission: ChatTurnAdmission
    # Execution params forwarded to per-model tool construction
    slack_context: SlackContext | None
    litellm_additional_headers: dict[str, str] | None = None
    custom_tool_additional_headers: dict[str, str] | None
    mcp_headers: dict[str, str] | None


class ResponseOwner(BaseModel):
    token: UUID
    root_message_id: int
    ownership_version: int | None = None


class CheckpointPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    value: dict[str, JsonValue]


class CheckpointToolAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    decision: InputDecision
    result: dict[str, JsonValue] | None = None


class CheckpointBinding(BaseModel):
    """Application identity; validating this record does not authorize access."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    response_id: str


class MessagePayload(BaseModel):
    metadata: JsonValue = None
    details: JsonValue = None
    cacheable: bool = False


class ResponseCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    history_digest: str
    response_digest: str
    binding: CheckpointBinding
    revision: int
    progress: dict[str, JsonValue]
    compaction_checkpoint: CompactionCheckpoint | None
    # Request display settings are saved by chat finalization, after execution ends.
    request_params: GenerationRequestParams | None
    message_payloads: list[MessagePayload]
    input_payloads: list[MessagePayload]


class SavedCheckpoint(BaseModel):
    ownership_version: int
    data: ResponseCheckpoint


class ToolReplayData(BaseModel):
    """Saved application data needed to replay one accepted tool invocation."""

    tool_id: int | None
    search_docs: list[SearchDoc] = Field(default_factory=list)


class ResponseReplayData(BaseModel):
    """Detached source documents and tool identities for response replay."""

    tools: dict[tuple[str, str], ToolReplayData]
    documents: dict[str, SearchDoc]
