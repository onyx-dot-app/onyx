from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from ee.onyx.server.manage.models import StandardAnswer
from onyx.chat.models import CitationInfo
from onyx.chat.models import OnyxContexts
from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import QADocsResponse
from onyx.chat.models import ThreadMessage
from onyx.configs.constants import DocumentSource
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import SearchType
from onyx.context.search.models import ChunkContext
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SavedSearchDoc


class StandardAnswerRequest(BaseModel):
    message: str
    slack_bot_categories: list[str]


class StandardAnswerResponse(BaseModel):
    standard_answers: list[StandardAnswer] = Field(default_factory=list)


class DocumentSearchRequest(ChunkContext):
    message: str
    search_type: SearchType
    retrieval_options: RetrievalDetails
    recency_bias_multiplier: float = 1.0
    evaluation_type: LLMEvaluationType
    # None to use system defaults for reranking
    rerank_settings: RerankingDetails | None = None


class BasicCreateChatMessageRequest(ChunkContext):
    """Before creating messages, be sure to create a chat_session and get an id
    Note, for simplicity this option only allows for a single linear chain of messages
    """

    chat_session_id: UUID
    # New message contents
    message: str
    # Defaults to using retrieval with no additional filters
    retrieval_options: RetrievalDetails | None = None
    # Allows the caller to specify the exact search query they want to use
    # will disable Query Rewording if specified
    query_override: str | None = None
    # If search_doc_ids provided, then retrieval options are unused
    search_doc_ids: list[int] | None = None
    # only works if using an OpenAI model. See the following for more details:
    # https://platform.openai.com/docs/guides/structured-outputs/introduction
    structured_response_format: dict | None = None


class BasicCreateChatMessageWithHistoryRequest(ChunkContext):
    # Last element is the new query. All previous elements are historical context
    messages: list[ThreadMessage]
    prompt_id: int | None
    persona_id: int
    retrieval_options: RetrievalDetails | None = None
    query_override: str | None = None
    skip_rerank: bool | None = None
    # If search_doc_ids provided, then retrieval options are unused
    search_doc_ids: list[int] | None = None
    # only works if using an OpenAI model. See the following for more details:
    # https://platform.openai.com/docs/guides/structured-outputs/introduction
    structured_response_format: dict | None = None


class SimpleDoc(BaseModel):
    id: str
    semantic_identifier: str
    link: str | None
    blurb: str
    match_highlights: list[str]
    source_type: DocumentSource
    metadata: dict | None


class ChatBasicResponse(BaseModel):
    # This is built piece by piece, any of these can be None as the flow could break
    answer: str | None = None
    answer_citationless: str | None = None

    top_documents: list[SavedSearchDoc] | None = None

    error_msg: str | None = None
    message_id: int | None = None
    llm_selected_doc_indices: list[int] | None = None
    final_context_doc_indices: list[int] | None = None
    # this is a map of the citation number to the document id
    cited_documents: dict[int, str] | None = None

    # FOR BACKWARDS COMPATIBILITY
    # TODO: deprecate both of these
    simple_search_docs: list[SimpleDoc] | None = None
    llm_chunks_indices: list[int] | None = None


class OneShotQARequest(ChunkContext):
    # Supports simplier APIs that don't deal with chat histories or message edits
    # Easier APIs to work with for developers
    persona_override_config: PersonaOverrideConfig | None = None
    persona_id: int | None = None

    messages: list[ThreadMessage]
    prompt_id: int | None = None
    retrieval_options: RetrievalDetails = Field(default_factory=RetrievalDetails)
    rerank_settings: RerankingDetails | None = None
    return_contexts: bool = False

    # allows the caller to specify the exact search query they want to use
    # can be used if the message sent to the LLM / query should not be the same
    # will also disable Thread-based Rewording if specified
    query_override: str | None = None

    # If True, skips generative an AI response to the search query
    skip_gen_ai_answer_generation: bool = False

    @model_validator(mode="after")
    def check_persona_fields(self) -> "OneShotQARequest":
        if self.persona_override_config is None and self.persona_id is None:
            raise ValueError("Exactly one of persona_config or persona_id must be set")
        elif self.persona_override_config is not None and (
            self.persona_id is not None or self.prompt_id is not None
        ):
            raise ValueError(
                "If persona_override_config is set, persona_id and prompt_id cannot be set"
            )
        return self


class OneShotQAResponse(BaseModel):
    # This is built piece by piece, any of these can be None as the flow could break
    answer: str | None = None
    rephrase: str | None = None
    citations: list[CitationInfo] | None = None
    docs: QADocsResponse | None = None
    llm_selected_doc_indices: list[int] | None = None
    error_msg: str | None = None
    chat_message_id: int | None = None
    contexts: OnyxContexts | None = None
