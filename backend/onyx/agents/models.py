from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from onyx.agents.tools import AgentTool
from onyx.agents.transcript import (
    AgentTranscript,
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
    ToolResultMessage,
)


class AgentStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    index: int = Field(ge=0)
    limit: int = Field(gt=0)

    @property
    def is_last(self) -> bool:
        return self.index + 1 == self.limit


class AgentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[Message] = Field(default_factory=list)
    checkpoint: CompactionCheckpoint | None = None

    def snapshot(self) -> "AgentContext":
        return self.model_copy(deep=True)


class PreparedStep(BaseModel):
    """Decisions captured once and reused when compaction rebuilds a request."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)
    system_prompt: str = ""
    tools: list[AgentTool] = Field(default_factory=list)
    options: GenerationOptions = Field(default_factory=GenerationOptions)
    timeout: int | None = Field(default=None, gt=0)
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
    request: GenerationRequest
    messages: list[Message]


class StepResult(BaseModel):
    step: AgentStep
    message: AssistantMessage
    tool_results: list[ToolResultMessage]
    request: GenerationRequest


class StepInput(BaseModel):
    history: list[Message]
    input_messages: list[Message]
    messages: list[Message]
    step: AgentStep
    previous: StepResult | None = None


class RunResult(BaseModel):
    """Completed output for one run; conversation history remains on Agent.context."""

    run_id: str
    steps: int
    stop_reason: Literal[RunStatus.COMPLETE, RunStatus.LIMIT]
    output: AssistantMessage


class RunSnapshot(BaseModel):
    """One run’s initial input and subsequent messages, including partial work.

    Operation indices address messages; input_messages is a separate prefix.
    """

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
    child_runs: list["RunSnapshot"] = Field(default_factory=list)
    request_params: GenerationRequestParams | None = None
    failure: RunFailure | None = None
    checkpoint: CompactionCheckpoint | None = None

    def transcript(self) -> AgentTranscript:
        input_messages = [
            message.model_copy(deep=True) for message in self.input_messages
        ]
        messages = [message.model_copy(deep=True) for message in self.messages]
        for message in [*input_messages, *messages]:
            message.metadata = None
            if isinstance(message, ToolResultMessage):
                message.details = None
        return AgentTranscript(
            agent_id=self.agent_id,
            previous_run_id=self.previous_run_id,
            run_id=self.run_id,
            parent_run_id=self.parent_run_id,
            parent_tool_call_id=self.parent_tool_call_id,
            parent_message_id=self.parent_message_id,
            operations=[operation.model_copy() for operation in self.operations],
            child_runs=[child.transcript() for child in self.child_runs],
            status=self.status,
            failure=self.failure,
            input_messages=input_messages,
            messages=messages,
            checkpoint=self.checkpoint.model_copy(deep=True)
            if self.checkpoint
            else None,
        )
