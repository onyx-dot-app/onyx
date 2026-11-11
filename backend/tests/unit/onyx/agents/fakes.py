"""Run the chat adapter through model streaming, tools, and packet rendering."""

from collections.abc import (
    Callable,
    Generator,
    Iterable,
    Iterator,
    Sequence,
)
from typing import Any, override
from uuid import uuid4

from onyx.agents.agent_coordination import (
    AgentCoordinator,
    AgentDirectory,
    RunOwnership,
    RunStore,
)
from onyx.agents.events import AgentEvent
from onyx.agents.models import (
    AgentInfo,
    AgentMessageReceipt,
    AgentMessageRequest,
    RunResult,
    RunState,
    RunStatus,
    StepRecord,
)
from onyx.agents.runtime import Agent, AgentBusy, Run
from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM, GenerationContext, LLMConfig
from onyx.llm.model_request import ChatCompletionMessage
from onyx.llm.model_response import Delta, ModelResponseStream, StreamingChoice
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationRequest,
    GenerationStartEvent,
    Message,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolDefinition,
    ToolResult,
    UserMessage,
    apply_generation_event,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.tools.interface import Tool
from onyx.tools.models import CodeModeExposure, ToolContext


class FakeAgentDirectory(AgentDirectory):
    def __init__(
        self,
        *,
        list_agents: Callable[[], list[AgentInfo]] | None = None,
        lookup_agent: Callable[[str, str], AgentInfo | None] | None = None,
        restore_agent: Callable[[str, str], Agent] | None = None,
        read_run: Callable[[str, str], RunState | None] | None = None,
        read_run_status: Callable[[str, str], RunStatus] | None = None,
        cancel_run: Callable[[str, str], None] | None = None,
    ) -> None:
        self._list_agents = list_agents
        self._lookup_agent = lookup_agent
        self._restore_agent = restore_agent
        self._read_run = read_run
        self._read_run_status = read_run_status
        self._cancel_run = cancel_run

    def list_agents(self) -> list[AgentInfo]:
        return self._list_agents() if self._list_agents else []

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
        receive_inputs: Callable[[Run], list[UserMessage]] | None = None,
        accept_inputs: Callable[[Run, StepRecord], bool] | None = None,
        delegated_runs: Callable[[str], dict[str, RunStatus]] | None = None,
        submit_message: Callable[[AgentMessageRequest], AgentMessageReceipt]
        | None = None,
    ) -> None:
        self._register = register
        self._release = release
        self._abort_start = abort_start
        self._receive_inputs = receive_inputs
        self._accept_inputs = accept_inputs
        self._delegated_runs = delegated_runs
        self._submit_message = submit_message

    @override
    def reserve_run_id(
        self,
        *,
        agent: AgentInfo,
        messages: Sequence[Message],
        previous_run_id: str | None,
        parent_run_id: str | None,
        parent_message_id: str | None,
        parent_tool_call_id: str | None,
    ) -> str:
        return str(uuid4())

    def register(self, run: Run) -> None:
        if self._register is not None:
            self._register(run)

    def release(self, run_id: str) -> None:
        if self._release is not None:
            self._release(run_id)

    def abort_start(self, run_id: str) -> None:
        if self._abort_start is not None:
            self._abort_start(run_id)

    @override
    def receive_inputs(self, run: Run) -> list[UserMessage]:
        return self._receive_inputs(run) if self._receive_inputs else []

    @override
    def accept_inputs(self, run: Run, step: StepRecord) -> bool:
        return self._accept_inputs(run, step) if self._accept_inputs else True

    @override
    def has_unread_inputs(self, run: Run) -> bool:
        return False

    @override
    def delegated_runs(self, parent_id: str) -> dict[str, RunStatus]:
        return self._delegated_runs(parent_id) if self._delegated_runs else {}

    @override
    def withdraw_result(self, run_id: str, parent_id: str) -> None:
        return None

    @override
    def submit_message(self, request: AgentMessageRequest) -> AgentMessageReceipt:
        if self._submit_message is None:
            raise ValueError("Remote messaging is unavailable")
        return self._submit_message(request)


def direct_message_coordinator(
    directory: AgentDirectory | None = None,
) -> AgentCoordinator:
    """Start each addressed run directly; ext-dep `test_run_store.py` covers chat delivery."""

    def submit(request: AgentMessageRequest) -> AgentMessageReceipt:
        run = coordinator.start_message_run(
            request.agent_id,
            spawner_id=request.parent_id,
            messages=[request.message],
            max_steps=request.max_steps,
            deadline_at=None,
            parent_run_id=request.parent_run_id,
            parent_message_id=request.parent_message_id,
            parent_tool_call_id=request.parent_tool_call_id,
        )
        if run is None:
            raise AgentBusy("The previous agent run is still draining")
        return AgentMessageReceipt(id=request.message.id or "", run_id=run.id)

    coordinator = AgentCoordinator(
        directory=directory, ownership=FakeRunOwnership(submit_message=submit)
    )
    return coordinator


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
        self, prompt: list[ChatCompletionMessage], *args: Any, **kwargs: Any
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
        yield from message_events(self.invoke(request, context))


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

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
            },
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
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


def message_events(message: AssistantMessage) -> Iterator[GenerationEvent]:
    yield GenerationStartEvent()
    for index, block in enumerate(message.content):
        if isinstance(block, TextContent):
            yield TextDeltaEvent(content_index=index, text=block.text)
        elif isinstance(block, ThinkingContent):
            yield ThinkingDeltaEvent(
                content_index=index, text=block.text, blocks=block.blocks
            )
        else:
            yield ToolCallStartEvent(
                content_index=index, tool_call_id=block.id, tool_name=block.name
            )
            yield ToolCallEndEvent(
                content_index=index, tool_call=block.model_copy(deep=True)
            )
    yield GenerationDoneEvent(usage=message.usage, stop_reason=message.stop_reason)


def collect_generation(events: Iterable[GenerationEvent]) -> AssistantMessage:
    message = AssistantMessage()
    for event in events:
        apply_generation_event(message, event)
    return message
