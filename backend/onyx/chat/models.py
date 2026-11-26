from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
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
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunFailure,
    RunFailureKind,
    RunStatus,
    StepRecord,
    messages_from_steps,
)
from onyx.agents.tools import InputDecision
from onyx.cache.interface import CacheBackend
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.mention_models import Mentions, PickedSkillMessage, RecordedMention
from onyx.configs.constants import MessageType
from onyx.context.models import UserMemoryContext
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.db.enums import (
    ApprovalDecidedVia,
    ApprovalDecision,
    IncognitoRecordMode,
    QuestionAnsweredVia,
    QuestionOutcome,
)
from onyx.db.models import SAVED_TOOL_RESULT_TYPES, SavedToolResultDetails, UserFile
from onyx.deep_research.models import ResearchConfiguration
from onyx.file_store.models import (
    ChatLoadedFile,
    ExtractedContextFiles,
    FileDescriptor,
    FileToolMetadata,
)
from onyx.integrations.models import ApprovalMode
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import (
    GenerationRequestParams,
    Message,
    ReasoningEffort,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.override_models import LLMOverride
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
    ToolApprovalRequest,
    ToolQuestionRequest,
)
from onyx.tools.file_snapshot import SavedChatFile, SavedContextFiles, SavedLoadedFile
from onyx.tools.models import (
    ChatFile,
    GeneratedImage,
    PersonaToolConfiguration,
    SearchToolUsage,
    ToolCallInfo,
    ToolOptions,
    ToolPreference,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeExecutionResult,
    SavedCodeCell,
)
from onyx.tools.tool_implementations.custom.base_tool_types import ToolResultType
from onyx.tools.tool_implementations.question.models import (
    ToolQuestion,
    ToolQuestionAnswer,
)
from onyx.tools.tool_implementations.sandbox.models import PublishedFile, VmChatFile
from onyx.tools.tool_implementations.search.models import SearchContext
from onyx.tools.tool_implementations.subagents.models import ChatConfiguration

MAX_DISCOVERED_AGENTS = 128
_MESSAGE_ADAPTER = TypeAdapter(Message)
_INCOGNITO_IMAGES = TypeAdapter(list[SavedLoadedFile])
_INCOGNITO_DETAILS = TypeAdapter(SavedToolResultDetails)


class PendingChatMessage(BaseModel):
    id: str
    message: str
    delivery: MessageDelivery
    target_response_id: int | None
    deep_research: bool = False
    llm_override: LLMOverride | None = None
    mentions: Mentions


class QueuedChatTurn(BaseModel):
    """The next root turn: a submitted message, or unread agent results when None."""

    parent_response_id: int | None
    message: PendingChatMessage | None


class PromptMetadata(CompactionMetadata):
    token_count: int | None = None
    image_files: list[ChatLoadedFile] | None = None
    image_token_count: int = 0
    should_cache: bool = False
    file_id: str | None = None
    is_reminder: bool = False


class ChatInputMetadata(InputMessageMetadata):
    """A user message accepted between steps, with the records of what it
    picked. The `<skill>` message of each pick follows it in history."""

    mentions: list[RecordedMention] = Field(default_factory=list)


def recorded_mentions(message: Message) -> list[RecordedMention]:
    """What a message accepted between steps picked."""
    return (
        message.metadata.mentions
        if isinstance(message.metadata, ChatInputMetadata)
        else []
    )


def skill_message_id(message_id: str, version_id: UUID) -> str:
    """The id of the `<skill>` message that a message's pick of a skill
    version gives the model."""
    return f"{message_id}:skill:{version_id}"


def picked_skill_messages(
    message_id: str,
    mentions: Sequence[RecordedMention],
    skill_messages: Sequence[PickedSkillMessage],
) -> list[UserMessage]:
    """The `<skill>` messages that follow a message in history, in the order
    it picked the skills."""
    by_version = {message.version_id: message for message in skill_messages}
    if by_version.keys() != {mention.version_id for mention in mentions}:
        raise ValueError("Each picked skill needs its saved skill message")
    return [
        UserMessage(
            id=skill_message_id(message_id, mention.version_id),
            content=by_version[mention.version_id].content,
            metadata=PromptMetadata(
                token_count=by_version[mention.version_id].token_count,
                is_input_context=True,
            ),
        )
        for mention in mentions
    ]


