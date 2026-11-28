from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from onyx.agents.models import MessageDelivery


class ChatConfiguration(BaseModel):
    """A chat child uses the current request's authorized tools and settings."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["chat"]


class AgentWaitDetails(BaseModel):
    """The agents that a root's wait call waits for; None means all."""

    type: Literal["agent_wait"] = "agent_wait"
    agent_ids: list[str] | None


# The description of an argument that names an agent.
TARGET_DESCRIPTION = (
    "An agent's path, as list_agents shows it, e.g. /root/research; .. is your parent."
)
DELIVERY_DESCRIPTION = "send: next step; queue: after completion."
Delivery = Literal[MessageDelivery.SEND, MessageDelivery.QUEUE]


class AgentSelectionArguments(BaseModel):
    target: str = Field(min_length=1, description=TARGET_DESCRIPTION)


class ListAgentsArguments(BaseModel):
    path_prefix: str | None = Field(
        default=None,
        description="Only paths with this prefix, e.g. /root/research.",
    )
    include_finished: bool = Field(
        default=False,
        description="Also list finished agents from earlier user turns.",
    )


class WaitAgentArguments(BaseModel):
    targets: list[str] | None = Field(
        default=None,
        description="Agent paths, as list_agents shows them, e.g. /root/research. "
        "Omit to wait for all.",
    )

    @field_validator("targets")
    @classmethod
    def _empty_means_all(cls, targets: list[str] | None) -> list[str] | None:
        return targets or None
