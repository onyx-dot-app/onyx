import abc
from collections.abc import Callable, Iterator
from typing import Any

from pydantic import BaseModel

from onyx.configs.chat_configs import LLM_INVOKE_TIMEOUT_S, LLM_SOCKET_READ_TIMEOUT
from onyx.llm.model_request import LanguageModelInput
from onyx.llm.model_response import ModelResponse, ModelResponseStream
from onyx.llm.models import ReasoningEffort, ToolChoice
from onyx.llm.tracing_wrap import wrap_invoke, wrap_stream
from onyx.utils.logger import setup_logger

logger = setup_logger()


class LLMUserIdentity(BaseModel):
    user_id: str | None = None
    session_id: str | None = None


class LlmRequestPolicy(BaseModel):
    """Per-request policy an LLM call must carry (e.g. incognito retention
    suppression). Merged after every other source so nothing overrides it."""

    headers: dict[str, str] = {}
    model_kwargs: dict[str, Any] = {}


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
    # Here rather than in the chat loop, so every invoke path gets it.
    reasoning_effort_default: ReasoningEffort | None = None
    reasoning_effort_user_default: ReasoningEffort | None = None
    reasoning_effort_max: ReasoningEffort | None = None
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
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        total_timeout_s: float = LLM_INVOKE_TIMEOUT_S,
    ) -> "ModelResponse":
        """Return one complete response, or raise ``LLMTimeoutError`` after
        ``total_timeout_s`` seconds.

        Use ``stream`` when you want output as it arrives. The timeout is always
        finite: our Celery pools disable Celery's own time limits, so a call that
        never ends would hold its worker thread forever.
        """
        raise NotImplementedError

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        stall_timeout_s: int = LLM_SOCKET_READ_TIMEOUT,
    ) -> Iterator[ModelResponseStream]:
        """Yield deltas as they arrive.

        ``stall_timeout_s`` bounds the gap between deltas, not the whole run. A
        stream takes no total timeout: its consumer sees progress and owns the
        end-to-end deadline, and some runs (deep research reports) take many
        minutes.
        """
        raise NotImplementedError