def accepted_input_messages(
    *,
    message_id: str,
    content: str,
    source: InputSource,
    source_run_id: str | None,
    mentions: list[RecordedMention],
    skill_messages: list[PickedSkillMessage],
) -> list[UserMessage]:
    """A user message accepted between steps and the `<skill>` messages of
    its picks, as the run accepted it and as its saved record restores it."""
    return [
        UserMessage(
            id=message_id,
            content=content,
            # Only a message that picked skills has the chat metadata.
            metadata=ChatInputMetadata(
                source=source, source_run_id=source_run_id, mentions=mentions
            )
            if mentions
            else InputMessageMetadata(source=source, source_run_id=source_run_id),
        ),
        *picked_skill_messages(message_id, mentions, skill_messages),
    ]


class ContextUserFiles(BaseModel):
    """The user files of a chat's context: its project's files and its
    custom agent's files. A file in both is the agent's."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project: list[UserFile]
    agent: list[UserFile]


class PlacedChatFiles(BaseModel):
    """The chat files in the chat's sandbox (files.place_chat_files)."""

    files: list[VmChatFile]
    # By file store ID: the paths of the chat's uploads.
    upload_paths: dict[str, str]


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
    RESEARCH = "research"
    PLAN = "plan"
    REPORT = "report"
    SILENT = "silent"


class ToolApprovalDenial(BaseModel):
    """Metadata of the result that a denied approval request gives the model:
    why the call did not run. Saved responses drop it."""

    # disabled: the action policy blocked the call when the user approved it,
    # or the tool's server was deleted while the call waited.
    outcome: Literal["rejected", "disabled"]


class MessageRendering(BaseModel):
    """Chat display settings retained with one generated message for history replay."""

    mode: PresentationMode = PresentationMode.ANSWER
    is_clarification: bool = False
    citation_mode: CitationMode | None = None
    # The citation numbers and documents that this step adds to its run's;
    # see RunDocuments. A step can also hold the run's whole set so far,
    # which gives the same result.
    citation_documents: dict[int, str] = Field(default_factory=dict)
    document_ids: list[str] = Field(default_factory=list)
    pre_answer_seconds: float | None = None


class RunDocuments(BaseModel):
    """The documents and citations that a run's messages show after some of
    its steps. Each step's MessageRendering adds to them: `add_step` folds a
    run's steps in order."""

    model_config = ConfigDict(frozen=True)
    # By document ID, in the order first shown, each in its latest copy.
    shown: dict[str, SearchDoc] = Field(default_factory=dict)
    # Citation numbers, each with the document of the step that added it.
    cited: dict[int, SearchDoc] = Field(default_factory=dict)

    def add_step(
        self, setting: MessageRendering, documents: Mapping[str, SearchDoc]
    ) -> "RunDocuments":
        """The documents after one more step; `documents` resolves the
        step's document IDs."""
        # The values are already validated documents.
        return RunDocuments.model_construct(
            shown={
                **self.shown,
                **{
                    key: documents[key]
                    for key in setting.document_ids
                    if key in documents
                },
            },
            cited={
                **self.cited,
                **{
                    number: documents[key]
                    for number, key in setting.citation_documents.items()
                    if key in documents
                },
            },
        )

    @property
    def citations(self) -> dict[int, SearchDoc]:
        """Citation numbers and their documents, in the latest shown copy."""
        return {
            number: self.shown.get(document.document_id, document)
            for number, document in self.cited.items()
        }


def read_message_rendering(value: dict[str, JsonValue]) -> MessageRendering:
    """Hide text with an unknown display mode when replaying stored chat steps."""
    mode = value.get("mode")
    if isinstance(mode, str) and mode not in PresentationMode:
        value = {**value, "mode": PresentationMode.SILENT}
    return MessageRendering.model_validate(value)


