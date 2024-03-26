from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field
from pydantic import root_validator

from danswer.chat.models import AnswerQuestionStreamReturn
from danswer.configs.constants import MessageType

if TYPE_CHECKING:
    from danswer.db.models import ChatMessage


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
