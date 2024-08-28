from pydantic import BaseModel
from pydantic import Field

from danswer.configs.constants import DocumentSource
from danswer.one_shot_answer.models import ThreadMessage
from danswer.search.enums import LLMEvaluationType
from danswer.search.enums import SearchType
from danswer.search.models import ChunkContext
from danswer.search.models import RerankingDetails
from danswer.search.models import RetrievalDetails
from danswer.server.manage.models import StandardAnswer


class StandardAnswerRequest(BaseModel):
    message: str
    slack_bot_categories: list[str]


class StandardAnswerResponse(BaseModel):
    standard_answers: list[StandardAnswer] = []


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

    chat_session_id: int
    # New message contents
    message: str
    # Defaults to using retrieval with no additional filters
    retrieval_options: RetrievalDetails | None = None
    # Allows the caller to specify the exact search query they want to use
    # will disable Query Rewording if specified
    query_override: str | None = None
    # If search_doc_ids provided, then retrieval options are unused
    search_doc_ids: list[int] | None = None


class BasicCreateChatMessageWithHistoryRequest(ChunkContext):
    # Last element is the new query. All previous elements are historical context
    messages: list[ThreadMessage]
    prompt_id: int | None
    persona_id: int
    retrieval_options: RetrievalDetails = Field(default_factory=RetrievalDetails)
    query_override: str | None = None
    skip_rerank: bool | None = None


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
    simple_search_docs: list[SimpleDoc] | None = None
    error_msg: str | None = None
    message_id: int | None = None
    llm_chunks_indices: list[int] | None = None
