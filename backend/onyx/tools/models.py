from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import model_validator
from sqlalchemy.orm import Session

from onyx.context.search.enums import SearchType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceSection


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
    # agentic additions; only need to set during agentic tool calls
    level: int | None = None
    level_question_num: int | None = None


class DynamicSchemaInfo(BaseModel):
    chat_session_id: UUID | None
    message_id: int | None


class SearchQueryInfo(BaseModel):
    predicted_search: SearchType | None
    final_filters: IndexFilters
    recency_bias_multiplier: float


class SearchToolOverrideKwargs(BaseModel):
    force_no_rerank: bool
    alternate_db_session: Session | None
    retrieved_sections_callback: Callable[[list[InferenceSection]], None] | None
    skip_query_analysis: bool

    class Config:
        arbitrary_types_allowed = True


CHAT_SESSION_ID_PLACEHOLDER = "CHAT_SESSION_ID"
MESSAGE_ID_PLACEHOLDER = "MESSAGE_ID"
