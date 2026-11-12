from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.models import MessageDelivery


class ChatConfiguration(BaseModel):
    """A chat child uses the current request's authorized tools and settings."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["chat"]


class SpawnAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Short name.")
    instruction: str = Field(min_length=1, description="Self-contained task.")


class SubagentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, description="From list_agents.")


class AgentMessageInput(SubagentSelection):
    delivery: Literal[MessageDelivery.SEND, MessageDelivery.QUEUE] = Field(
        default=MessageDelivery.SEND,
        description="send: next step; queue: after completion.",
    )
    message: str = Field(min_length=1)


class ListAgentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_prefix: str | None = Field(
        default=None,
        description="Only paths with this prefix, e.g. /root/research.",
    )
