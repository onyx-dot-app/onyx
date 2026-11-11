"""Direct controls for independent agents on the selected chat branch."""

from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel

from onyx.agents.models import MessageDelivery
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentLifetime, ToolInvocation
from onyx.configs.chat_configs import CHAT_EXECUTION_TIMEOUT_S
from onyx.llm.models import ToolDefinition, ToolResult, UserMessage
from onyx.tools.constants import SEND_MESSAGE_TOOL_NAME, SPAWN_AGENT_TOOL_NAME
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import (
    CodeModeExposure,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.subagents.models import (
    AgentMessageInput,
    ChatConfiguration,
    ListAgentsInput,
    SpawnAgentInput,
    SubagentSelection,
)


class _SubagentTool(Tool):
    id = None
    code_mode_exposure = CodeModeExposure.DIRECT
    input_model: ClassVar[type[BaseModel]]

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.input_model.model_json_schema(),
        )


class SpawnAgentTool(_SubagentTool):
    name = SPAWN_AGENT_TOOL_NAME
    display_name = "Start agent"
    description = (
        "Start an independent agent with the tools configured for this chat. Returns immediately. "
        "Its result arrives automatically before your next model step. A root response "
        "may end while the agent works and receive a follow-up when it finishes. "
        "A subagent waits for the agents it starts before finishing. "
        "Give it complete instructions; it cannot see this conversation."
    )
    input_model = SpawnAgentInput

    def __init__(self, create_agent: Callable[[], Agent], *, max_steps: int) -> None:
        self.create_agent = create_agent
        self.max_steps = max_steps

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SpawnAgentInput, invocation.arguments)
        started = invocation.agents.spawn_agent(
            self.create_agent(),
            name=request.name,
            description=request.instruction,
            max_steps=self.max_steps,
            messages=[UserMessage(content=request.instruction)],
            restoration_config=ChatConfiguration(kind="chat"),
            lifetime=AgentLifetime.BACKGROUND,
            total_timeout_s=CHAT_EXECUTION_TIMEOUT_S,
        )
        return ToolResult(
            content=f"Started {started.agent_path} (agent_id: {started.agent_id})."
        )


class ListAgentsTool(_SubagentTool):
    name = "list_agents"
    display_name = "List agents"
    description = (
        "List the whole agent tree on this chat branch, including the root and agents "
        "from earlier turns: path, agent_id, parent, and status. "
        "Your own entry is marked. Pass path_prefix to list one subtree."
    )
    input_model = ListAgentsInput

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(ListAgentsInput, invocation.arguments)
        control = invocation.agents
        agents = sorted(
            (
                agent
                for agent in control.discover_agents()
                if request.path_prefix is None
                or agent.path.startswith(request.path_prefix)
            ),
            key=lambda agent: agent.path,
        )
        if not agents:
            return ToolResult(content="No agents match on this chat branch.")
        lines: list[str] = []
        for agent in agents:
            status = agent.status.value if agent.status is not None else "not started"
            parent = f"parent {agent.parent_id}" if agent.parent_id else "root"
            line = f"{agent.path} (agent_id: {agent.id}; {parent}): {status}"
            if agent.id == control.agent_id:
                line += " [you]"
            lines.append(line)
        return ToolResult(content="\n".join(lines))


class SendMessageTool(_SubagentTool):
    name = SEND_MESSAGE_TOOL_NAME
    display_name = "Send agent message"
    description = (
        "Send instructions to any other agent in this chat's agent tree; use list_agents "
        "for IDs. A running agent receives them before its next model step without "
        "resetting its limits. An idle agent starts a new run in its existing "
        "conversation. Set delivery to queue for a new run after normal completion with "
        "fresh limits. Stopped, failed, or interrupted agents keep queued work "
        "paused until an explicit send. The root agent reads messages at its next step "
        "while it runs; a message never starts a root run. Returns immediately; results "
        "go to the agent that spawned the recipient."
    )
    input_model = AgentMessageInput

    def __init__(self, *, max_steps: int) -> None:
        self.max_steps = max_steps

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(AgentMessageInput, invocation.arguments)
        receipt = invocation.agents.send_message(
            request.agent_id,
            message=request.message,
            delivery=request.delivery,
            max_steps=self.max_steps,
            total_timeout_s=CHAT_EXECUTION_TIMEOUT_S,
        )
        return ToolResult(
            content="Message queued for the agent's next run."
            if request.delivery == MessageDelivery.QUEUE or receipt.run_id is None
            else "Message queued for the agent's next model step."
        )


class InterruptAgentTool(_SubagentTool):
    name = "interrupt_agent"
    display_name = "Interrupt agent"
    description = (
        "Request cancellation of one agent's current run. You can interrupt any agent "
        "in the tree except yourself and the root; agents below it keep running. The "
        "interrupted run reports no result. Its conversation remains, and its queued "
        "messages stay paused until an explicit send. Use list_agents to confirm it stopped."
    )
    input_model = SubagentSelection

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        selection = parse_tool_arguments(SubagentSelection, invocation.arguments)
        agent = invocation.agents.interrupt_agent(selection.agent_id)
        if agent is None:
            raise ToolCallException(
                "Agent cannot be interrupted on this chat branch.",
                "That agent cannot be interrupted: it is you, the root, or not on this "
                "chat branch. Use list_agents to find agents.",
            )
        return ToolResult(content=f"Interruption requested for {agent.path}.")
