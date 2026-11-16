from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from onyx.agents.models import MessageDelivery


class ChatConfiguration(BaseModel):
    """A chat child uses the current request's authorized tools and settings."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["chat"]


class AgentWaitDetails(BaseModel):
    """The agents that a root `wait_agents` call waits for; None means all."""

    type: Literal["agent_wait"] = "agent_wait"
    agent_ids: list[str] | None


class SpawnAgentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Short name.")
    instruction: str = Field(min_length=1, description="Self-contained task.")


class AgentSelectionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, description="From list_agents.")


class SendMessageArguments(AgentSelectionArguments):
    delivery: Literal[MessageDelivery.SEND, MessageDelivery.QUEUE] = Field(
        default=MessageDelivery.SEND,
        description="send: next step; queue: after completion.",
    )
    message: str = Field(min_length=1)


class ListAgentsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_prefix: str | None = Field(
        default=None,
        description="Only paths with this prefix, e.g. /root/research.",
    )
    include_finished: bool = Field(
        default=False,
        description="Also list finished agents from earlier user turns.",
    )


class WaitAgentsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_ids: list[str] | None = Field(
        default=None,
        description="Agents to wait for, from list_agents. Omit to wait for all.",
    )

    @field_validator("agent_ids")
    @classmethod
    def _empty_means_all(cls, agent_ids: list[str] | None) -> list[str] | None:
        return agent_ids or None
