from collections.abc import Iterator
from typing import Any

from langchain.schema.language_model import LanguageModelInput

from danswer.configs.model_configs import GEN_AI_MAX_OUTPUT_TOKENS
from danswer.configs.model_configs import GEN_AI_TEMPERATURE
from danswer.llm.interfaces import LLM
from danswer.llm.utils import convert_lm_input_to_basic_string
from danswer.utils.logger import setup_logger


logger = setup_logger()


class DummyGPT4All:
    """In the case of import failure due to architectural incompatibilities,
    this module does not raise exceptions during server startup,
    as long as the module isn't actually used"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("GPT4All library not installed.")


try:
    from gpt4all import GPT4All  # type:ignore
except ImportError:
    # Setting a low log level because users get scared when they see this
    logger.debug(
        "GPT4All library not installed. "
        "If you wish to run GPT4ALL (in memory) to power Danswer's "
        "Generative AI features, please install gpt4all==2.0.2."
    )
    GPT4All = DummyGPT4All


class DanswerGPT4All(LLM):
    """Option to run an LLM locally, however this is significantly slower and
    answers tend to be much worse

    NOTE: currently unused, but kept for future reference / if we want to add this back.
    """

    @property
    def requires_warm_up(self) -> bool:
        """GPT4All models are lazy loaded, load them on server start so that the
        first inference isn't extremely delayed"""
        return True

    @property
    def requires_api_key(self) -> bool:
        return False

    def __init__(
        self,
        timeout: int,
        model_version: str,
        max_output_tokens: int = GEN_AI_MAX_OUTPUT_TOKENS,
        temperature: float = GEN_AI_TEMPERATURE,
    ):
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.gpt4all_model = GPT4All(model_version)

    def log_model_configs(self) -> None:
        logger.debug(
            f"GPT4All Model: {self.gpt4all_model}, Temperature: {self.temperature}"
        )

    def invoke(self, prompt: LanguageModelInput) -> str:
        prompt_basic = convert_lm_input_to_basic_string(prompt)
        return self.gpt4all_model.generate(prompt_basic)

    def stream(self, prompt: LanguageModelInput) -> Iterator[str]:
        prompt_basic = convert_lm_input_to_basic_string(prompt)
        return self.gpt4all_model.generate(prompt_basic, streaming=True)
