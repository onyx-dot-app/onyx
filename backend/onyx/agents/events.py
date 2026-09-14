"""Agent execution, generation updates, and tool execution events."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.transcript import RunStatus
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    Message,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)


class AgentEventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    INPUT_CONSUMED = "input_consumed"
    TURN_START = "turn_start"
    MESSAGE_START = "message_start"
    MESSAGE_UPDATE = "message_update"
    MESSAGE_END = "message_end"
    TURN_END = "turn_end"
    TOOL_START = "tool_start"
    TOOL_UPDATE = "tool_update"
    TOOL_END = "tool_end"


class InputKind(str, Enum):
    STEER = "steer"
    FOLLOW_UP = "follow_up"


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _AgentEvent(_Event):
    run_id: str
    parent_run_id: str | None = None
    parent_tool_call_id: str | None = None


class AgentStartEvent(_AgentEvent):
    type: Literal[AgentEventType.AGENT_START] = AgentEventType.AGENT_START


class AgentEndEvent(_AgentEvent):
    type: Literal[AgentEventType.AGENT_END] = AgentEventType.AGENT_END
    outcome: Literal[
        RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
    ]


class InputConsumedEvent(_AgentEvent):
    type: Literal[AgentEventType.INPUT_CONSUMED] = AgentEventType.INPUT_CONSUMED
    turn: int = Field(ge=0)
    input_id: str
    kind: InputKind


class TurnStartEvent(_AgentEvent):
    type: Literal[AgentEventType.TURN_START] = AgentEventType.TURN_START
    turn: int = Field(ge=0)
    input_messages: list[Message] = Field(default_factory=list)


class MessageStartEvent(_AgentEvent):
    type: Literal[AgentEventType.MESSAGE_START] = AgentEventType.MESSAGE_START
    turn: int = Field(ge=0)


class MessageUpdateEvent(_AgentEvent):
    type: Literal[AgentEventType.MESSAGE_UPDATE] = AgentEventType.MESSAGE_UPDATE
    turn: int = Field(ge=0)
    generation_event: GenerationEvent

    @property
    def message(self) -> AssistantMessage:
        return self.generation_event.message


class MessageEndEvent(_AgentEvent):
    type: Literal[AgentEventType.MESSAGE_END] = AgentEventType.MESSAGE_END
    turn: int = Field(ge=0)
    message: AssistantMessage


class TurnEndEvent(_AgentEvent):
    type: Literal[AgentEventType.TURN_END] = AgentEventType.TURN_END
    turn: int = Field(ge=0)
    message: AssistantMessage
    tool_results: list[ToolResultMessage]


class ToolStartEvent(_AgentEvent):
    type: Literal[AgentEventType.TOOL_START] = AgentEventType.TOOL_START
    turn: int = Field(ge=0)
    tool_call: ToolCall


class ToolResultEvent(_AgentEvent):
    turn: int = Field(ge=0)
    tool_call: ToolCall
    result: ToolResult


class ToolUpdateEvent(ToolResultEvent):
    type: Literal[AgentEventType.TOOL_UPDATE] = AgentEventType.TOOL_UPDATE


class ToolEndEvent(ToolResultEvent):
    type: Literal[AgentEventType.TOOL_END] = AgentEventType.TOOL_END


AgentEvent = Annotated[
    AgentStartEvent
    | AgentEndEvent
    | InputConsumedEvent
    | TurnStartEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | TurnEndEvent
    | ToolStartEvent
    | ToolUpdateEvent
    | ToolEndEvent,
    Field(discriminator="type"),
]
