import abc
from collections.abc import Iterator
from typing import Literal

from langchain.schema.language_model import LanguageModelInput
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from danswer.utils.logger import setup_logger


logger = setup_logger()

ToolChoiceOptions = Literal["required"] | Literal["auto"] | Literal["none"]


class LLMConfig(BaseModel):
    model_provider: str
    model_name: str
    temperature: float
    api_key: str | None


class LLM(abc.ABC):
    """Mimics the LangChain LLM / BaseChatModel interfaces to make it easy
    to use these implementations to connect to a variety of LLM providers."""

    @property
    def requires_warm_up(self) -> bool:
        """Is this model running in memory and needs an initial call to warm it up?"""
        return False

    @property
    def requires_api_key(self) -> bool:
        return True

    @property
    @abc.abstractmethod
    def config(self) -> LLMConfig:
        raise NotImplementedError

    @abc.abstractmethod
    def log_model_configs(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> BaseMessage:
        raise NotImplementedError

    @abc.abstractmethod
    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> Iterator[BaseMessage]:
        raise NotImplementedError
