"""Executable tools and their invocation-scoped services."""

from collections.abc import Callable, Collection, Mapping, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializeAsAny,
    model_validator,
)

from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    Message,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
)

if TYPE_CHECKING:
    from onyx.agents.concurrency import ExecutionWork
    from onyx.agents.models import (
        AgentInfo,
        AgentMessageReceipt,
        MessageDelivery,
        RunState,
    )
    from onyx.agents.runtime import Agent


class AgentLifetime(str, Enum):
    """Foreground children share parent cancellation and completion ownership."""

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
    # The run's ToolApprovals opened the request; only that owner answers or
    # withdraws it. The runtime sets it.
    approval: bool = False
    # How the requester names the action, for display.
    display_name: str | None = None


class HumanToolAnswer(BaseModel):
    """A human approval, denial, or supplied result for a pending tool input request.

    A denial can carry the result the model sees in place of the default one.
    """

    request_id: str
    decision: InputDecision
    result: ToolResult | None = None
    # A standing approval also approves later calls of the same action; the
    # application that answers applies it to those calls.
    standing: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> "HumanToolAnswer":
        if self.decision == InputDecision.RESULT and self.result is None:
            raise ValueError("A result answer requires a tool result")
        if self.decision == InputDecision.APPROVE and self.result is not None:
            raise ValueError("An approval cannot supply a tool result")
        if self.standing and self.decision != InputDecision.APPROVE:
            raise ValueError("Only an approval can be standing")
        return self


class ChildRunWait(BaseModel):
    """Complete a delegation call when these child runs reach terminal output."""

    kind: Literal["children"] = "children"
    run_ids: list[str]


class NestedInputRequest(BaseModel):
    """An input request that a call of the run waits for, with the place of
    the call that shows it.

    `nested_call` is the call that a tool makes for the model, such as a
    program's; `tool_call` is then the call whose tool made it, or an earlier
    call of the same tool. It is None when `tool_call` itself waits.
    """

    message_id: str
    step_index: int
    tool_call: ToolCall
    nested_call: ToolCall | None
    request: PendingToolInput


class NestedInputWait(BaseModel):
    """Continue a call once every request of the calls that its tool made for
    the model has an answer; `AgentTool.resume_with_input` continues it."""

    kind: Literal["nested_input"] = "nested_input"
    requests: list[NestedInputRequest] = Field(min_length=1)


class NestedInputAnswer(BaseModel):
    request: NestedInputRequest
    answer: HumanToolAnswer


ToolOutcome = ToolResult | PendingToolInput | ChildRunWait | NestedInputWait


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
        total_timeout_s: float | None = None,
        lifetime: AgentLifetime = AgentLifetime.FOREGROUND,
    ) -> SpawnResult: ...

    def send_message(
        self,
        agent_id: str,
        *,
        message: str,
        delivery: "Literal[MessageDelivery.SEND, MessageDelivery.QUEUE]" = ...,
        max_steps: int,
        total_timeout_s: float | None = None,
    ) -> "AgentMessageReceipt": ...

    @property
    def agent_id(self) -> str:
        """The calling agent."""
        ...

    def discover_agents(self) -> list["AgentInfo"]:
        """The visible agent tree, including the root and the caller."""
        ...

    def interrupt_agent(self, agent_id: str) -> "AgentInfo | None":
        """Cancel one agent's active run; the run reports no result.

        Returns None for the caller, the root, or an agent that is not visible.
        """
        ...


class ToolProgress(BaseModel):
    """Tool progress with typed details that define snapshot or delta semantics."""

    content: str = ""
    details: SerializeAsAny[BaseModel] | None = None


ToolUpdate = Callable[[ToolProgress], None]


