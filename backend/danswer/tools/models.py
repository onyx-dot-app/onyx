from typing import Any

from pydantic import BaseModel
from pydantic import root_validator


class ToolResponse(BaseModel):
    id: str | None = None
    response: Any


class ToolCallKickoff(BaseModel):
    tool_name: str
    tool_args: dict[str, Any]


class ToolRunnerResponse(BaseModel):
    tool_run_kickoff: ToolCallKickoff | None = None
    tool_response: ToolResponse | None = None
    tool_message_content: str | list[str | dict[str, Any]] | None = None

    @root_validator
    def validate_tool_runner_response(
        cls, values: dict[str, ToolResponse | str]
    ) -> dict[str, ToolResponse | str]:
        fields = ["tool_response", "tool_message_content", "tool_run_kickoff"]
        provided = sum(1 for field in fields if values.get(field) is not None)

        if provided != 1:
            raise ValueError(
                "Exactly one of 'tool_response', 'tool_message_content', "
                "or 'tool_run_kickoff' must be provided"
            )

        return values


class ToolCallFinalResult(ToolCallKickoff):
    tool_result: Any  # we would like to use JSON_ro, but can't due to its recursive nature
