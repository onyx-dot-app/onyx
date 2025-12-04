from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel
from pydantic import model_validator

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
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet


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


class CreateChatSessionID(BaseModel):
    chat_session_id: UUID


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


class CreateChatMessageRequest(ChunkContext):
    # NOTE: Double check before adding fields to this class, it has historically gotten really
    # bloated and hard to maintain.

    # Identifying where the message is in the chat session history
    chat_session_id: UUID
    # This is the primary-key (unique identifier) for the previous message of the tree
    parent_message_id: int | None

    # New message contents
    message: str
    filters: BaseFilters | None = None
    # Files that we should attach to this message
    file_descriptors: list[FileDescriptor] = []
    # Prompts are embedded in personas, so no separate prompt_id needed
    # If search_doc_ids provided, it should use those docs explicitly
    # TODO: this is for the selecting documents functionality
    search_doc_ids: list[int] | None = None

    # Let's the message be processed with some different LLM than the usual
    llm_override: LLMOverride | None = None

    # Allows the caller to override the temperature for the chat session
    temperature_override: float | None = None

    # List of allowed tool IDs to restrict tool usage. If not provided, all tools available to the persona will be used.
    allowed_tool_ids: list[int] | None = None

    # List of tool IDs we MUST use.
    # TODO: make this a single one since unclear how to force this for multiple at a time.
    forced_tool_ids: list[int] | None = None

    # NOTE: the fields below are less used and typically should not be set in normal flows.
    # used for seeded chats to kick off the generation of an AI answer
    use_existing_user_message: bool = False

    # forces the LLM to return a structured response, see
    # https://platform.openai.com/docs/guides/structured-outputs/introduction
    structured_response_format: dict | None = None

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
    persona_id: int
    messages: list[ThreadMessage]
    filters: BaseFilters | None = None


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
