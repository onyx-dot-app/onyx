from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import model_validator


class ToolResponse(BaseModel):
    id: str | None = None
    response: Any = None


class ToolCallKickoff(BaseModel):
    tool_name: str
    tool_args: dict[str, Any]


class ToolRunnerResponse(BaseModel):
    tool_run_kickoff: ToolCallKickoff | None = None
    tool_response: ToolResponse | None = None
    tool_message_content: str | list[str | dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_tool_runner_response(self) -> "ToolRunnerResponse":
        fields = ["tool_response", "tool_message_content", "tool_run_kickoff"]
        provided = sum(1 for field in fields if getattr(self, field) is not None)

        if provided != 1:
            raise ValueError(
                "Exactly one of 'tool_response', 'tool_message_content', "
                "or 'tool_run_kickoff' must be provided"
            )

        return self


class ToolCallFinalResult(ToolCallKickoff):
    tool_result: Any = (
        None  # we would like to use JSON_ro, but can't due to its recursive nature
    )


class DynamicSchemaInfo(BaseModel):
    chat_session_id: UUID | None
    message_id: int | None


CHAT_SESSION_ID_PLACEHOLDER = "CHAT_SESSION_ID"
MESSAGE_ID_PLACEHOLDER = "MESSAGE_ID"
