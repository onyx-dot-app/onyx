"""Executable tools and their invocation-scoped services."""

from collections.abc import Callable, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue, SerializeAsAny

from onyx.agents.transcript import AgentRestorationConfig
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

    def spawn_agent(
        self,
        agent: "Agent",
        *,
        name: str,
        description: str,
        max_steps: int,
        messages: Sequence[Message],
        restoration_config: AgentRestorationConfig | None = None,
    ) -> SpawnResult: ...

    def start_run(
        self, agent_id: str, *, max_steps: int, messages: Sequence[Message]
    ) -> str: ...

    def wait_run(
        self, run_id: str, *, timeout: float = DEFAULT_AGENT_WAIT_SECONDS
    ) -> "RunResult | None": ...

    def cancel_run(self, run_id: str) -> None: ...

    def wait_for_idle(self, run_id: str, *, timeout: float = 1800.0) -> bool: ...

    def add_idle_callback(self, run_id: str, callback: Callable[[], None]) -> None: ...

    def discovery(self) -> list["AgentInfo"]: ...


class ToolProgress(BaseModel):
    """Current partial tool output; each update replaces the previous partial value."""

    content: str = ""
    details: SerializeAsAny[BaseModel] | None = None


ToolUpdate = Callable[[ToolProgress], None]


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
    ) -> None:
        self.call_id = call_id
        self.call_index = call_index
        self.arguments = arguments
        self.cancellation = cancellation
        self.update = update
        self.messages = messages
        self._agents = agents

    @property
    def agents(self) -> AgentControl:
        if self._agents is None:
            raise RuntimeError("Agent coordination was not supplied for this run")
        return self._agents


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
        execute: Callable[[ToolInvocation], ToolResult],
        execution_mode: ToolExecutionMode = ToolExecutionMode.PARALLEL,
    ) -> None:
        self.definition = ToolDefinition(
            name=name, description=description, parameters=parameters
        )
        self.execute = execute
        self.execution_mode = execution_mode

    def snapshot(self) -> "AgentTool":
        definition = self.definition.model_copy(deep=True)
        return AgentTool(
            name=definition.name,
            description=definition.description,
            parameters=definition.parameters,
            execute=self.execute,
            execution_mode=self.execution_mode,
        )

    @property
    def name(self) -> str:
        return self.definition.name
