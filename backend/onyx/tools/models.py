from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import model_validator
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.enums import SearchType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import QueryExpansions
from shared_configs.model_server_models import Embedding


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


# None indicates that the default value should be used
class SearchToolOverrideKwargs(BaseModel):
    original_query: str | None = None
    force_no_rerank: bool | None = None
    alternate_db_session: Session | None = None
    retrieved_sections_callback: Callable[[list[InferenceSection]], None] | None = None
    skip_query_analysis: bool | None = None
    precomputed_query_embedding: Embedding | None = None
    precomputed_is_keyword: bool | None = None
    precomputed_keywords: list[str] | None = None
    user_file_ids: list[UUID] | None = None
    project_id: int | None = None
    document_sources: list[DocumentSource] | None = None
    time_cutoff: datetime | None = None
    expanded_queries: QueryExpansions | None = None
    kg_entities: list[str] | None = None
    kg_relationships: list[str] | None = None
    kg_terms: list[str] | None = None
    kg_sources: list[str] | None = None
    kg_chunk_id_zero_only: bool | None = False

    class Config:
        arbitrary_types_allowed = True


CHAT_SESSION_ID_PLACEHOLDER = "CHAT_SESSION_ID"
MESSAGE_ID_PLACEHOLDER = "MESSAGE_ID"
