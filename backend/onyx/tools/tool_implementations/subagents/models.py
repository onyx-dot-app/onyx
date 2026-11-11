from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.models import MessageDelivery


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
    delivery: Literal[MessageDelivery.SEND, MessageDelivery.QUEUE] = Field(
        default=MessageDelivery.SEND,
        description="Send at the next model step, or queue a new run after normal completion.",
    )
    message: str = Field(min_length=1, description="Instructions for this agent.")


class ListAgentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_prefix: str | None = Field(
        default=None,
        description="List only agents whose path starts with this prefix, such as /root/research.",
    )
