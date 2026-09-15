"""Versioned canonical output, independent of packets and application objects."""

from enum import Enum
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator

from onyx.llm.models import AssistantMessage, Message, ToolCall, ToolResultMessage
from onyx.utils.logger import setup_logger

logger = setup_logger()


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    LIMIT = "limit"
    CANCELLED = "cancelled"
    ERROR = "error"


class CompactionCheckpoint(BaseModel):
    summary: str
    covered_count: int = Field(gt=0)
    covered_digest: str


class OperationSnapshot(BaseModel):
    step_index: int = Field(validation_alias=AliasChoices("step_index", "turn"))
    message_index: int
    tool_call_id: str | None = None
    status: RunStatus


class AgentTranscript(BaseModel):
    """Storage-safe run record; operation indices address messages, excluding input."""

    input_messages: list[Message] = Field(default_factory=list)
    version: Literal[1, 2] = 2
    run_id: str | None = None
    parent_run_id: str | None = None
    parent_tool_call_id: str | None = None
    parent_message_id: str | None = None
    operations: list[OperationSnapshot] = Field(default_factory=list)
    children: list["AgentTranscript"] = Field(default_factory=list)
    status: RunStatus
    messages: list[Message]
    checkpoint: CompactionCheckpoint | None = None

    @model_validator(mode="after")
    def reject_application_details(self) -> "AgentTranscript":
        if any(
            isinstance(message, ToolResultMessage) and message.details is not None
            for message in [*self.input_messages, *self.messages]
        ):
            raise ValueError(
                "Application details do not belong in a durable transcript"
            )
        return self


def completed_tool_call_ids(messages: list[Message], assistant_index: int) -> set[str]:
    result_ids: set[str] = set()
    for index in range(assistant_index + 1, len(messages)):
        following = messages[index]
        if not isinstance(following, ToolResultMessage):
            break
        result_ids.add(following.tool_call_id)
    return result_ids


def messages_for_model(messages: list[Message]) -> list[Message]:
    """Exclude unfinished tool calls while preserving recorded partial output."""
    replay: list[Message] = []
    accepted: set[str] = set()
    for index, message in enumerate(messages):
        if isinstance(message, AssistantMessage):
            result_ids = completed_tool_call_ids(messages, index)
            accepted = {call.id for call in message.tool_calls if call.id in result_ids}
            copy = message.model_copy(deep=True)
            copy.content = [
                part
                for part in copy.content
                if not isinstance(part, ToolCall) or part.id in accepted
            ]
            if copy.content:
                replay.append(copy)
            else:
                logger.debug(
                    "Omitting an unfinished empty assistant message from model context"
                )
        elif isinstance(message, ToolResultMessage):
            if message.tool_call_id in accepted:
                replay.append(message.model_copy(deep=True))
                accepted.remove(message.tool_call_id)
            else:
                logger.debug(
                    "Omitting an incomplete tool result from model context: %s",
                    message.tool_call_id,
                )
        else:
            accepted.clear()
            replay.append(message.model_copy(deep=True))
    return replay
