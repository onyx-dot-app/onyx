from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerContexts
from danswer.chat.models import DanswerQuotes
from danswer.chat.models import QADocsResponse
from danswer.configs.constants import MessageType
from danswer.search.enums import LLMEvaluationType
from danswer.search.enums import RecencyBiasSetting
from danswer.search.enums import SearchType
from danswer.search.models import ChunkContext
from danswer.search.models import RerankingDetails
from danswer.search.models import RetrievalDetails


class QueryRephrase(BaseModel):
    rephrased_query: str


class ThreadMessage(BaseModel):
    message: str
    sender: str | None = None
    role: MessageType = MessageType.USER


class PromptConfig(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    task_prompt: str = ""
    include_citations: bool = True
    datetime_aware: bool = True


class DocumentSetConfig(BaseModel):
    id: int


class ToolConfig(BaseModel):
    id: int


class PersonaConfig(BaseModel):
    name: str
    description: str
    search_type: SearchType = SearchType.SEMANTIC
    num_chunks: float | None = None
    llm_relevance_filter: bool = False
    llm_filter_extraction: bool = False
    recency_bias: RecencyBiasSetting = RecencyBiasSetting.AUTO
    llm_model_provider_override: str | None = None
    llm_model_version_override: str | None = None

    prompts: list[PromptConfig] = Field(default_factory=list)
    prompt_ids: list[int] = Field(default_factory=list)

    document_set_ids: list[int] = Field(default_factory=list)
    tools: list[ToolConfig] = Field(default_factory=list)
    tool_ids: list[int] = Field(default_factory=list)
    custom_tools_openapi: list[dict[str, Any]] = Field(default_factory=list)


class DirectQARequest(ChunkContext):
    persona_config: PersonaConfig | None = None
    persona_id: int | None = None

    messages: list[ThreadMessage]
    prompt_id: int | None = None
    multilingual_query_expansion: list[str] | None = None
    retrieval_options: RetrievalDetails = Field(default_factory=RetrievalDetails)
    rerank_settings: RerankingDetails | None = None
    evaluation_type: LLMEvaluationType = LLMEvaluationType.UNSPECIFIED

    chain_of_thought: bool = False
    return_contexts: bool = False

    # allows the caller to specify the exact search query they want to use
    # can be used if the message sent to the LLM / query should not be the same
    # will also disable Thread-based Rewording if specified
    query_override: str | None = None

    # If True, skips generative an AI response to the search query
    skip_gen_ai_answer_generation: bool = False

    @model_validator(mode="after")
    def check_persona_fields(self) -> "DirectQARequest":
        if (self.persona_config is None) == (self.persona_id is None):
            raise ValueError("Exactly one of persona_config or persona_id must be set")
        return self

    @model_validator(mode="after")
    def check_chain_of_thought_and_prompt_id(self) -> "DirectQARequest":
        if self.chain_of_thought and self.prompt_id is not None:
            raise ValueError(
                "If chain_of_thought is True, prompt_id must be None"
                "The chain of thought prompt is only for question "
                "answering and does not accept customizing."
            )

        return self


class OneShotQAResponse(BaseModel):
    # This is built piece by piece, any of these can be None as the flow could break
    answer: str | None = None
    rephrase: str | None = None
    quotes: DanswerQuotes | None = None
    citations: list[CitationInfo] | None = None
    docs: QADocsResponse | None = None
    llm_selected_doc_indices: list[int] | None = None
    error_msg: str | None = None
    answer_valid: bool = True  # Reflexion result, default True if Reflexion not run
    chat_message_id: int | None = None
    contexts: DanswerContexts | None = None
