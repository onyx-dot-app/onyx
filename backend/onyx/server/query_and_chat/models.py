from datetime import datetime
from enum import Enum
from typing import Any
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import QADocsResponse
from onyx.chat.models import ThreadMessage
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.configs.constants import SearchFeedbackType
from onyx.configs.constants import SessionType
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import SearchType
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkContext
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SavedSearchDocWithContent
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import Tag
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import ChatSession
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.llm.override_models import PromptOverride
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet


AUTO_PLACE_AFTER_LATEST_MESSAGE = -1


class MessageOrigin(str, Enum):
    """Origin of a chat message for telemetry tracking."""

    WEBAPP = "webapp"
    CHROME_EXTENSION = "chrome_extension"
    API = "api"
    SLACKBOT = "slackbot"
    UNKNOWN = "unknown"
    UNSET = "unset"


if TYPE_CHECKING:
    pass


class SourceTag(Tag):
    source: DocumentSource


class TagResponse(BaseModel):
    tags: list[SourceTag]


class UpdateChatSessionThreadRequest(BaseModel):
    # If not specified, use Onyx default persona
    chat_session_id: UUID
    new_alternate_model: str


class UpdateChatSessionTemperatureRequest(BaseModel):
    chat_session_id: UUID
    temperature_override: float


class ChatSessionCreationRequest(BaseModel):
    # If not specified, use Onyx default persona
    persona_id: int = 0
    description: str | None = None
    project_id: int | None = None


class ChatFeedbackRequest(BaseModel):
    chat_message_id: int
    is_positive: bool | None = None
    feedback_text: str | None = None
    predefined_feedback: str | None = None

    @model_validator(mode="after")
    def check_is_positive_or_feedback_text(self) -> "ChatFeedbackRequest":
        if self.is_positive is None and self.feedback_text is None:
            raise ValueError("Empty feedback received.")
        return self


class SendMessageRequest(BaseModel):
    message: str

    llm_override: LLMOverride | None = None

    allowed_tool_ids: list[int] | None = None
    forced_tool_id: int | None = None

    file_descriptors: list[FileDescriptor] = []

    internal_search_filters: BaseFilters | None = None

    deep_research: bool = False

    # Origin of the message for telemetry tracking
    origin: MessageOrigin = MessageOrigin.UNSET

    # Placement information for the message in the conversation tree:
    # - -1: auto-place after latest message in chain
    # - null: regeneration from root (first message)
    # - positive int: place after that specific parent message
    # NOTE: for regeneration, this is the only case currently where there is branching on the user message.
    # If the message of parent_message_id is a user message, the message will be ignored and it will use the
    # original user message for regeneration.
    parent_message_id: int | None = AUTO_PLACE_AFTER_LATEST_MESSAGE
    chat_session_id: UUID | None = None
    chat_session_info: ChatSessionCreationRequest | None = None

    # When True (default), returns StreamingResponse with SSE
    # When False, returns ChatFullResponse with complete data
    stream: bool = True

    @model_validator(mode="after")
    def check_chat_session_id_or_info(self) -> "SendMessageRequest":
        # If neither is provided, default to creating a new chat session using the
        # default ChatSessionCreationRequest values.
        if self.chat_session_id is None and self.chat_session_info is None:
            return self.model_copy(
                update={"chat_session_info": ChatSessionCreationRequest()}
            )
        if self.chat_session_id is not None and self.chat_session_info is not None:
            raise ValueError(
                "Only one of chat_session_id or chat_session_info should be provided, not both."
            )
        return self


