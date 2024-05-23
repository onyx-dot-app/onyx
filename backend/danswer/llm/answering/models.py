from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from typing import TYPE_CHECKING

from langchain.schema.messages import AIMessage
from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage
from langchain.schema.messages import SystemMessage
from pydantic import BaseModel
from pydantic import Field
from pydantic import root_validator

from danswer.chat.models import AnswerQuestionStreamReturn
from danswer.configs.constants import MessageType
from danswer.file_store.models import InMemoryChatFile
from danswer.llm.override_models import PromptOverride
from danswer.llm.utils import build_content_with_imgs

if TYPE_CHECKING:
    from danswer.db.models import ChatMessage
    from danswer.db.models import Prompt


StreamProcessor = Callable[[Iterator[str]], AnswerQuestionStreamReturn]


class PreviousMessage(BaseModel):
    """Simplified version of `ChatMessage`"""

    message: str
    token_count: int
    message_type: MessageType
    files: list[InMemoryChatFile]

    @classmethod
    def from_chat_message(
        cls, chat_message: "ChatMessage", available_files: list[InMemoryChatFile]
    ) -> "PreviousMessage":
        message_file_ids = (
            [file["id"] for file in chat_message.files] if chat_message.files else []
        )
        return cls(
            message=chat_message.message,
            token_count=chat_message.token_count,
            message_type=chat_message.message_type,
            files=[
                file
                for file in available_files
                if str(file.file_id) in message_file_ids
            ],
        )

    def to_langchain_msg(self) -> BaseMessage:
        content = build_content_with_imgs(self.message, self.files)
        if self.message_type == MessageType.USER:
            return HumanMessage(content=content)
        elif self.message_type == MessageType.ASSISTANT:
            return AIMessage(content=content)
        else:
            return SystemMessage(content=content)


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
    # If using tools, then we need to consider the tool length
    tool_num_tokens: int = 0
    # If using a tool message to represent the docs, then we have to JSON serialize
    # the document content, which adds to the token count.
    using_tool_message: bool = False


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
