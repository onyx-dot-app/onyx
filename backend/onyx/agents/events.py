"""Agent execution, generation updates, and tool execution events."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from onyx.agents.execution_records import RunStatus
from onyx.agents.tools import PendingToolInput, ToolProgress
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    ToolCall,
    ToolResult,
)


class AgentEventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_SUSPENDED = "agent_suspended"
    INPUT_REQUIRED = "input_required"
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


class AgentSuspendedEvent(_AgentEvent):
    type: Literal[AgentEventType.AGENT_SUSPENDED] = AgentEventType.AGENT_SUSPENDED


class InputRequiredEvent(_AgentEvent):
    type: Literal[AgentEventType.INPUT_REQUIRED] = AgentEventType.INPUT_REQUIRED
    tool_call_id: str
    request: PendingToolInput


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


class MessageEndEvent(_AgentEvent):
    type: Literal[AgentEventType.MESSAGE_END] = AgentEventType.MESSAGE_END
    step_index: int = Field(ge=0)
    message: AssistantMessage


class ToolStartEvent(_AgentEvent):
    type: Literal[AgentEventType.TOOL_START] = AgentEventType.TOOL_START
    step_index: int = Field(ge=0)
    tool_call: ToolCall


class ToolUpdateEvent(_AgentEvent):
    type: Literal[AgentEventType.TOOL_UPDATE] = AgentEventType.TOOL_UPDATE
    step_index: int = Field(ge=0)
    tool_call: ToolCall
    progress: ToolProgress


class ToolEndEvent(_AgentEvent):
    type: Literal[AgentEventType.TOOL_END] = AgentEventType.TOOL_END
    step_index: int = Field(ge=0)
    tool_call: ToolCall
    result: ToolResult


AgentEvent = Annotated[
    AgentStartEvent
    | AgentSuspendedEvent
    | InputRequiredEvent
    | AgentEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolStartEvent
    | ToolUpdateEvent
    | ToolEndEvent,
    Field(discriminator="type"),
]