class ResponseRecord(BaseModel):
    """Accepted steps and execution outcomes, without live application objects."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    agent_id: str | None = None
    agent_path: str = "/root"
    agent_description: str = ""
    restoration_config: ResearchConfiguration | ChatConfiguration | None = None
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
    ancestor_agent_ids: list[str]
    status: RunStatus


class ResponseAncestry(BaseModel):
    message_id: int
    session_id: UUID
    status: RunStatus | None
    spawned_by_message_id: int | None
    parent_session_id: UUID | None
    parent_response_id: int | None
    # For a child run, the agent's previous run; it can belong to a later turn.
    previous_response_id: int | None = None


class AgentResultState(BaseModel):
    """An unread child result on a branch; it is readable once its response finishes."""

    recipient_id: UUID
    # The agent whose run delivers the result.
    agent_id: UUID
    response_id: int
    # The root response that the run belongs to.
    root_response_id: int
    status: RunStatus
    failure: RunFailure | None = None
    # SUSPENDED with a checkpoint: the run waits for people, without an owner.
    parked: bool = False

    @property
    def wakes_recipient(self) -> bool:
        """A finished result starts its idle recipient's next run.

        A run the user stopped does not: its recipient reads the stop as a
        notice at its next step instead.
        """
        return self.status.is_terminal and (
            self.failure is None or self.failure.kind != RunFailureKind.STOPPED_BY_USER
        )

    @property
    def is_active(self) -> bool:
        """An active background agent: an unfinished run that delivers this result.

        Only the spawn tool's runs have result rows, so foreground workers never count.
        A run that waits for the user without an owner (parked) counts.
        """
        return not self.status.is_terminal

    @property
    def is_running(self) -> bool:
        """An active run that is not parked: it has, or had, an owner."""
        return self.is_active and not self.parked


class AgentWait(BaseModel):
    """A root's wait call on a branch, as `AgentWaitDetails` records it."""

    response_id: int
    agent_ids: frozenset[UUID] | None
    # A message to one of its agents still waits to start that agent's run.
    queued: bool

    def holds(self, agent_id: UUID, root_response_id: int) -> bool:
        return root_response_id <= self.response_id and (
            self.agent_ids is None or agent_id in self.agent_ids
        )


class AgentInboxWork(BaseModel):
    """An idle child's next run: a queued message, or its unread results when None."""

    agent_id: str
    message: UserMessage | None
    # None: the step limit of the chat agent that hosts the run.
    max_steps: int | None
    total_timeout_s: float | None
    parent_run_id: str
    parent_message_id: str
    parent_tool_call_id: str


class ParkedRun(BaseModel):
    """A parked run whose waits have all ended, on any branch of the chat."""

    # The agent's conversation; the chat session itself for a root response.
    agent_id: str
    response_id: int
    # The root response whose branch the run belongs to.
    root_response_id: int
    # The model, temperature, and the request's tool options that the run's
    # checkpoint saved, which it continues with.
    model_configuration_id: int | None = None
    temperature: float | None = None
    tool_options: ToolOptions | None = None

    @property
    def is_root(self) -> bool:
        """Whether the run is a root response, which continues in a turn."""
        return self.response_id == self.root_response_id


class ChatBranch(BaseModel):
    chat_session_id: UUID
    message_ids: list[int]


class ChatInbox(BaseModel):
    """Running children and startable work on a conversation's selected branch."""

    branch: ChatBranch
    selected_response_id: int | None
    # The running selected response and running background agents. Each can
    # have lost its owner; parked runs have none and are not listed.
    running_response_ids: list[int] = Field(default_factory=list)
    results: list[AgentResultState] = Field(default_factory=list)
    next_turn: QueuedChatTurn | None = None
    child_work: list[AgentInboxWork] = Field(default_factory=list)
    # Unfinished latest runs of agents whose messages wait for them.
    waiting_response_ids: list[int] = Field(default_factory=list)
    # Parked runs whose waits have all ended, on any branch: root responses
    # continue in a turn before any queued turn, and the stores of their
    # branches resume agent runs.
    resumable_runs: list[ParkedRun] = Field(default_factory=list)

    @property
    def unfinished_response_ids(self) -> list[int]:
        """Running and waited-for responses; any of them can have lost its owner."""
        return [*self.running_response_ids, *self.waiting_response_ids]


class ResponseLink(BaseModel):
    id: int
    chat_session_id: UUID
    previous_response_id: int | None
    root_id: int
    status: RunStatus


class IncognitoAgentResponse(BaseModel):
    run_id: str | None = None
    checkpoint: CompactionCheckpoint | None = None
    message_ids: list[str] = Field(default_factory=list)
    replay_digest: str


