import abc
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from onyx.llm.models import AssistantMessage, GenerationRequest, ReasoningEffort
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode


class LLMUserIdentity(BaseModel):
    user_id: str | None = None
    session_id: str | None = None


class GenerationContext(BaseModel):
    """Call policy shared by the provider request and its tracing span."""

    model_config = ConfigDict(extra="forbid")

    # Invoke defaults to LLM_INVOKE_TIMEOUT_S.
    total_timeout_s: float | None = Field(default=None, gt=0)
    user_identity: LLMUserIdentity | None = None
    flow: LLMFlow | None = None
    content_mode: TraceContentMode | None = None


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
    """Generate assistant messages from shared messages and tool definitions."""

    @property
    @abc.abstractmethod
    def config(self) -> LLMConfig:
        raise NotImplementedError

    @abc.abstractmethod
    def invoke(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> AssistantMessage:
        """Return one complete response, or raise ``LLMTimeoutError`` at the total deadline.

        ``context.total_timeout_s`` defaults to ``LLM_INVOKE_TIMEOUT_S``. The
        timeout is always finite: our Celery pools disable Celery's own time
        limits, so a call that never ends would hold its worker thread forever.
        The call records its own generation span; set ``context.flow`` to tag it.
        """
        raise NotImplementedError
