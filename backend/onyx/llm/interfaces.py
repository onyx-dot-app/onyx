import abc
from collections.abc import Iterator

from braintrust import traced
from pydantic import BaseModel

from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.utils.logger import setup_logger

logger = setup_logger()


class LLMConfig(BaseModel):
    model_provider: str
    model_name: str
    temperature: float
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None
    credentials_file: str | None = None
    max_input_tokens: int
    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}


class LLM(abc.ABC):
    @property
    @abc.abstractmethod
    def config(self) -> LLMConfig:
        raise NotImplementedError

    @traced(name="invoke llm", type="llm")
    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> "ModelResponse":
        raise NotImplementedError

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> Iterator[ModelResponseStream]:
        raise NotImplementedError
