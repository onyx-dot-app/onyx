from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_AGENT_WAIT_SECONDS = 30
MAX_AGENT_WAIT_SECONDS = 300


class ChatConfiguration(BaseModel):
    """A chat child uses the current request's authorized tools and settings."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["chat"]


class SpawnAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="A short name for this agent.")
    instruction: str = Field(
        min_length=1,
        description="A self-contained task. The child does not inherit this conversation.",
    )


class SubagentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(
        min_length=1, description="The agent_id returned by spawn_agent or list_agents."
    )


class AgentMessageInput(SubagentSelection):
    message: str = Field(min_length=1, description="Instructions for this agent.")


class ListAgentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WaitAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = Field(
        default=DEFAULT_AGENT_WAIT_SECONDS,
        ge=1,
        le=MAX_AGENT_WAIT_SECONDS,
        description="Maximum time to wait for any unread agent completion.",
    )
