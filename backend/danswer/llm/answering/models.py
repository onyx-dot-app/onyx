from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field
from pydantic import root_validator

from danswer.chat.models import AnswerQuestionStreamReturn
from danswer.configs.constants import MessageType
from danswer.configs.model_configs import GEN_AI_MODEL_PROVIDER
from danswer.llm.override_models import LLMOverride
from danswer.llm.override_models import PromptOverride
from danswer.llm.utils import get_default_llm_version

if TYPE_CHECKING:
    from danswer.db.models import ChatMessage
    from danswer.db.models import Prompt
    from danswer.db.models import Persona


StreamProcessor = Callable[[Iterator[str]], AnswerQuestionStreamReturn]


class PreviousMessage(BaseModel):
    """Simplified version of `ChatMessage`"""

    message: str
    token_count: int
    message_type: MessageType

    @classmethod
    def from_chat_message(cls, chat_message: "ChatMessage") -> "PreviousMessage":
        return cls(
            message=chat_message.message,
            token_count=chat_message.token_count,
            message_type=chat_message.message_type,
        )


class DocumentPruningConfig(BaseModel):
    max_chunks: int | None = None
    max_window_percentage: float | None = None
    max_tokens: int | None = None
    # different pruning behavior is expected when the
    # user manually selects documents they want to chat with
    # e.g. we don't want to truncate each document to be no more
    # than one chunk long
    is_manually_selected_docs: bool = False
    # If user specifies to include additional context chunks for each match, then different pruning
    # is used. As many Sections as possible are included, and the last Section is truncated
    use_sections: bool = False


class CitationConfig(BaseModel):
    all_docs_useful: bool = False


class QuotesConfig(BaseModel):
    pass


class AnswerStyleConfig(BaseModel):
    citation_config: CitationConfig | None = None
    quotes_config: QuotesConfig | None = None
    document_pruning_config: DocumentPruningConfig = Field(
        default_factory=DocumentPruningConfig
    )

    @root_validator
    def check_quotes_and_citation(cls, values: dict[str, Any]) -> dict[str, Any]:
        citation_config = values.get("citation_config")
        quotes_config = values.get("quotes_config")

        if citation_config is None and quotes_config is None:
            raise ValueError(
                "One of `citation_config` or `quotes_config` must be provided"
            )

        if citation_config is not None and quotes_config is not None:
            raise ValueError(
                "Only one of `citation_config` or `quotes_config` must be provided"
            )

        return values


class LLMConfig(BaseModel):
    """Final representation of the LLM configuration passed into
    the `Answer` object."""

    model_provider: str
    model_version: str
    temperature: float

    @classmethod
    def from_persona(
        cls, persona: "Persona", llm_override: LLMOverride | None = None
    ) -> "LLMConfig":
        model_provider_override = llm_override.model_provider if llm_override else None
        model_version_override = llm_override.model_version if llm_override else None
        temperature_override = llm_override.temperature if llm_override else None

        return cls(
            model_provider=model_provider_override or GEN_AI_MODEL_PROVIDER,
            model_version=(
                model_version_override
                or persona.llm_model_version_override
                or get_default_llm_version()[0]
            ),
            temperature=temperature_override or 0.0,
        )

    class Config:
        frozen = True


class PromptConfig(BaseModel):
    """Final representation of the Prompt configuration passed
    into the `Answer` object."""

    system_prompt: str
    task_prompt: str
    datetime_aware: bool
    include_citations: bool

    @classmethod
    def from_model(
        cls, model: "Prompt", prompt_override: PromptOverride | None = None
    ) -> "PromptConfig":
        override_system_prompt = (
            prompt_override.system_prompt if prompt_override else None
        )
        override_task_prompt = prompt_override.task_prompt if prompt_override else None

        return cls(
            system_prompt=override_system_prompt or model.system_prompt,
            task_prompt=override_task_prompt or model.task_prompt,
            datetime_aware=model.datetime_aware,
            include_citations=model.include_citations,
        )

    # needed so that this can be passed into lru_cache funcs
    class Config:
        frozen = True
