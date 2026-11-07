from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.context.search.models import SearchDoc


class SpawnAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="A short name for this agent.")
    instruction: str = Field(
        min_length=1,
        description="A self-contained task. The child does not inherit this conversation.",
    )


class SubagentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)


class ListAgentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubagentResult(BaseModel):
    """Source references imported with a completed subagent's answer."""

    type: Literal["subagent_result"] = "subagent_result"
    citation_mapping: dict[int, SearchDoc] = Field(default_factory=dict)