class CreateChatMessageRequest(ChunkContext):
    """Before creating messages, be sure to create a chat_session and get an id"""

    chat_session_id: UUID
    # This is the primary-key (unique identifier) for the previous message of the tree
    parent_message_id: int | None

    # New message contents
    message: str
    # Files that we should attach to this message
    file_descriptors: list[FileDescriptor] = []
    # Prompts are embedded in personas, so no separate prompt_id needed
    # If search_doc_ids provided, it should use those docs explicitly
    search_doc_ids: list[int] | None
    retrieval_options: RetrievalDetails | None
    # Useable via the APIs but not recommended for most flows
    rerank_settings: RerankingDetails | None = None
    # allows the caller to specify the exact search query they want to use
    # will disable Query Rewording if specified
    query_override: str | None = None

    # enables additional handling to ensure that we regenerate with a given user message ID
    regenerate: bool | None = None

    # allows the caller to override the Persona / Prompt
    # these do not persist in the chat thread details
    llm_override: LLMOverride | None = None
    prompt_override: PromptOverride | None = None

    # Allows the caller to override the temperature for the chat session
    # this does persist in the chat thread details
    temperature_override: float | None = None

    # allow user to specify an alternate assistant
    alternate_assistant_id: int | None = None

    # This takes the priority over the prompt_override
    # This won't be a type that's passed in directly from the API
    persona_override_config: PersonaOverrideConfig | None = None

    # used for seeded chats to kick off the generation of an AI answer
    use_existing_user_message: bool = False

    # used for "OpenAI Assistants API"
    existing_assistant_message_id: int | None = None

    # forces the LLM to return a structured response, see
    # https://platform.openai.com/docs/guides/structured-outputs/introduction
    structured_response_format: dict | None = None

    skip_gen_ai_answer_generation: bool = False

    # List of allowed tool IDs to restrict tool usage. If not provided, all tools available to the persona will be used.
    allowed_tool_ids: list[int] | None = None

    # List of tool IDs we MUST use.
    # TODO: make this a single one since unclear how to force this for multiple at a time.
    forced_tool_ids: list[int] | None = None

    deep_research: bool = False

    # Origin of the message for telemetry tracking
    origin: MessageOrigin = MessageOrigin.UNKNOWN

    @model_validator(mode="after")
    def check_search_doc_ids_or_retrieval_options(self) -> "CreateChatMessageRequest":
        if self.search_doc_ids is None and self.retrieval_options is None:
            raise ValueError(
                "Either search_doc_ids or retrieval_options must be provided, but not both or neither."
            )
        return self

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        data = super().model_dump(*args, **kwargs)
        data["chat_session_id"] = str(data["chat_session_id"])
        return data


class ChatMessageIdentifier(BaseModel):
    message_id: int


class ChatRenameRequest(BaseModel):
    chat_session_id: UUID
    name: str | None = None


class ChatSessionUpdateRequest(BaseModel):
    sharing_status: ChatSessionSharedStatus


class DeleteAllSessionsRequest(BaseModel):
    session_type: SessionType


class RenameChatSessionResponse(BaseModel):
    new_name: str  # This is only really useful if the name is generated


class ChatSessionDetails(BaseModel):
    id: UUID
    name: str | None
    persona_id: int | None = None
    time_created: str
    time_updated: str
    shared_status: ChatSessionSharedStatus
    current_alternate_model: str | None = None
    current_temperature_override: float | None = None

    @classmethod
    def from_model(cls, model: ChatSession) -> "ChatSessionDetails":
        return cls(
            id=model.id,
            name=model.description,
            persona_id=model.persona_id,
            time_created=model.time_created.isoformat(),
            time_updated=model.time_updated.isoformat(),
            shared_status=model.shared_status,
            current_alternate_model=model.current_alternate_model,
            current_temperature_override=model.temperature_override,
        )


class ChatSessionsResponse(BaseModel):
    sessions: list[ChatSessionDetails]


class SearchFeedbackRequest(BaseModel):
    message_id: int
    document_id: str
    document_rank: int
    click: bool
    search_feedback: SearchFeedbackType | None = None

    @model_validator(mode="after")
    def check_click_or_search_feedback(self) -> "SearchFeedbackRequest":
        click, feedback = self.click, self.search_feedback

        if click is False and feedback is None:
            raise ValueError("Empty feedback received.")
        return self


class SubQueryDetail(BaseModel):
    query: str
    query_id: int
    # TODO: store these to enable per-query doc selection
    doc_ids: list[int] | None = None