class BeforeToolCallFailed(BaseException):
    """The run's before_tool_call hook raised for a call that a tool made for the
    model, such as a program's tool call.

    A BaseException, so that neither the tool's own error handling nor a program
    can catch it and go on. The tool lets it leave `execute`, and the run fails
    with `error`, as it does when the hook raises for a direct call.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


class NestedCallGate(Protocol):
    """Decides the calls that a tool makes for the model, such as a program's
    tool calls, as the run decides its direct calls: the before_tool_call hook,
    then the user's approval.

    A request that the gate returns is open: the run shows it at once and saves
    it with its progress. The call does not block on it. The tool returns it in
    a `NestedInputWait`, which the run saves and answers, or withdraws it. A
    request that neither holds stays open while the run suspends; its answer
    goes to `AgentTool.continue_open_input`. Open requests end with the run.
    An approved request runs its call. Raises BeforeToolCallFailed when the
    hook or the approval gate raises.
    """

    def decide(self, call: ToolCall) -> ToolResult | NestedInputRequest | None:
        """A result that replaces the call, a request that the call waits for,
        or None to run it."""
        ...

    def withdraw(self, request: NestedInputRequest) -> None:
        """End an open request whose call stopped waiting without an answer,
        for example because its program ended."""
        ...


class ToolInvocation:
    """Tool inputs and runtime services.

    The update callback captures progress before returning; tools may then mutate
    their local data. Callbacks that retain updates must take an isolated copy.
    """

    def __init__(
        self,
        *,
        call_id: str,
        arguments: dict[str, JsonValue],
        call_index: int = 0,
        cancellation: CancellationSignal,
        update: ToolUpdate,
        messages: Sequence[Message] = (),
        recorded_results: Sequence[ToolResultMessage] = (),
        agents: AgentControl | None = None,
        trace_metadata: Mapping[str, JsonValue] | None = None,
        nested_calls: NestedCallGate | None = None,
        run_work: "ExecutionWork | None" = None,
    ) -> None:
        self.call_id = call_id
        self.call_index = call_index
        self.arguments = arguments
        self.cancellation = cancellation
        self.update = update
        # The model's view of the conversation, after compaction, without result
        # details. Read only.
        self.messages = messages
        # Every recorded tool result of the conversation before this call, with
        # details and without compaction, oldest first: earlier steps, then this
        # step's completed results in call order. For state derived from the
        # whole conversation. Read only.
        self.recorded_results = recorded_results
        # Attributes of the call's tracing span.
        self.trace_metadata = trace_metadata
        # Decides the calls that the tool makes for the model, such as a
        # program's tool calls; None when no hook or approval decides calls.
        self.nested_calls = nested_calls
        # The run's work, which work that outlives this call joins; see
        # "Suspend and accept input" in agents/README.md for how it holds the run.
        self.run_work = run_work
        self._agents = agents

    @property
    def agents(self) -> AgentControl:
        if self._agents is None:
            raise RuntimeError("Agent coordination was not supplied for this run")
        return self._agents


class ToolExecutionMode(str, Enum):
    """SEQUENTIAL orders calls to the same tool name, or the same
    sequence_group, within a model step."""

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class AgentTool:
    """An executable SDK tool with application dependencies bound into its callbacks.

    Optional merge_arguments combines compatible calls into one execution. Such tools
    must return ToolResult; each original call receives the pooled result.

    A call that a lost execution owner left running runs again on restore, unless
    interrupted_result is set; then that result is saved as the call's result
    instead, with status error when it is an error.
    """

    def __init__(
        self,
        *,
        definition: ToolDefinition,
        execute: Callable[[ToolInvocation], ToolOutcome],
        result_from_children: Callable[[ToolInvocation, list["RunState"]], ToolResult]
        | None = None,
        resume_with_input: Callable[
            [ToolInvocation, list[NestedInputAnswer]], ToolOutcome
        ]
        | None = None,
        continue_open_input: Callable[
            [ToolInvocation, list[NestedInputAnswer]], Collection[str]
        ]
        | None = None,
        execution_mode: ToolExecutionMode = ToolExecutionMode.PARALLEL,
        sequence_group: str | None = None,
        merge_arguments: Callable[
            [dict[str, JsonValue], dict[str, JsonValue]], dict[str, JsonValue] | None
        ]
        | None = None,
        interrupted_result: ToolResult | None = None,
        display_name: str | None = None,
        approval_required: Collection[str] = (),
        inner_call_hint: Callable[[str], str | None] | None = None,
    ) -> None:
        self.definition = definition
        self.execute = execute
        self.result_from_children = result_from_children
        # Continues a call that returned NestedInputWait, with the answers to
        # its requests in their order; it does not repeat `execute`.
        self.resume_with_input = resume_with_input
        # Continues the calls that the tool made for the model whose open
        # requests have answers, such as a background program's, with the
        # answers of the requests that `invocation`'s call opened. Returns
        # the IDs of the requests it took; the run ends those. The others
        # stay open, and the run offers them again later.
        self.continue_open_input = continue_open_input
        self.execution_mode = execution_mode
        self.sequence_group = sequence_group
        self.merge_arguments = merge_arguments
        self.interrupted_result = interrupted_result
        self.display_name = display_name
        # Names of calls, this tool's own or those it makes for the model, that
        # wait for the user's approval before they run.
        self.approval_required = frozenset(approval_required)
        # For a call of a name that is no offered tool: how to call it through
        # this tool, when it is one of the tools that this tool's calls make.
        self.inner_call_hint = inner_call_hint

    def snapshot(self) -> "AgentTool":
        definition = self.definition.model_copy(deep=True)
        return AgentTool(
            definition=definition,
            execute=self.execute,
            result_from_children=self.result_from_children,
            resume_with_input=self.resume_with_input,
            continue_open_input=self.continue_open_input,
            execution_mode=self.execution_mode,
            sequence_group=self.sequence_group,
            merge_arguments=self.merge_arguments,
            interrupted_result=self.interrupted_result,
            display_name=self.display_name,
            approval_required=self.approval_required,
            inner_call_hint=self.inner_call_hint,
        )

    @property
    def name(self) -> str:
        return self.definition.name
