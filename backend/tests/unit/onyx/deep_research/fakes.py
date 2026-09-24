"""Model stand-in and helpers for Deep Research batch-runner tests."""

import queue
from collections.abc import Iterator

from onyx.chat.emitter import Emitter
from onyx.configs.chat_configs import LLM_INVOKE_TIMEOUT_S, LLM_SOCKET_READ_TIMEOUT
from onyx.llm.interfaces import (
    LLM,
    LanguageModelInput,
    LLMConfig,
    LLMUserIdentity,
    ReasoningEffort,
    ToolChoice,
)
from onyx.llm.model_response import ModelResponse, ModelResponseStream
from onyx.server.query_and_chat.streaming_models import Packet


class UnusedLLM(LLM):
    """For tests that replace the research child; any model call is a bug."""

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="unused-model",
            temperature=0.0,
            max_input_tokens=200_000,
        )

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
    ) -> ModelResponse:
        raise AssertionError("UnusedLLM.invoke was called")

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
        raise AssertionError("UnusedLLM.stream was called")


def make_emitter() -> Emitter:
    merged: queue.Queue[tuple[int, Packet | Exception | object]] = queue.Queue()
    return Emitter(merged_queue=merged)


def token_counter(value: str) -> int:
    return len(value) // 4 + 1
