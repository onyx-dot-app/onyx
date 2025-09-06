from collections import OrderedDict
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import QADocsResponse
from onyx.chat.models import ThreadMessage
from onyx.configs.constants import DocumentSource
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import SearchType
from onyx.context.search.models import ChunkContext
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.server.manage.models import StandardAnswer
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import SubQuestionIdentifier


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
    """If a chat_session_id is not provided, a persona_id must be provided to automatically create a new chat session
    Note, for simplicity this option only allows for a single linear chain of messages
    """

    chat_session_id: UUID | None = None
    # Optional persona_id to create a new chat session if chat_session_id is not provided
    persona_id: int | None = None
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

    # If True, uses agentic search instead of basic search
    use_agentic_search: bool = False

    @model_validator(mode="after")
    def validate_chat_session_or_persona(self) -> "BasicCreateChatMessageRequest":
        if self.chat_session_id is None and self.persona_id is None:
            raise ValueError("Either chat_session_id or persona_id must be provided")
        return self


class BasicCreateChatMessageWithHistoryRequest(ChunkContext):
    # Last element is the new query. All previous elements are historical context
    messages: list[ThreadMessage]
    persona_id: int
    retrieval_options: RetrievalDetails | None = None
    query_override: str | None = None
    skip_rerank: bool | None = None
    # If search_doc_ids provided, then retrieval options are unused
    search_doc_ids: list[int] | None = None
    # only works if using an OpenAI model. See the following for more details:
    # https://platform.openai.com/docs/guides/structured-outputs/introduction
    structured_response_format: dict | None = None
    # If True, uses agentic search instead of basic search
    use_agentic_search: bool = False


class SimpleDoc(BaseModel):
    id: str
    semantic_identifier: str
    link: str | None
    blurb: str
    match_highlights: list[str]
    source_type: DocumentSource
    metadata: dict | None


class AgentSubQuestion(SubQuestionIdentifier):
    sub_question: str
    document_ids: list[str]


class AgentAnswer(SubQuestionIdentifier):
    answer: str
    answer_type: Literal["agent_sub_answer", "agent_level_answer"]


class AgentSubQuery(SubQuestionIdentifier):
    sub_query: str
    query_id: int

    @staticmethod
    def make_dict_by_level_and_question_index(
        original_dict: dict[tuple[int, int, int], "AgentSubQuery"],
    ) -> dict[int, dict[int, list["AgentSubQuery"]]]:
        """Takes a dict of tuple(level, question num, query_id) to sub queries.

        returns a dict of level to dict[question num to list of query_id's]
        Ordering is asc for readability.
        """
        # In this function, when we sort int | None, we deliberately push None to the end

        # map entries to the level_question_dict
        level_question_dict: dict[int, dict[int, list["AgentSubQuery"]]] = {}
        for k1, obj in original_dict.items():
            level = k1[0]
            question = k1[1]

            if level not in level_question_dict:
                level_question_dict[level] = {}

            if question not in level_question_dict[level]:
                level_question_dict[level][question] = []

            level_question_dict[level][question].append(obj)

        # sort each query_id list and question_index
        for key1, obj1 in level_question_dict.items():
            for key2, value2 in obj1.items():
                # sort the query_id list of each question_index
                level_question_dict[key1][key2] = sorted(
                    value2, key=lambda o: o.query_id
                )
            # sort the question_index dict of level
            level_question_dict[key1] = OrderedDict(
                sorted(level_question_dict[key1].items(), key=lambda x: (x is None, x))
            )

        # sort the top dict of levels
        sorted_dict = OrderedDict(
            sorted(level_question_dict.items(), key=lambda x: (x is None, x))
        )
        return sorted_dict


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

    # If True, uses agentic search instead of basic search
    use_agentic_search: bool = False

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
