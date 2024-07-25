import abc
from collections.abc import Iterator
from typing import Literal

from langchain.schema.language_model import LanguageModelInput
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from danswer.configs.app_configs import DISABLE_GENERATIVE_AI
from danswer.configs.app_configs import LOG_DANSWER_MODEL_INTERACTIONS
from danswer.utils.logger import setup_logger


logger = setup_logger()

ToolChoiceOptions = Literal["required"] | Literal["auto"] | Literal["none"]


class LLMConfig(BaseModel):
    model_provider: str
    model_name: str
    temperature: float
    api_key: str | None
    api_base: str | None
    api_version: str | None


def log_prompt(prompt: LanguageModelInput) -> None:
    if isinstance(prompt, list):
        for ind, msg in enumerate(prompt):
            if isinstance(msg, AIMessageChunk):
                if msg.content:
                    log_msg = msg.content
                elif msg.tool_call_chunks:
                    log_msg = "Tool Calls: " + str(
                        [
                            {
                                key: value
                                for key, value in tool_call.items()
                                if key != "index"
                            }
                            for tool_call in msg.tool_call_chunks
                        ]
                    )
                else:
                    log_msg = ""
                logger.debug(f"Message {ind}:\n{log_msg}")
            else:
                logger.debug(f"Message {ind}:\n{msg.content}")
    if isinstance(prompt, str):
        logger.debug(f"Prompt:\n{prompt}")


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

    def _precall(self, prompt: LanguageModelInput) -> None:
        if DISABLE_GENERATIVE_AI:
            raise Exception("Generative AI is disabled")
        if LOG_DANSWER_MODEL_INTERACTIONS:
            log_prompt(prompt)

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> BaseMessage:
        self._precall(prompt)
        # TODO add a postcall to log model outputs independent of concrete class
        # implementation
        return self._invoke_implementation(prompt, tools, tool_choice)

    @abc.abstractmethod
    def _invoke_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> BaseMessage:
        raise NotImplementedError

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> Iterator[BaseMessage]:
        self._precall(prompt)
        # TODO add a postcall to log model outputs independent of concrete class
        # implementation
        return self._stream_implementation(prompt, tools, tool_choice)

    @abc.abstractmethod
    def _stream_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> Iterator[BaseMessage]:
        raise NotImplementedError
