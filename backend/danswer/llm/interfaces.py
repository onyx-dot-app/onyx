import abc
from collections.abc import Iterator

from langchain.schema.language_model import LanguageModelInput
from pydantic import BaseModel

from danswer.utils.logger import setup_logger


logger = setup_logger()


class LLMConfig(BaseModel):
    model_provider: str
    model_name: str
    temperature: float


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
    def invoke(self, prompt: LanguageModelInput) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def stream(self, prompt: LanguageModelInput) -> Iterator[str]:
        raise NotImplementedError
