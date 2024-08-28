from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic import root_validator

from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerContexts
from danswer.chat.models import DanswerQuotes
from danswer.chat.models import QADocsResponse
from danswer.configs.constants import MessageType
from danswer.search.enums import LLMEvaluationType
from danswer.search.models import ChunkContext
from danswer.search.models import RerankingDetails
from danswer.search.models import RetrievalDetails


class QueryRephrase(BaseModel):
    rephrased_query: str


class ThreadMessage(BaseModel):
    message: str
    sender: str | None
    role: MessageType = MessageType.USER


class DirectQARequest(ChunkContext):
    messages: list[ThreadMessage]
    prompt_id: int | None
    persona_id: int
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

    @root_validator
    def check_chain_of_thought_and_prompt_id(
        cls, values: dict[str, Any]
    ) -> dict[str, Any]:
        chain_of_thought = values.get("chain_of_thought")
        prompt_id = values.get("prompt_id")

        if chain_of_thought and prompt_id is not None:
            raise ValueError(
                "If chain_of_thought is True, prompt_id must be None"
                "The chain of thought prompt is only for question "
                "answering and does not accept customizing."
            )

        return values


class OneShotQAResponse(BaseModel):
    # This is built piece by piece, any of these can be None as the flow could break
    answer: str | None = None
    rephrase: str | None = None
    quotes: DanswerQuotes | None = None
    citations: list[CitationInfo] | None = None
    docs: QADocsResponse | None = None
    llm_chunks_indices: list[int] | None = None
    error_msg: str | None = None
    answer_valid: bool = True  # Reflexion result, default True if Reflexion not run
    chat_message_id: int | None = None
    contexts: DanswerContexts | None = None
