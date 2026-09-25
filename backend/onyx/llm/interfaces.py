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
    timeout: int | None = Field(default=None, gt=0)
    total_timeout: float | None = Field(default=None, gt=0)
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

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    model_provider: str
    model_name: str
    max_input_tokens: int
    max_output_tokens: int | None = None
    supports_images: bool | None = None
    temperature: float
    api_base: str | None = None
    deployment_name: str | None = None
    reasoning_effort_default: ReasoningEffort | None = None
    reasoning_effort_user_default: ReasoningEffort | None = None
    reasoning_effort_max: ReasoningEffort | None = None

    api_key: str | None = None
    api_version: str | None = None
    custom_config: dict[str, str] | None = None


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
    ) -> AssistantMessage: ...

    @abc.abstractmethod
    def stream(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> Generator[GenerationEvent, None, None]: ...
