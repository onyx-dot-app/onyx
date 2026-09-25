"""LLM interface, public settings, and provider configuration."""

import abc
from collections.abc import Generator

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationRequest,
    ReasoningEffort,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode


class LLMUserIdentity(BaseModel):
    user_id: str | None = None
    session_id: str | None = None


class GenerationContext(BaseModel):
    """Policy shared by the provider operation and its tracing span."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    cancellation: CancellationSignal | None = None
    # Streaming idle reads only; invoke uses its total deadline.
    stall_timeout_s: int | None = Field(default=None, gt=0)
    # Invoke defaults to a finite deadline; streams have no default deadline.
    total_timeout_s: float | None = Field(default=None, gt=0)
    user_identity: LLMUserIdentity | None = None
    flow: LLMFlow | None = None
    content_mode: TraceContentMode | None = None


class LlmRequestPolicy(BaseModel):
    """Per-request policy an LLM call must carry (e.g. incognito retention
    suppression). Merged after every other source so nothing overrides it."""

    headers: dict[str, str] = {}
    model_kwargs: dict[str, JsonValue] = {}


class LLMConfig(BaseModel):
    """Provider settings and resolved capabilities, including credentials."""

    model_provider: str
    model_name: str
    temperature: float
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None
    custom_config: dict[str, str] | None = None
    max_input_tokens: int
    supports_images: bool | None = None
    # Here rather than in the chat loop, so every invoke path gets it.
    reasoning_effort_default: ReasoningEffort | None = None
    reasoning_effort_user_default: ReasoningEffort | None = None
    reasoning_effort_max: ReasoningEffort | None = None
    # This disables the "model_" protected namespace for pydantic.
    model_config = ConfigDict(protected_namespaces=())


class LLM(abc.ABC):
    """Generate assistant messages from conversation input and tool definitions."""

    @property
    @abc.abstractmethod
    def config(self) -> LLMConfig: ...

    @abc.abstractmethod
    def redact_error(self, text: str) -> str: ...

    @abc.abstractmethod
    def invoke(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> AssistantMessage:
        """Return one complete response, or raise LLMTimeoutError at the total deadline.

        context.total_timeout_s defaults to LLM_INVOKE_TIMEOUT_S when unset.
        The deadline is always finite so a stalled call cannot hold a worker forever.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def stream(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> Generator[GenerationEvent, None, None]:
        """Yield generation events as output arrives.

        context.stall_timeout_s limits idle reads and defaults to LLM_SOCKET_READ_TIMEOUT.
        Streams have no total deadline unless context.total_timeout_s is set.
        Close the generator when stopping early to release provider resources.
        """
        raise NotImplementedError
