import abc
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.tracing_wrap import wrap_invoke
from onyx.llm.tracing_wrap import wrap_stream
from onyx.utils.logger import setup_logger

logger = setup_logger()


class LLMUserIdentity(BaseModel):
    user_id: str | None = None
    session_id: str | None = None


class LLMConfig(BaseModel):
    model_provider: str
    model_name: str
    temperature: float
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None
    custom_config: dict[str, str] | None = None
    max_input_tokens: int
    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}


class LLM(abc.ABC):
    """Abstract base for every LLM backend used by Onyx.

    Concrete subclasses have their ``invoke`` and ``stream`` methods
    auto-wrapped (via ``__init_subclass__`` below) with a fallback braintrust
    ``generation_span``. This guarantees that every LLM call — from any call
    site, including future subclasses — is captured in braintrust without
    per-callsite instrumentation. Callers that explicitly wrap their calls
    with ``llm_generation_span`` are unaffected: the fallback detects the
    outer span and no-ops.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._wrap_method_if_defined("invoke", wrap_invoke)
        cls._wrap_method_if_defined("stream", wrap_stream)

    @classmethod
    def _wrap_method_if_defined(
        cls,
        name: str,
        wrapper_fn: Callable[[Callable[..., Any]], Callable[..., Any]],
    ) -> None:
        """Replace ``cls.<name>`` with ``wrapper_fn(cls.<name>)`` iff the method
        is defined directly on this subclass.

        Inherited methods are skipped — they've already been wrapped on the
        parent class, so re-wrapping would nest two fallback spans around
        the same call.
        """
        fn = cls.__dict__.get(name)
        if fn is not None:
            setattr(cls, name, wrapper_fn(fn))

    @property
    @abc.abstractmethod
    def config(self) -> LLMConfig:
        raise NotImplementedError

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
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
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        raise NotImplementedError