class ChatMessageDetail(BaseModel):
    chat_session_id: UUID | None = None
    message_id: int
    parent_message: int | None = None
    latest_child_message: int | None = None
    message: str
    reasoning_tokens: str | None = None
    message_type: MessageType
    context_docs: list[SavedSearchDoc] | None = None
    # Dict mapping citation number to document_id
    citations: dict[int, str] | None = None
    time_sent: datetime
    files: list[FileDescriptor]
    error: str | None = None
    current_feedback: str | None = None  # "like" | "dislike" | null

    def model_dump(self, *args: list, **kwargs: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        initial_dict = super().model_dump(mode="json", *args, **kwargs)  # type: ignore
        initial_dict["time_sent"] = self.time_sent.isoformat()
        return initial_dict


class SearchSessionDetailResponse(BaseModel):
    search_session_id: UUID
    description: str | None
    documents: list[SearchDoc]
    messages: list[ChatMessageDetail]


class ChatSessionDetailResponse(BaseModel):
    chat_session_id: UUID
    description: str | None
    persona_id: int | None = None
    persona_name: str | None
    personal_icon_name: str | None
    messages: list[ChatMessageDetail]
    time_created: datetime
    shared_status: ChatSessionSharedStatus
    current_alternate_model: str | None
    current_temperature_override: float | None
    deleted: bool = False
    packets: list[list[Packet]]


# This one is not used anymore
class QueryValidationResponse(BaseModel):
    reasoning: str
    answerable: bool


class AdminSearchRequest(BaseModel):
    query: str
    filters: BaseFilters


class AdminSearchResponse(BaseModel):
    documents: list[SearchDoc]


class ChatSessionSummary(BaseModel):
    id: UUID
    name: str | None = None
    persona_id: int | None = None
    time_created: datetime
    shared_status: ChatSessionSharedStatus
    current_alternate_model: str | None = None
    current_temperature_override: float | None = None


class ChatSessionGroup(BaseModel):
    title: str
    chats: list[ChatSessionSummary]


class ChatSearchResponse(BaseModel):
    groups: list[ChatSessionGroup]
    has_more: bool
    next_page: int | None = None


class ChatSearchRequest(BaseModel):
    query: str | None = None
    page: int = 1
    page_size: int = 10


class CreateChatResponse(BaseModel):
    chat_session_id: str


class DocumentSearchRequest(ChunkContext):
    message: str
    search_type: SearchType
    retrieval_options: RetrievalDetails
    recency_bias_multiplier: float = 1.0
    evaluation_type: LLMEvaluationType
    # None to use system defaults for reranking
    rerank_settings: RerankingDetails | None = None


class OneShotQARequest(ChunkContext):
    # Supports simplier APIs that don't deal with chat histories or message edits
    # Easier APIs to work with for developers
    persona_override_config: PersonaOverrideConfig | None = None
    persona_id: int | None = None

    messages: list[ThreadMessage]
    retrieval_options: RetrievalDetails = Field(default_factory=RetrievalDetails)
    rerank_settings: RerankingDetails | None = None

    # allows the caller to specify the exact search query they want to use
    # can be used if the message sent to the LLM / query should not be the same
    # will also disable Thread-based Rewording if specified
    query_override: str | None = None

    # If True, skips generating an AI response to the search query
    skip_gen_ai_answer_generation: bool = False

    @model_validator(mode="after")
    def check_persona_fields(self) -> "OneShotQARequest":
        if self.persona_override_config is None and self.persona_id is None:
            raise ValueError("Exactly one of persona_config or persona_id must be set")
        elif self.persona_override_config is not None and (self.persona_id is not None):
            raise ValueError(
                "If persona_override_config is set, persona_id cannot be set"
            )
        return self


class OneShotQAResponse(BaseModel):
    # This is built piece by piece, any of these can be None as the flow could break
    answer: str | None = None
    rephrase: str | None = None
    citations: list[CitationInfo] | None = None
    docs: QADocsResponse | None = None
    error_msg: str | None = None
    chat_message_id: int | None = None


class DocumentSearchPagination(BaseModel):
    offset: int
    limit: int
    returned_count: int
    has_more: bool
    next_offset: int | None = None


class DocumentSearchResponse(BaseModel):
    top_documents: list[SavedSearchDocWithContent]
    llm_indices: list[int]
    pagination: DocumentSearchPagination
