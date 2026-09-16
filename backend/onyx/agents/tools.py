"""Executable tools and their invocation-scoped services."""

from collections.abc import Awaitable, Callable, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue, SerializeAsAny

from onyx.agents.transcript import AgentConfiguration
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import Message, ToolDefinition, ToolResult

if TYPE_CHECKING:
    from onyx.agents.coordination import AgentInfo
    from onyx.agents.models import RunResult
    from onyx.agents.runtime import Agent


DEFAULT_AGENT_WAIT_SECONDS = 60.0


class SpawnResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    agent_path: str
    run_id: str


class AgentControl(Protocol):
    """Start and observe authorized agent executions."""

    async def spawn_agent(
        self,
        agent: "Agent",
        *,
        name: str,
        description: str,
        max_steps: int,
        messages: Sequence[Message],
        restoration_config: AgentConfiguration | None = None,
    ) -> SpawnResult: ...

    async def start_run(
        self, agent_id: str, *, max_steps: int, messages: Sequence[Message]
    ) -> str: ...

    async def wait_run(
        self, run_id: str, *, timeout: float = DEFAULT_AGENT_WAIT_SECONDS
    ) -> "RunResult | None": ...

    async def cancel_run(self, run_id: str) -> None: ...

    def discovery(self) -> list["AgentInfo"]: ...


class ToolProgress(BaseModel):
    content: str = ""
    details: SerializeAsAny[BaseModel] | None = None


ToolUpdate = Callable[[ToolProgress], None]


class BlockingRunner(Protocol):
    async def __call__[T](
        self, operation: Callable[[], T], *, cleanup: bool = False
    ) -> T: ...


class ToolInvocation:
    def __init__(
        self,
        *,
        call_id: str,
        arguments: dict[str, JsonValue],
        call_index: int = 0,
        cancellation: CancellationSignal,
        update: ToolUpdate,
        messages: Sequence[Message] = (),
        agents: AgentControl | None = None,
        run_blocking: BlockingRunner | None = None,
    ) -> None:
        self.call_id = call_id
        self.call_index = call_index
        self.arguments = arguments
        self.cancellation = cancellation
        self.update = update
        self.messages = messages
        self._agents = agents
        self._run_blocking = run_blocking

    @property
    def agents(self) -> AgentControl:
        if self._agents is None:
            raise RuntimeError("Agent coordination was not supplied for this run")
        return self._agents

    async def run_blocking[T](
        self, operation: Callable[[], T], *, cleanup: bool = False
    ) -> T:
        if self._run_blocking is None:
            raise RuntimeError(
                "Blocking execution requires a runtime-managed tool invocation"
            )
        return await self._run_blocking(operation, cleanup=cleanup)


class ToolExecutionMode(str, Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class AgentTool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, JsonValue],
        execute: Callable[[ToolInvocation], ToolResult] | None = None,
        execute_async: Callable[[ToolInvocation], Awaitable[ToolResult]] | None = None,
        execution_mode: ToolExecutionMode = ToolExecutionMode.PARALLEL,
    ) -> None:
        if (execute is None) == (execute_async is None):
            raise ValueError("A tool requires exactly one execution function")
        self.definition = ToolDefinition(
            name=name, description=description, parameters=parameters
        )
        self.execute = execute
        self.execute_async = execute_async
        self.execution_mode = execution_mode

    def snapshot(self) -> "AgentTool":
        definition = self.definition.model_copy(deep=True)
        return AgentTool(
            name=definition.name,
            description=definition.description,
            parameters=definition.parameters,
            execute=self.execute,
            execute_async=self.execute_async,
            execution_mode=self.execution_mode,
        )

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def description(self) -> str:
        return self.definition.description

    @property
    def parameters(self) -> dict[str, JsonValue]:
        return self.definition.parameters
