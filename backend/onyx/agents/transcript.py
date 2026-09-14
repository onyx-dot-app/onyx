"""Versioned canonical output, independent of packets and application objects."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, model_validator

from onyx.llm.models import Message, ToolResultMessage


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    LIMIT = "limit"
    CANCELLED = "cancelled"
    ERROR = "error"


class AgentTranscript(BaseModel):
    version: Literal[1] = 1
    status: RunStatus
    messages: list[Message]

    @model_validator(mode="after")
    def reject_application_details(self) -> "AgentTranscript":
        if any(
            isinstance(message, ToolResultMessage) and message.details is not None
            for message in self.messages
        ):
            raise ValueError(
                "Application details do not belong in a durable transcript"
            )
        return self
