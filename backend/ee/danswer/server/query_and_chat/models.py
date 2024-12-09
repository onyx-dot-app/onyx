from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from danswer.configs.constants import DocumentSource
from danswer.context.search.enums import LLMEvaluationType
from danswer.context.search.enums import SearchType
from danswer.context.search.models import ChunkContext
from danswer.context.search.models import RerankingDetails
from danswer.context.search.models import RetrievalDetails
from danswer.context.search.models import SavedSearchDoc
from danswer.one_shot_answer.models import ThreadMessage
from ee.danswer.server.manage.models import StandardAnswer


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
