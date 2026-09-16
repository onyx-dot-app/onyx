"""Run the chat adapter through model streaming, tools, and packet rendering."""

import asyncio
from collections.abc import Callable, Generator, Iterator, Sequence
from typing import Any

from onyx.agents.coordination import AgentCoordinator
from onyx.agents.events import AgentEvent
from onyx.agents.models import RunResult
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM, GenerationContext, LLMConfig, LLMInfo
from onyx.llm.litellm_models import (
    Delta,
    LanguageModelInput,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationRequest,
    Message,
    ToolResult,
)
from onyx.llm.multi_llm import LitellmLLM, LitellmTransport
from onyx.tools.interface import FunctionToolDefinition, Tool, ToolContext


class ScriptedTransport(LitellmTransport):
    def __init__(self, steps: list[Delta], max_input_tokens: int = 4096) -> None:
        self.max_input_tokens = max_input_tokens
        self.steps = iter(steps)
        self.requests: list[dict[str, Any]] = []

    @property
    def info(self) -> LLMInfo:
        return LLMInfo.model_validate(self.config.model_dump())

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="test-model",
            max_input_tokens=self.max_input_tokens,
            temperature=0,
        )

    def stream(
        self, prompt: LanguageModelInput, *args: Any, **kwargs: Any
    ) -> Iterator[ModelResponseStream]:
        assert not args
        self.requests.append({"prompt": prompt, **kwargs})
        yield ModelResponseStream(
            id="test", created="1", choice=StreamingChoice(delta=next(self.steps))
        )


class ScriptedLLM(LitellmLLM):
    transport: ScriptedTransport

    def __init__(self, steps: list[Delta], max_input_tokens: int = 4096) -> None:
        super().__init__(ScriptedTransport(steps, max_input_tokens))
        self.requests = self.transport.requests


class FakeModelClient(LLM):
    """Canonical client for deterministic runtime tests."""

    def __init__(
        self, reply: Callable[[GenerationRequest, CancellationSignal], AssistantMessage]
    ) -> None:
        self.reply = reply

    @property
    def info(self) -> LLMInfo:
        return LLMInfo(
            model_provider="openai",
            model_name="test-model",
            max_input_tokens=4096,
            temperature=0,
        )

    def redact_error(self, text: str) -> str:
        return text

    def invoke(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> AssistantMessage:
        signal = (
            context.cancellation
            if context and context.cancellation
            else CancellationSignal()
        )
        signal.check()
        return self.reply(request, signal)

    def stream(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> Generator[GenerationEvent, None, None]:
        yield GenerationDoneEvent(message=self.invoke(request, context))


class EchoTool(Tool):
    @property
    def id(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Return a value."

    @property
    def display_name(self) -> str:
        return "Echo"

    def tool_definition(self) -> FunctionToolDefinition:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
            },
        }

    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        invocation.cancellation.check()
        return ToolResult(content=str(invocation.arguments["value"]))


def run_agent(
    agent: Agent,
    *,
    max_steps: int,
    messages: Sequence[Message] = (),
    cancellation: CancellationSignal | None = None,
    runs: list[Run] | None = None,
    observe_run: Callable[[Run], None] | None = None,
    listener: Callable[[AgentEvent], None] | None = None,
    coordinator: AgentCoordinator | None = None,
) -> RunResult:
    async def execute() -> RunResult:
        run = agent.start(
            max_steps=max_steps,
            messages=messages,
            cancellation=cancellation,
            coordinator=coordinator,
        )
        if runs is not None:
            runs.append(run)
        if listener is not None:
            run.subscribe(listener)
        if observe_run is not None:
            observe_run(run)
        try:
            return await run.wait()
        finally:
            assert await run.wait_for_idle(timeout=5)

    return asyncio.run(execute())
