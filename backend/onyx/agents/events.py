"""Agent execution, generation updates, and tool execution events."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from onyx.agents.items import ResponseItem, build_response_items
from onyx.agents.tools import ToolProgress
from onyx.agents.transcript import OperationSnapshot, RunStatus
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationErrorEvent,
    GenerationEvent,
    ToolCall,
    ToolResult,
)


class AgentEventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    MESSAGE_START = "message_start"
    MESSAGE_UPDATE = "message_update"
    MESSAGE_END = "message_end"
    TOOL_START = "tool_start"
    TOOL_UPDATE = "tool_update"
    TOOL_END = "tool_end"


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _AgentEvent(_Event):
    agent_id: str | None = None
    run_id: str
    parent_run_id: str | None = None
    parent_tool_call_id: str | None = None
    parent_message_id: str | None = None


class AgentStartEvent(_AgentEvent):
    type: Literal[AgentEventType.AGENT_START] = AgentEventType.AGENT_START


class AgentEndEvent(_AgentEvent):
    answer_message_id: str | None = None
    type: Literal[AgentEventType.AGENT_END] = AgentEventType.AGENT_END
    outcome: Literal[
        RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
    ]


class MessageStartEvent(_AgentEvent):
    type: Literal[AgentEventType.MESSAGE_START] = AgentEventType.MESSAGE_START
    step_index: int = Field(ge=0)
    metadata: SerializeAsAny[BaseModel] | None = None


class MessageUpdateEvent(_AgentEvent):
    type: Literal[AgentEventType.MESSAGE_UPDATE] = AgentEventType.MESSAGE_UPDATE
    step_index: int = Field(ge=0)
    generation_event: GenerationEvent

    @property
    def items(self) -> list[ResponseItem]:
        return build_response_items(
            self.run_id,
            [self.generation_event.message],
            [
                OperationSnapshot(
                    step_index=self.step_index,
                    message_index=0,
                    status=(
                        RunStatus.COMPLETE
                        if isinstance(self.generation_event, GenerationDoneEvent)
                        else RunStatus.ERROR
                        if isinstance(self.generation_event, GenerationErrorEvent)
                        else RunStatus.RUNNING
                    ),
                )
            ],
            step_offset=self.step_index,
        )


class MessageEndEvent(_AgentEvent):
    type: Literal[AgentEventType.MESSAGE_END] = AgentEventType.MESSAGE_END
    step_index: int = Field(ge=0)
    message: AssistantMessage

    @property
    def items(self) -> list[ResponseItem]:
        return build_response_items(
            self.run_id,
            [self.message],
            [
                OperationSnapshot(
                    step_index=self.step_index,
                    message_index=0,
                    status=RunStatus.COMPLETE,
                )
            ],
            step_offset=self.step_index,
        )


class ToolStartEvent(_AgentEvent):
    type: Literal[AgentEventType.TOOL_START] = AgentEventType.TOOL_START
    step_index: int = Field(ge=0)
    tool_call: ToolCall


class ToolResultEvent(_AgentEvent):
    step_index: int = Field(ge=0)
    tool_call: ToolCall
    result: ToolResult


class ToolUpdateEvent(_AgentEvent):
    type: Literal[AgentEventType.TOOL_UPDATE] = AgentEventType.TOOL_UPDATE
    step_index: int = Field(ge=0)
    tool_call: ToolCall
    progress: ToolProgress


class ToolEndEvent(ToolResultEvent):
    type: Literal[AgentEventType.TOOL_END] = AgentEventType.TOOL_END


AgentEvent = Annotated[
    AgentStartEvent
    | AgentEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolStartEvent
    | ToolUpdateEvent
    | ToolEndEvent,
    Field(discriminator="type"),
]
