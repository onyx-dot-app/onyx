from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel
from pydantic import model_validator

from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import RetrievalDocs
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.configs.constants import SearchFeedbackType
from onyx.configs.constants import SessionType
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkContext
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import Tag
from onyx.db.enums import ChatSessionSharedStatus
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.llm.override_models import PromptOverride
from onyx.tools.models import ToolCallFinalResult


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


"""
Currently the different branches are generated by changing the search query

                 [Empty Root Message]  This allows the first message to be branched as well
              /           |           \
[First Message] [First Message Edit 1] [First Message Edit 2]
       |                  |
[Second Message]  [Second Message of Edit 1 Branch]
"""


class CreateChatMessageRequest(ChunkContext):
    """Before creating messages, be sure to create a chat_session and get an id"""

    chat_session_id: UUID
    # This is the primary-key (unique identifier) for the previous message of the tree
    parent_message_id: int | None
    # New message contents
    message: str
    # Files that we should attach to this message
    file_descriptors: list[FileDescriptor]

    # If no prompt provided, uses the largest prompt of the chat session
    # but really this should be explicitly specified, only in the simplified APIs is this inferred
    # Use prompt_id 0 to use the system default prompt which is Answer-Question
    prompt_id: int | None
    # If search_doc_ids provided, then retrieval options are unused
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

    # allow user to specify an alternate assistnat
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

    # If true, ignores most of the search options and uses pro search instead.
    # This is now determined by the assistant's pro_search_enabled setting
    use_agentic_search: bool | None = None

    skip_gen_ai_answer_generation: bool = False

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
    folder_id: int | None = None
    current_alternate_model: str | None = None
    current_temperature_override: float | None = None


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


class SubQuestionDetail(BaseModel):
    level: int
    level_question_num: int
    question: str
    answer: str
    sub_queries: list[SubQueryDetail] | None = None
    context_docs: RetrievalDocs | None = None


class ChatMessageDetail(BaseModel):
    message_id: int
    parent_message: int | None = None
    latest_child_message: int | None = None
    message: str
    rephrased_query: str | None = None
    context_docs: RetrievalDocs | None = None
    message_type: MessageType
    time_sent: datetime
    overridden_model: str | None
    alternate_assistant_id: int | None = None
    chat_session_id: UUID | None = None
    # Dict mapping citation number to db_doc_id
    citations: dict[int, int] | None = None
    sub_questions: list[SubQuestionDetail] | None = None
    files: list[FileDescriptor]
    tool_call: ToolCallFinalResult | None
    refined_answer_improvement: bool | None = None
    is_agentic: bool | None = None
    error: str | None = None

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
    persona_icon_color: str | None
    persona_icon_shape: int | None
    messages: list[ChatMessageDetail]
    time_created: datetime
    shared_status: ChatSessionSharedStatus
    current_alternate_model: str | None
    current_temperature_override: float | None


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
    folder_id: int | None = None
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
