import abc
import os
from collections.abc import Iterator
from typing import Any

import litellm  # type:ignore
from langchain.chat_models.base import BaseChatModel
from langchain.schema.language_model import LanguageModelInput
from langchain_community.chat_models import ChatLiteLLM

from danswer.configs.app_configs import LOG_ALL_MODEL_INTERACTIONS
from danswer.configs.model_configs import DISABLE_LITELLM_STREAMING
from danswer.configs.model_configs import GEN_AI_API_ENDPOINT
from danswer.configs.model_configs import GEN_AI_API_VERSION
from danswer.configs.model_configs import GEN_AI_LLM_PROVIDER_TYPE
from danswer.configs.model_configs import GEN_AI_MAX_OUTPUT_TOKENS
from danswer.configs.model_configs import GEN_AI_TEMPERATURE
from danswer.llm.interfaces import LLM
from danswer.llm.interfaces import LLMConfig
from danswer.llm.utils import message_generator_to_string_generator
from danswer.llm.utils import should_be_verbose
from danswer.utils.logger import setup_logger


logger = setup_logger()

# If a user configures a different model and it doesn't support all the same
# parameters like frequency and presence, just ignore them
litellm.drop_params = True
litellm.telemetry = False


class LangChainChatLLM(LLM, abc.ABC):
    @property
    @abc.abstractmethod
    def llm(self) -> BaseChatModel:
        raise NotImplementedError

    @staticmethod
    def _log_prompt(prompt: LanguageModelInput) -> None:
        if isinstance(prompt, list):
            for ind, msg in enumerate(prompt):
                logger.debug(f"Message {ind}:\n{msg.content}")
        if isinstance(prompt, str):
            logger.debug(f"Prompt:\n{prompt}")

    def log_model_configs(self) -> None:
        llm_dict = {k: v for k, v in self.llm.__dict__.items() if v}
        llm_dict.pop("client")
        logger.info(
            f"LLM Model Class: {self.llm.__class__.__name__}, Model Config: {llm_dict}"
        )

    def invoke(self, prompt: LanguageModelInput) -> str:
        if LOG_ALL_MODEL_INTERACTIONS:
            self._log_prompt(prompt)

        model_raw = self.llm.invoke(prompt).content
        if LOG_ALL_MODEL_INTERACTIONS:
            logger.debug(f"Raw Model Output:\n{model_raw}")

        if not isinstance(model_raw, str):
            raise RuntimeError(
                "Model output inconsistent with expected type, "
                "is this related to a library upgrade?"
            )

        return model_raw

    def stream(self, prompt: LanguageModelInput) -> Iterator[str]:
        if LOG_ALL_MODEL_INTERACTIONS:
            self.log_model_configs()
            self._log_prompt(prompt)

        if DISABLE_LITELLM_STREAMING:
            yield self.invoke(prompt)
            return

        output_tokens = []
        for token in message_generator_to_string_generator(self.llm.stream(prompt)):
            output_tokens.append(token)
            yield token

        full_output = "".join(output_tokens)
        if LOG_ALL_MODEL_INTERACTIONS:
            logger.debug(f"Raw Model Output:\n{full_output}")


class DefaultMultiLLM(LangChainChatLLM):
    """Uses Litellm library to allow easy configuration to use a multitude of LLMs
    See https://python.langchain.com/docs/integrations/chat/litellm"""

    DEFAULT_MODEL_PARAMS: dict[str, Any] = {
        "frequency_penalty": 0,
        "presence_penalty": 0,
    }

    def __init__(
        self,
        api_key: str | None,
        timeout: int,
        model_provider: str,
        model_name: str,
        api_base: str | None = GEN_AI_API_ENDPOINT,
        api_version: str | None = GEN_AI_API_VERSION,
        custom_llm_provider: str | None = GEN_AI_LLM_PROVIDER_TYPE,
        max_output_tokens: int = GEN_AI_MAX_OUTPUT_TOKENS,
        temperature: float = GEN_AI_TEMPERATURE,
        custom_config: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        self._model_provider = model_provider
        self._model_version = model_name
        self._temperature = temperature

        # Litellm Langchain integration currently doesn't take in the api key param
        # Can place this in the call below once integration is in
        litellm.api_key = api_key or "dummy-key"
        litellm.api_version = api_version

        # NOTE: have to set these as environment variables for Litellm since
        # not all are able to passed in but they always support them set as env
        # variables
        if custom_config:
            for k, v in custom_config.items():
                os.environ[k] = v

        model_kwargs = (
            DefaultMultiLLM.DEFAULT_MODEL_PARAMS if model_provider == "openai" else {}
        )

        if extra_headers:
            model_kwargs.update({"extra_headers": extra_headers})

        self._llm = ChatLiteLLM(  # type: ignore
            model=(
                model_name if custom_llm_provider else f"{model_provider}/{model_name}"
            ),
            api_base=api_base,
            custom_llm_provider=custom_llm_provider,
            max_tokens=max_output_tokens,
            temperature=temperature,
            request_timeout=timeout,
            # LiteLLM and some model providers don't handle these params well
            # only turning it on for OpenAI
            model_kwargs=model_kwargs,
            verbose=should_be_verbose(),
            max_retries=0,  # retries are handled outside of langchain
        )

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider=self._model_provider,
            model_name=self._model_version,
            temperature=self._temperature,
        )

    @property
    def llm(self) -> ChatLiteLLM:
        return self._llm
