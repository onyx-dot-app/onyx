from collections.abc import Callable
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from onyx.agents.items import ResponseItem, build_response_items
from onyx.agents.tools import AgentTool, ChildRunWait, HumanToolAnswer, PendingToolInput
from onyx.agents.transcript import (
    CompactionCheckpoint,
    OperationSnapshot,
    RunFailure,
    RunStatus,
    messages_for_model,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    GenerationRequestParams,
    Message,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
)


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


class PreparedStep(BaseModel):
    """Decisions captured once and reused when compaction rebuilds a request."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)
    system_prompt: str = ""
    tools: list[AgentTool] = Field(default_factory=list)
    options: GenerationOptions = Field(default_factory=GenerationOptions)
    stall_timeout_s: int | None = Field(default=None, gt=0)
    output_metadata: SerializeAsAny[BaseModel] | None = None
    assemble_messages: Callable[[list[Message]], list[Message]] | None = None

    def generation_request(self, messages: list[Message]) -> GenerationRequest:
        history = [message.model_copy(deep=True) for message in messages]
        return GenerationRequest(
            messages=messages_for_model(
                self.assemble_messages(history) if self.assemble_messages else history
            ),
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


class RunProgress(BaseModel):
    """Saved execution position; message indices refer to the run's recorded output."""

    step_index: int = 0
    step_limit: int = Field(gt=0)
    action: RunAction = RunAction.PREPARE
    message_index: int | None = None
    options: GenerationOptions | None = None
    tools: list[ToolDefinition] = Field(default_factory=list)
    previous_message_index: int | None = None
    previous_options: GenerationOptions | None = None
    finalized_tools: int = 0
    feature_state: SerializeAsAny[BaseModel] | None = None
    pending_tool_calls: dict[str, PendingToolInput | ChildRunWait] = Field(
        default_factory=dict
    )
    human_tool_answers: dict[str, HumanToolAnswer] = Field(default_factory=dict)
    child_run_ids: list[str] = Field(default_factory=list)
    observed_child_run_ids: list[str] = Field(default_factory=list)
    outcome: RunStatus | None = None


class RunState(BaseModel):
    """One run's input, output, and progress; Run.snapshot() returns an isolated copy.

    Operation indices address messages; input_messages is a separate prefix.
    """

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
    messages: list[Message]
    operations: list[OperationSnapshot] = Field(default_factory=list)
    answer_message_index: int | None = None
    child_runs: list["RunState"] = Field(default_factory=list)
    request_params: GenerationRequestParams | None = None
    failure: RunFailure | None = None
    checkpoint: CompactionCheckpoint | None = None

    @property
    def items(self) -> list[ResponseItem]:
        return build_response_items(
            self.run_id,
            self.messages,
            self.operations,
            answer_message_index=self.answer_message_index,
        )


class ExecutionCheckpoint(BaseModel):
    """Run progress and the conversation history preceding its input."""

    model_config = ConfigDict(extra="forbid")
    agent_state: AgentState
    run_state: RunState
