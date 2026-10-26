from collections.abc import Callable, Sequence
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SerializeAsAny

from onyx.agents.execution_records import messages_for_model
from onyx.agents.tools import AgentTool, ChildRunWait, HumanToolAnswer, PendingToolInput
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    GenerationRequestParams,
    LLMErrorInfo,
    Message,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
)


class RunStatus(str, Enum):
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETE = "complete"
    LIMIT = "limit"
    CANCELLED = "cancelled"
    ERROR = "error"

    @property
    def is_terminal(self) -> bool:
        return self not in (RunStatus.RUNNING, RunStatus.SUSPENDED)


class ExecutionStatus(str, Enum):
    """State of one generation or tool invocation; running means no terminal outcome yet."""

    RUNNING = "running"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    ERROR = "error"


class RunFailureKind(str, Enum):
    LLM = "llm"
    LLM_TIMEOUT = "llm_timeout"
    LLM_RATE_LIMIT = "llm_rate_limit"
    EXECUTION = "execution"


class RunFailure(BaseModel):
    kind: RunFailureKind
    message: str
    llm_error: LLMErrorInfo | None = None


class ContextBudget(BaseModel):
    input_limit: int = Field(gt=0)
    trigger: int = Field(gt=0)
    recent: int = Field(gt=0)
    summary: int = Field(gt=0)


class CompactionCheckpoint(BaseModel):
    summary: str
    covered_through_message_id: str = Field(min_length=1)


class AgentInfo(BaseModel):
    """Visible identity and latest run status, without conversation content."""

    model_config = ConfigDict(frozen=True)
    id: str
    path: str
    parent_id: str | None
    description: str
    restoration_config: SerializeAsAny[BaseModel] | None
    latest_run_id: str | None = None
    status: RunStatus | None = None


class AgentStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    index: int = Field(ge=0)
    limit: int = Field(gt=0)

    @property
    def is_last(self) -> bool:
        return self.index + 1 == self.limit


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[Message] = Field(default_factory=list)
    checkpoint: CompactionCheckpoint | None = None

    def snapshot(self) -> "AgentState":
        return self.model_copy(deep=True)


class CompactionMetadata(BaseModel):
    """Summary input text and whether a message can anchor a saved summary."""

    compaction_text: str | None = None
    allow_compaction_cutoff: bool = True


class PreparedStep(BaseModel):
    """Decisions captured once and reused when compaction rebuilds a request."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)
    system_prompt: str = ""
    tools: list[AgentTool] = Field(default_factory=list)
    options: GenerationOptions = Field(default_factory=GenerationOptions)
    stall_timeout_s: int | None = Field(default=None, gt=0)
    output_metadata: SerializeAsAny[BaseModel] | None = None
    assemble_messages: Callable[[Sequence[Message]], list[Message]] | None = None

    def generation_request(self, messages: list[Message]) -> GenerationRequest:
        """Build a detached request; assembly must not mutate borrowed history."""
        history = messages
        if self.assemble_messages is not None:
            history = self.assemble_messages(tuple(messages))
        return GenerationRequest(
            messages=messages_for_model(history),
            system_prompt=self.system_prompt,
            tools=[tool.definition.model_copy(deep=True) for tool in self.tools],
            options=self.options.model_copy(deep=True),
        )


class ToolCallContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    step: AgentStep
    call: ToolCall
    options: GenerationOptions
    messages: list[Message]


class StepResult(BaseModel):
    step: AgentStep
    message: AssistantMessage
    tool_results: list[ToolResultMessage]
    options: GenerationOptions


class StepInput(BaseModel):
    """Detached callback input; previous references its matching entries in messages."""

    history: list[Message]
    input_messages: list[Message]
    messages: list[Message]
    step: AgentStep
    previous: StepResult | None = None


class RunResult(BaseModel):
    """Completed output for one run; conversation history remains on Agent.state."""

    run_id: str
    steps: int
    stop_reason: Literal[RunStatus.COMPLETE, RunStatus.LIMIT]
    output: AssistantMessage


class ExecutionRequest(str, Enum):
    """Local scheduling intent; suspension persists until explicit input or resume."""

    NONE = "none"
    WAKE = "wake"
    SUSPEND = "suspend"


class RunAction(str, Enum):
    PREPARE = "prepare"
    TOOLS = "tools"
    AFTER_STEP = "after_step"
    FINISH = "finish"


class ToolExecutionRecord(BaseModel):
    """A tool invocation and its optional result; RunProgress tracks waits and finalizers."""

    model_config = ConfigDict(extra="forbid")

    status: ExecutionStatus
    result: ToolResultMessage | None = None


class StepRecord(BaseModel):
    """One model generation and the executions of its tool calls."""

    model_config = ConfigDict(extra="forbid")

    message: AssistantMessage
    generation_status: ExecutionStatus
    tools: dict[str, ToolExecutionRecord] = Field(default_factory=dict)


def messages_from_steps(steps: list[StepRecord]) -> list[Message]:
    """Return message references in model order, regardless of tool completion order."""
    messages: list[Message] = []
    for step in steps:
        messages.append(step.message)
        for call in step.message.tool_calls:
            execution = step.tools.get(call.id)
            if execution is not None and execution.result is not None:
                messages.append(execution.result)
    return messages


class RunProgress(BaseModel):
    """Saved execution position and unfinished work within the current step."""

    model_config = ConfigDict(extra="forbid")

    step_index: int = 0
    step_limit: int = Field(gt=0)
    # Absolute UTC deadline includes time spent suspended or between execution owners.
    deadline_at: datetime | None = None
    action: RunAction = RunAction.PREPARE
    options: GenerationOptions | None = None
    tools: list[ToolDefinition] = Field(default_factory=list)
    previous_options: GenerationOptions | None = None
    finalized_tools: int = 0
    feature_state: dict[str, JsonValue] | None = None
    pending_tool_calls: dict[str, PendingToolInput | ChildRunWait] = Field(
        default_factory=dict
    )
    human_tool_answers: dict[str, HumanToolAnswer] = Field(default_factory=dict)
    child_run_ids: list[str] = Field(default_factory=list)
    observed_child_run_ids: list[str] = Field(default_factory=list)
    outcome: RunStatus | None = None


class RunState(BaseModel):
    """One run's input, recorded steps, and resumable progress."""

    model_config = ConfigDict(extra="forbid")

    revision: int = 0
    progress: RunProgress | None = None
    input_messages: list[Message] = Field(default_factory=list)
    run_id: str
    agent_id: str | None = None
    previous_run_id: str | None = None
    parent_run_id: str | None = None
    parent_tool_call_id: str | None = None
    parent_message_id: str | None = None
    status: RunStatus
    steps: list[StepRecord] = Field(default_factory=list)
    answer_step_index: int | None = None
    child_runs: list["RunState"] = Field(default_factory=list)
    request_params: GenerationRequestParams | None = None
    failure: RunFailure | None = None
    checkpoint: CompactionCheckpoint | None = None

    @property
    def messages(self) -> list[Message]:
        """Derive model order from steps; the returned messages belong to this state."""
        return messages_from_steps(self.steps)


class ExecutionCheckpoint(BaseModel):
    """Run progress and the conversation history preceding its input."""

    model_config = ConfigDict(extra="forbid")
    agent_state: AgentState
    run_state: RunState
