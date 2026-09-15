"""Executable tools and their invocation-scoped services."""

from collections.abc import Awaitable, Callable, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, JsonValue, SerializeAsAny

from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import Message, ToolDefinition, ToolResult

if TYPE_CHECKING:
    from onyx.agents.runtime import Agent, RunResult


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
        run_child: Callable[["Agent", int, Sequence[Message]], Awaitable["RunResult"]]
        | None = None,
        run_blocking: BlockingRunner | None = None,
    ) -> None:
        self.call_id = call_id
        self.call_index = call_index
        self.arguments = arguments
        self.cancellation = cancellation
        self.update = update
        self.messages = messages
        self._run_child = run_child
        self._run_blocking = run_blocking

    def run_child(
        self, agent: "Agent", *, max_steps: int, messages: Sequence[Message] = ()
    ) -> Awaitable["RunResult"]:
        if self._run_child is None:
            raise RuntimeError("Child execution requires an active agent runtime")
        self.cancellation.check()
        return self._run_child(agent, max_steps, messages)

    async def run_blocking[T](
        self, operation: Callable[[], T], *, cleanup: bool = False
    ) -> T:
        if self._run_blocking is None:
            raise RuntimeError("Blocking coordination requires an active agent runtime")
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

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def description(self) -> str:
        return self.definition.description

    @property
    def parameters(self) -> dict[str, JsonValue]:
        return self.definition.parameters
