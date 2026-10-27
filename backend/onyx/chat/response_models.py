"""Detached accepted responses and their application presentation settings."""

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
)

from onyx.agents.models import (
    AgentInfo,
    CompactionCheckpoint,
    RunFailure,
    RunStatus,
    StepRecord,
    messages_from_steps,
)
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchConfiguration
from onyx.llm.models import GenerationRequestParams, Message
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.tools.file_snapshot import SavedChatFile
from onyx.tools.models import ChatFile
from onyx.tools.records import RecordedToolCallInfo


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


class ToolHistorySnapshot(BaseModel):
    """Application records derived from accepted tool results."""

    model_config = ConfigDict(frozen=True)

    tool_calls: list[RecordedToolCallInfo]
    all_search_docs: dict[str, SearchDoc]
    citation_to_doc: dict[int, SearchDoc]


class ChatResponseSnapshot(BaseModel):
    """Detached response data for one persistence attempt."""

    model_config = ConfigDict(frozen=True)

    answer: str | None
    reasoning: str | None
    request_params: GenerationRequestParams | None
    citation_to_doc: dict[int, SearchDoc]
    tool_calls: list[RecordedToolCallInfo]
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


class ToolReplayData(BaseModel):
    """Saved application data needed to replay one accepted tool invocation."""

    tool_id: int | None
    search_docs: list[SearchDoc] = Field(default_factory=list)


class ResponseReplayData(BaseModel):
    """Detached source documents and tool identities for response replay."""

    tools: dict[tuple[str, str], ToolReplayData]
    documents: dict[str, SearchDoc]


class ChatBranch(BaseModel):
    chat_session_id: UUID
    message_ids: list[int]


class ResponseLink(BaseModel):
    id: int
    chat_session_id: UUID
    previous_response_id: int | None
    root_id: int
    status: RunStatus


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


class HistoryLink(BaseModel):
    id: int
    parent_message_id: int | None
    chat_session_id: UUID


class SessionAncestor(BaseModel):
    id: UUID
    agent_name: str | None
    parent_id: UUID | None


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
