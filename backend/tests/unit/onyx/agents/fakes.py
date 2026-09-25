"""Run the chat adapter through model streaming, tools, and packet rendering."""

from collections.abc import Callable, Generator, Iterator, Sequence
from typing import Any

from onyx.agents.agent_coordination import (
    AgentCoordinator,
    AgentDirectory,
    RunOwnership,
    RunStore,
)
from onyx.agents.events import AgentEvent
from onyx.agents.execution_records import RunStatus
from onyx.agents.models import AgentInfo, RunResult, RunState
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM, GenerationContext, LLMConfig
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
    ToolDefinition,
    ToolResult,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.tools.interface import Tool, ToolContext


class FakeAgentDirectory(AgentDirectory):
    def __init__(
        self,
        *,
        lookup_agent: Callable[[str, str], AgentInfo | None] | None = None,
        restore_agent: Callable[[str, str], Agent] | None = None,
        read_run: Callable[[str, str], RunState | None] | None = None,
        read_run_status: Callable[[str, str], RunStatus] | None = None,
        cancel_run: Callable[[str, str], None] | None = None,
    ) -> None:
        self._lookup_agent = lookup_agent
        self._restore_agent = restore_agent
        self._read_run = read_run
        self._read_run_status = read_run_status
        self._cancel_run = cancel_run

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        return self._lookup_agent(agent_id, parent_id) if self._lookup_agent else None

    def restore_agent(self, agent_id: str, parent_id: str) -> Agent:
        if self._restore_agent is None:
            raise ValueError("Agent restoration is unavailable")
        return self._restore_agent(agent_id, parent_id)

    def read_run(self, run_id: str, parent_id: str) -> RunState | None:
        return self._read_run(run_id, parent_id) if self._read_run else None

    def read_run_status(self, run_id: str, parent_id: str) -> RunStatus:
        if self._read_run_status is not None:
            return self._read_run_status(run_id, parent_id)
        state = self.read_run(run_id, parent_id)
        if state is None:
            raise ValueError("Run is unavailable")
        return state.status

    def cancel_run(self, run_id: str, parent_id: str) -> None:
        if self._cancel_run is None:
            raise ValueError("Remote run cancellation is unavailable")
        self._cancel_run(run_id, parent_id)


class FakeRunStore(RunStore):
    def __init__(self, *, save: Callable[[Run], None]) -> None:
        self._save = save

    def save(self, run: Run) -> None:
        self._save(run)


class FakeRunOwnership(RunOwnership):
    def __init__(
        self,
        *,
        register: Callable[[Run], None] | None = None,
        release: Callable[[str], None] | None = None,
        abort_start: Callable[[str], None] | None = None,
    ) -> None:
        self._register = register
        self._release = release
        self._abort_start = abort_start

    def register(self, run: Run) -> None:
        if self._register is not None:
            self._register(run)

    def release(self, run_id: str) -> None:
        if self._release is not None:
            self._release(run_id)

    def abort_start(self, run_id: str) -> None:
        if self._abort_start is not None:
            self._abort_start(run_id)


class ScriptedLLM(LitellmLLM):
    def __init__(self, steps: list[Delta], max_input_tokens: int = 4096) -> None:
        self.max_input_tokens = max_input_tokens
        self.steps = iter(steps)
        self.requests: list[dict[str, Any]] = []

    def redact_error(self, text: str) -> str:
        return text

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="test-model",
            max_input_tokens=self.max_input_tokens,
            temperature=0,
        )

    def stream_raw(
        self, prompt: LanguageModelInput, *args: Any, **kwargs: Any
    ) -> Iterator[ModelResponseStream]:
        assert not args
        self.requests.append({"prompt": prompt, **kwargs})
        yield ModelResponseStream(
            id="test", created="1", choice=StreamingChoice(delta=next(self.steps))
        )


class FakeModelClient(LLM):
    """Canonical client for deterministic runtime tests."""

    def __init__(
        self, reply: Callable[[GenerationRequest, CancellationSignal], AssistantMessage]
    ) -> None:
        self.reply = reply

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
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

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
            },
        )

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
    def execute() -> RunResult:
        run = agent.start(
            max_steps=max_steps,
            messages=messages,
            cancellation=cancellation,
            coordinator=coordinator,
            on_event=listener,
        )
        if runs is not None:
            runs.append(run)
        if observe_run is not None:
            observe_run(run)
        try:
            return run.result()
        finally:
            assert run.wait_for_idle(timeout=5)

    return execute()
