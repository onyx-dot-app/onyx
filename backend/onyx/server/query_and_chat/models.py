from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import model_validator

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.configs.constants import SessionType
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import Tag
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import ChatSession
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.streaming_models import Packet


AUTO_PLACE_AFTER_LATEST_MESSAGE = -1


class MessageOrigin(str, Enum):
    """Origin of a chat message for telemetry tracking."""

    WEBAPP = "webapp"
    CHROME_EXTENSION = "chrome_extension"
    API = "api"
    SLACKBOT = "slackbot"
    WIDGET = "widget"
    DISCORDBOT = "discordbot"
    UNKNOWN = "unknown"
    UNSET = "unset"


class MessageResponseIDInfo(BaseModel):
    user_message_id: int | None
    reserved_assistant_message_id: int


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


# NOTE: This model is used for the core flow of the Onyx application, any changes to it should be reviewed and approved by an
# experienced team member. It is very important to 1. avoid bloat and 2. that this remains backwards compatible across versions.
class SendMessageRequest(BaseModel):
    message: str

    llm_override: LLMOverride | None = None
    # Test-only override for deterministic LiteLLM mock responses.
    mock_llm_response: str | None = None

    allowed_tool_ids: list[int] | None = None
    forced_tool_id: int | None = None

    file_descriptors: list[FileDescriptor] = []

    internal_search_filters: BaseFilters | None = None

    deep_research: bool = False

    # Headers to forward to MCP tool calls (e.g., user JWT token, user ID)
    # Example: {"Authorization": "Bearer <user_jwt>", "X-User-ID": "user123"}
    mcp_headers: dict[str, str] | None = None

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

    # When False, disables citation generation:
    # - Citation markers like [1], [2] are removed from response text
    # - No CitationInfo packets are emitted during streaming
    include_citations: bool = True

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
    processing_duration_seconds: float | None = None

    def model_dump(self, *args: list, **kwargs: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        initial_dict = super().model_dump(mode="json", *args, **kwargs)  # type: ignore
        initial_dict["time_sent"] = self.time_sent.isoformat()
        return initial_dict


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