def _read_incognito_message(value: dict[str, JsonValue] | Message) -> Message:
    if not isinstance(value, dict):
        return value
    data = dict(value)
    raw_metadata = data.pop("metadata", {})
    if isinstance(raw_metadata, dict) and raw_metadata.get("image_files"):
        raw_metadata = {
            **raw_metadata,
            "image_files": [
                image.restore()
                for image in _INCOGNITO_IMAGES.validate_python(
                    raw_metadata["image_files"]
                )
            ],
        }
    metadata = (
        ChatMessageMetadata.model_validate(raw_metadata)
        if isinstance(raw_metadata, dict) and "sources" in raw_metadata
        else PromptMetadata.model_validate(raw_metadata)
    )
    details = data.pop("details", None)
    message = _MESSAGE_ADAPTER.validate_python(data)
    message.metadata = metadata
    if details is not None and isinstance(message, ToolResultMessage):
        message.details = _INCOGNITO_DETAILS.validate_python(details)
    return message


def serialize_incognito_message(message: Message) -> dict[str, JsonValue]:
    """Retain replay text, citation sources and saved tool result details, excluding
    execution files and state."""
    metadata = (
        message.metadata
        if isinstance(message.metadata, PromptMetadata)
        else PromptMetadata()
    )
    data: dict[str, JsonValue] = message.model_dump(
        mode="json", exclude={"details", "metadata"}
    )
    data["metadata"] = (
        message.metadata.model_dump(mode="json", include={"sources"})
        if isinstance(message.metadata, ChatMessageMetadata)
        else {
            **metadata.model_dump(exclude={"image_files"}),
            "image_files": [
                SavedLoadedFile.capture(image).model_dump(mode="json")
                for image in metadata.image_files
            ]
            if metadata.image_files is not None
            else None,
        }
    )
    if isinstance(message, ToolResultMessage) and isinstance(
        message.details, SAVED_TOOL_RESULT_TYPES
    ):
        # Dumped as the saved type: staged files stay in execution state.
        data["details"] = _INCOGNITO_DETAILS.dump_python(message.details, mode="json")
    return data


IncognitoMessage = Annotated[
    Message,
    BeforeValidator(_read_incognito_message),
    PlainSerializer(serialize_incognito_message),
]


class IncognitoState(BaseModel):
    format_version: Literal[3] = 3
    messages: list[IncognitoMessage] = Field(default_factory=list)
    file_metadata: dict[str, FileToolMetadata] = Field(default_factory=dict)
    previous_run_id: str | None = None
    responses: dict[str, IncognitoAgentResponse] = Field(default_factory=dict)


class SavedAgentContext(BaseModel):
    """Saved history, settings, and sources used to rebuild an agent."""

    agent_id: str
    configuration: ResearchConfiguration | ChatConfiguration | None
    messages: list[Message]
    checkpoint: CompactionCheckpoint | None = None
    previous_run_id: str | None = None
    sources: dict[int, SearchDoc] = Field(default_factory=dict)


class ChatMessageMetadata(BaseModel):
    """Source references and display settings attached to a generated chat message."""

    # The citation numbers and gathered documents that are new since the
    # run's earlier steps, or new copies; together the run's steps hold them
    # all (see RunDocuments).
    sources: dict[int, SearchDoc] = Field(default_factory=dict)
    documents: list[SearchDoc] = Field(default_factory=list)
    include_citations: bool = True
    elapsed_seconds: float = 0


class ReceivedAgentInputs(BaseModel):
    """Received messages and the citation numbers their sources add."""

    messages: list[UserMessage]
    new_citations: dict[int, SearchDoc]


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
    # The `<skill>` messages of the skills a question picked.
    skill_messages: list[UserMessage]
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


class ChatSessionNameInfo(BaseModel):
    """The name the server gave a new chat, sent once it is saved."""

    chat_session_id: UUID
    chat_session_name: str


AnswerStreamPart = (
    Packet
    | MessageResponseIDInfo
    | MultiModelMessageResponseIDInfo
    | StreamingError
    | CreateChatSessionID
    | ChatSessionNameInfo
)

AnswerStream = Iterator[AnswerStreamPart]


