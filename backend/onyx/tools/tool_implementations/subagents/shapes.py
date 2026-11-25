"""The shapes of the agent operations: each tool family names the spawn tool
and takes the spawn and send arguments its own way (AGENT_SHAPES); each
arguments model's pure `request` gives the operation's typed input."""

from collections.abc import Mapping
from typing import NamedTuple

from pydantic import Field

from onyx.agents.models import MessageDelivery
from onyx.llm.model_capabilities import ToolFamily
from onyx.tools.constants import (
    AGENT_TOOL_NAME,
    SEND_MESSAGE_TOOL_NAME,
    SPAWN_AGENT_TOOL_NAME,
    WAIT_AGENT_TOOL_NAME,
)
from onyx.tools.models import ToolArguments
from onyx.tools.tool_implementations.subagents.models import (
    DELIVERY_DESCRIPTION,
    TARGET_DESCRIPTION,
    Delivery,
)


class SpawnRequest(NamedTuple):
    """A call of the spawn operation: start an agent on a task."""

    # The agent's name, the last segment of its path.
    name: str
    # The task, the agent's first message.
    instruction: str


class SpawnAgentArguments(ToolArguments[SpawnRequest]):
    task_name: str = Field(min_length=1, description="Short name for the task.")
    message: str = Field(min_length=1, description="Self-contained task.")

    def request(self) -> SpawnRequest:
        return SpawnRequest(name=self.task_name, instruction=self.message)


class AgentArguments(ToolArguments[SpawnRequest]):
    description: str = Field(
        min_length=1, description="A short (3-5 word) description of the task"
    )
    prompt: str = Field(min_length=1, description="The task for the agent to perform")

    def request(self) -> SpawnRequest:
        # The description names the agent's path segment, which has no slash.
        return SpawnRequest(
            name=self.description.replace("/", "-"), instruction=self.prompt
        )


class SendRequest(NamedTuple):
    """A call of the send operation: a message to an agent."""

    target: str
    message: str
    delivery: Delivery


class SendMessageArguments(ToolArguments[SendRequest]):
    target: str = Field(min_length=1, description=TARGET_DESCRIPTION)
    delivery: Delivery = Field(
        default=MessageDelivery.SEND, description=DELIVERY_DESCRIPTION
    )
    message: str = Field(min_length=1)

    def request(self) -> SendRequest:
        return SendRequest(
            target=self.target, message=self.message, delivery=self.delivery
        )


class SendMessageToArguments(ToolArguments[SendRequest]):
    to: str = Field(min_length=1, description=TARGET_DESCRIPTION)
    message: str = Field(min_length=1)
    delivery: Delivery = Field(
        default=MessageDelivery.SEND, description=DELIVERY_DESCRIPTION
    )

    def request(self) -> SendRequest:
        return SendRequest(target=self.to, message=self.message, delivery=self.delivery)


class AgentShape(NamedTuple):
    """How one tool family names and calls the agent operations; list_agents,
    interrupt_agent and send_message have one name in every shape."""

    spawn_name: str
    spawn_arguments: type[ToolArguments[SpawnRequest]]
    # The spawn arguments that hold the agent's name and its task, which
    # errors name.
    spawn_name_argument: str
    spawn_task_argument: str
    send_arguments: type[ToolArguments[SendRequest]]
    # The root's tool that ends its response until its agents finish. None:
    # the shape has none, and a root response waits for the agents that it
    # created by itself; when it ends while they run, their results arrive
    # together in one new response once all of them finish
    # (db/chat_inputs.py:agent_waits).
    wait_name: str | None


AGENT_SHAPES: Mapping[ToolFamily, AgentShape] = {
    ToolFamily.OPENAI: AgentShape(
        spawn_name=SPAWN_AGENT_TOOL_NAME,
        spawn_arguments=SpawnAgentArguments,
        spawn_name_argument="task_name",
        spawn_task_argument="message",
        send_arguments=SendMessageArguments,
        wait_name=WAIT_AGENT_TOOL_NAME,
    ),
    # The shape Claude models are trained on.
    ToolFamily.CLAUDE: AgentShape(
        spawn_name=AGENT_TOOL_NAME,
        spawn_arguments=AgentArguments,
        spawn_name_argument="description",
        spawn_task_argument="prompt",
        send_arguments=SendMessageToArguments,
        wait_name=None,
    ),
}
# The names across the shapes and saved chats: the spawn tool, and the
# tools whose calls start background agents, whose runs show apart from the
# call.
SPAWN_TOOL_NAMES = frozenset(shape.spawn_name for shape in AGENT_SHAPES.values())
AGENT_START_TOOL_NAMES = SPAWN_TOOL_NAMES | {SEND_MESSAGE_TOOL_NAME}
WAIT_AGENT_TOOL_NAMES = frozenset(
    shape.wait_name for shape in AGENT_SHAPES.values() if shape.wait_name is not None
)
# The spawn tools of the shapes without a wait tool; a saved call of one is
# its root response's wait.
IMPLICIT_WAIT_SPAWN_TOOL_NAMES = frozenset(
    shape.spawn_name for shape in AGENT_SHAPES.values() if shape.wait_name is None
)
