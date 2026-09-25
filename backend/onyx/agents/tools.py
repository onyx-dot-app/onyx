"""Executable tools and their invocation-scoped services."""

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from enum import Enum
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue, SerializeAsAny, model_validator

from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import Message, ToolDefinition, ToolResult

if TYPE_CHECKING:
    from onyx.agents.coordination import AgentInfo
    from onyx.agents.models import RunResult, RunState
    from onyx.agents.runtime import Agent


DEFAULT_AGENT_WAIT_SECONDS = 60.0


class AgentLifetime(str, Enum):
    FOREGROUND = "foreground"
    BACKGROUND = "background"


class InputMode(str, Enum):
    EXECUTE = "execute"
    RESULT = "result"


class InputDecision(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    RESULT = "result"


class PendingToolInput(BaseModel):
    """Release the tool worker until an identified answer permits execution or supplies output."""

    kind: Literal["input"] = "input"
    request_id: str
    prompt: str
    mode: InputMode


class HumanToolAnswer(BaseModel):
    """A human approval, denial, or supplied result for a pending tool input request."""

    request_id: str
    decision: InputDecision
    result: ToolResult | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "HumanToolAnswer":
        if (self.decision == InputDecision.RESULT) != (self.result is not None):
            raise ValueError("Only a result answer requires a tool result")
        return self


class ChildRunWait(BaseModel):
    """Complete a delegation call when these child runs reach terminal output."""

    kind: Literal["children"] = "children"
    run_ids: list[str]


ToolOutcome = ToolResult | PendingToolInput | ChildRunWait


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
        restoration_config: BaseModel | None = None,
        lifetime: AgentLifetime = AgentLifetime.FOREGROUND,
    ) -> SpawnResult: ...

    def start_run(
        self,
        agent_id: str,
        *,
        max_steps: int,
        messages: Sequence[Message],
        lifetime: AgentLifetime = AgentLifetime.FOREGROUND,
    ) -> str: ...

    def wait_run(
        self, run_id: str, *, timeout: float = DEFAULT_AGENT_WAIT_SECONDS
    ) -> "RunResult | None": ...

    def cancel_run(self, run_id: str) -> None: ...

    def add_completion_cleanup(
        self, run_id: str, callback: Callable[[], None]
    ) -> Future[None]: ...

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
    """An executable SDK tool with application dependencies bound into its callbacks.

    Optional merge_arguments combines compatible calls into one execution. Such tools
    must return ToolResult; each original call receives the pooled result.
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, JsonValue],
        execute: Callable[[ToolInvocation], ToolOutcome],
        complete_children: Callable[[ToolInvocation, list["RunState"]], ToolResult]
        | None = None,
        execution_mode: ToolExecutionMode = ToolExecutionMode.PARALLEL,
        merge_arguments: Callable[
            [dict[str, JsonValue], dict[str, JsonValue]], dict[str, JsonValue] | None
        ]
        | None = None,
    ) -> None:
        self.definition = ToolDefinition(
            name=name, description=description, parameters=parameters
        )
        self.execute = execute
        self.complete_children = complete_children
        self.execution_mode = execution_mode
        self.merge_arguments = merge_arguments

    def snapshot(self) -> "AgentTool":
        definition = self.definition.model_copy(deep=True)
        return AgentTool(
            name=definition.name,
            description=definition.description,
            parameters=definition.parameters,
            execute=self.execute,
            complete_children=self.complete_children,
            execution_mode=self.execution_mode,
            merge_arguments=self.merge_arguments,
        )

    @property
    def name(self) -> str:
        return self.definition.name