class ToolCallResponse(BaseModel):
    """Tool call with full details for non-streaming response."""

    tool_name: str
    tool_arguments: dict[str, Any]
    tool_result: str
    search_docs: list[SearchDoc] | None = None
    generated_images: list[GeneratedImage] | None = None
    # Files that the call published to the user; each downloads from
    # /chat/file/{file_id}.
    published_files: list[PublishedFile] | None = None
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
    # Set when the response stopped because tool calls wait for the user
    # (stop reason `awaiting_user`): for approval decisions, or for answers to
    # the agent's questions. After them the response continues in the chat
    # session. Empty for a finished response.
    pending_tool_approvals: list[ToolApprovalRequest] = []
    pending_tool_questions: list[ToolQuestionRequest] = []


class ChatHistoryResult(BaseModel):
    """Result of converting chat history to simple format.

    Bundles the simple messages with metadata for every text file that was
    injected into the history. After context-window truncation drops older
    messages, callers compare surviving ``file_id`` tags against this map
    to discover "forgotten" files whose metadata should be provided to the
    FileReaderTool.
    """

    messages: list[Message]
    input_start: int
    all_injected_file_metadata: dict[str, FileToolMetadata]


class SearchParams(BaseModel):
    """Resolved search filter IDs and search-tool usage for a chat turn."""

    project_id_filter: int | None
    persona_id_filter: int | None
    search_usage: SearchToolUsage


class ResultSources(BaseModel):
    """Documents carried by one tool result and the citation numbers it gave them."""

    model_config = ConfigDict(frozen=True)

    # The documents the result carries: every search result, or only the cited
    # documents of a research result.
    documents: list[SearchDoc]
    # The documents to show for the call; a search can select a subset. None when
    # the call shows no documents of its own.
    displayed: list[SearchDoc] | None
    citations: dict[int, SearchDoc]


class StagedChatFiles(BaseModel):
    """Files of a tool result's documents, staged before the result is committed."""

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


class ChatSearchResult(StagedChatFiles, SearchDocsResponse):
    """Search documents with their files staged."""


class ChatCodeModeResult(StagedChatFiles, CodeModeExecutionResult):
    """A code mode result with the files of its nested searches staged."""


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
    # The reminder to open pages after a web search, naming the tools as the
    # model calls them; None without the URL reading tool.
    open_url_reminder: str | None
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
    preferred_tool: ToolPreference | None = None
    code_mode: bool
    base_prompt: str
    custom_prompt: str | None
    request_context: str | None = None
    reminders_enabled: bool

    elapsed_seconds: float
    citation_sources: dict[int, SearchDoc]
    citation_mapping: dict[int, str]
    gathered_documents: list[SearchDoc]
    chat_files: list[SavedChatFile]
    has_called_search_tool: bool
    search_context: SearchContext
    # Cells whose observations wait for the user's input.
    code_cells: list[SavedCodeCell] = Field(default_factory=list)


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
    # The turn offers the sandbox tools (sandbox_tools.py:SANDBOX_TOOLS).
    sandbox_tools: bool
    # The chat's files in its sandbox (chat/files.py:place_chat_files); none
    # without the sandbox tools.
    vm_chat_files: list[VmChatFile]
    # The turn's first sandbox call copies them (SandboxTurn).
    copy_vm_chat_files: bool
    # The root agent gets the question tool (question_tool.py).
    question_tool: bool = False
    research_tool_id: int | None
    checkpoint: CompactionCheckpoint | None
    # Child-result delivery has no new user message.
    user_message_id: int | None
    # The mentions recorded on the question, for its ID packet.
    mentions: list[RecordedMention]
    user_identity: LLMUserIdentity
    responses: list[ReservedChatResponse]
    messages: list[Message]
    input_messages: list[Message]
    previous_run_id: str | None = None
    additional_context: str | None = None
    extracted_context_files: ExtractedContextFiles
    # Fences processing status and identifies the buffered stream.
    stream_id: int
    reasoning_effort: ReasoningEffort
    search_params: SearchParams
    all_injected_file_metadata: dict[str, FileToolMetadata]
    available_files: AvailableFiles
    preferred_tool: ToolPreference | None
    # The preferred tool comes from the chat's saved options, which can
    # outlive the tool or its plugin; the turn then runs without it.
    preferred_tool_saved: bool = False
    # Name the chat from its first question while the answer streams
    # (`chat/session_naming.py`).
    auto_name: bool = False
    chat_files_for_tools: list[ChatFile]
    custom_agent_prompt: str | None
    user_memory_context: UserMemoryContext
    # The user's memory settings as the turn started.
    use_memories: bool
    enable_memory_tool: bool
    # The turn offers the skill tools when the user had custom skills as it
    # started; the tools and each agent's catalog read the current skills.
    has_chat_skills: bool
    # For deep research: was the last assistant message a clarification request?
    skip_clarification: bool
    cache: CacheBackend
    admission: ChatTurnAdmission
    # Execution params forwarded to per-model tool construction
    slack_context: SlackContext | None
    litellm_additional_headers: dict[str, str] | None = None
    custom_tool_additional_headers: dict[str, str] | None
    mcp_headers: dict[str, str] | None
    # Only server-side callers set it; the public request has no such field.
    approval_mode: ApprovalMode = ApprovalMode.INTERACTIVE
    # The suspended response that this turn continues after its approvals,
    # under a new stream ID; None for a turn that starts a response.
    resumed_response_id: int | None = None


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
    standing: bool = False


class CheckpointBinding(BaseModel):
    """Application identity; validating this record does not authorize access."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    response_id: str


class MessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    input_messages: list[Message]
    input_payloads: list[MessagePayload]
    # The saved model configuration that the response runs, its sampling
    # temperature, and the tool options of its request; a parked response
    # continues with them.
    model_configuration_id: int | None = None
    temperature: float | None = None
    tool_options: ToolOptions | None = None


class SavedCheckpoint(BaseModel):
    ownership_version: int
    data: ResponseCheckpoint


class ToolReplayData(BaseModel):
    """Saved application data needed to replay one accepted tool invocation."""

    tool_id: int | None
    search_docs: list[SearchDoc] = Field(default_factory=list)


class SavedToolApproval(BaseModel):
    """A saved approval request of a chat tool call (`approval_request`)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # The response, by message ID, and the call of its step that the request
    # belongs to.
    chat_message_id: int
    tool_call_id: str
    tool_name: str
    display_name: str
    arguments: dict[str, JsonValue]
    created_at: datetime
    decision: ApprovalDecision | None
    decided_via: ApprovalDecidedVia | None
    decided_at: datetime | None


class SavedToolQuestion(BaseModel):
    """A saved question request of a chat response's call (`question_request`)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chat_message_id: int
    tool_call_id: str
    questions: list[ToolQuestion]
    answers: list[ToolQuestionAnswer] | None
    message: str | None
    outcome: QuestionOutcome | None
    answered_via: QuestionAnsweredVia | None
    created_at: datetime
    resolved_at: datetime | None


class AgentToolApproval(BaseModel):
    """A background agent's approval request, shown at the root response's
    call that started the agent."""

    approval: SavedToolApproval
    agent_name: str


class ChatApprovals(BaseModel):
    """The approval requests and questions of a page of chat responses, read
    once for the replays of those responses."""

    # The requests of the responses and of the runs that they started, by
    # response (the request's chat message), in the order they were made.
    requests: dict[int, list[SavedToolApproval]] = Field(default_factory=dict)
    # The agent names of the responses of background agents.
    agent_names: dict[int, str] = Field(default_factory=dict)
    # The runs that each response's calls started, directly or through the
    # runs they started, with the ID of the response's call.
    started_runs: dict[int, list[tuple[int, str]]] = Field(default_factory=dict)
    # The questions of the responses, by response, in the order they were
    # asked. Only root responses ask.
    questions: dict[int, list[SavedToolQuestion]] = Field(default_factory=dict)


class ResponseReplayData(BaseModel):
    """Detached source documents, tool identities, approval requests and
    questions for response replay."""

    tools: dict[tuple[str, str], ToolReplayData]
    documents: dict[str, SearchDoc]
    # The approval requests of an ended or suspended response, in the order
    # they were made, by response run ID and tool call ID.
    approvals: dict[tuple[str, str], list[SavedToolApproval]]
    # The requests of the background agents that the response started, by its
    # run ID and the call that started each agent.
    agent_approvals: dict[tuple[str, str], list[AgentToolApproval]] = Field(
        default_factory=dict
    )
    # The questions of an ended or suspended response, by its run ID and the
    # call that asked.
    questions: dict[tuple[str, str], SavedToolQuestion] = Field(default_factory=dict)
