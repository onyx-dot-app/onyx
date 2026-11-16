"""Direct controls for independent agents on the selected chat branch."""

from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel

from onyx.agents.models import MessageDelivery, RunFailureKind
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentLifetime, ToolInvocation
from onyx.configs.chat_configs import CHAT_EXECUTION_TIMEOUT_S
from onyx.db.chat_inputs import MAX_PENDING_MESSAGE_BYTES
from onyx.llm.models import ToolDefinition, ToolResult, UserMessage
from onyx.tools.constants import (
    SEND_MESSAGE_TOOL_NAME,
    SPAWN_AGENT_TOOL_NAME,
    WAIT_AGENTS_TOOL_NAME,
)
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.subagents.models import (
    AgentSelectionArguments,
    AgentWaitDetails,
    ChatConfiguration,
    ListAgentsArguments,
    SendMessageArguments,
    SpawnAgentArguments,
    WaitAgentsArguments,
)

# An agent name is a path segment shown in agent lists and the UI.
MAX_AGENT_NAME_BYTES = 256


class _SubagentTool(Tool):
    id = None
    code_mode_exposure = CodeModeExposure.DIRECT
    arguments: ClassVar[type[BaseModel]]

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, self.arguments
        )


class SpawnAgentTool(_SubagentTool):
    name = SPAWN_AGENT_TOOL_NAME
    display_name = "Start agent"
    description = (
        "Start an agent on a task in the background. It does not see this "
        "conversation, so give complete instructions. Its result arrives as a message."
    )
    arguments = SpawnAgentArguments

    def __init__(self, create_agent: Callable[[], Agent], *, max_steps: int) -> None:
        self.create_agent = create_agent
        self.max_steps = max_steps

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SpawnAgentArguments, invocation.arguments)
        # The instruction becomes the child's first message, so it has the
        # limit of a message sent to an agent.
        for field, value, limit in (
            ("name", request.name, MAX_AGENT_NAME_BYTES),
            ("instruction", request.instruction, MAX_PENDING_MESSAGE_BYTES),
        ):
            if len(value.encode()) > limit:
                raise ToolCallException(
                    f"Agent {field} exceeds {limit} bytes.",
                    f"The {field} can have at most {limit} bytes. Shorten it and "
                    "call spawn_agent again.",
                )
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
    description = "List agents with their path, agent_id, parent and status."
    arguments = ListAgentsArguments

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(ListAgentsArguments, invocation.arguments)
        control = invocation.agents
        matching = sorted(
            (
                agent
                for agent in control.discover_agents()
                if request.path_prefix is None
                or agent.path.startswith(request.path_prefix)
            ),
            key=lambda agent: agent.path,
        )
        agents = [
            agent
            for agent in matching
            if request.include_finished
            or agent.current_turn
            or (agent.status is not None and not agent.status.is_terminal)
        ]
        hidden = len(matching) - len(agents)
        if not agents and not hidden:
            return ToolResult(content="No agents match on this chat branch.")
        lines: list[str] = []
        for agent in agents:
            status = (
                "stopped by the user"
                if agent.failure_kind == RunFailureKind.STOPPED_BY_USER
                else agent.status.value
                if agent.status is not None
                else "not started"
            )
            parent = f"parent {agent.parent_id}" if agent.parent_id else "root"
            line = f"{agent.path} (agent_id: {agent.id}; {parent}): {status}"
            if agent.id == control.agent_id:
                line += " [you]"
            lines.append(line)
        if hidden:
            lines.append(
                f"Not shown: {hidden} finished agents from earlier user turns. "
                "Use include_finished to list them."
            )
        return ToolResult(content="\n".join(lines))


class SendMessageTool(_SubagentTool):
    name = SEND_MESSAGE_TOOL_NAME
    display_name = "Send agent message"
    description = (
        "Send a message to an agent. A running agent reads it at its next step; an "
        "idle agent starts a new run with it."
    )
    arguments = SendMessageArguments

    def __init__(self, *, max_steps: int) -> None:
        self.max_steps = max_steps

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SendMessageArguments, invocation.arguments)
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
    description = "Stop an agent's current run. No result is reported."
    arguments = AgentSelectionArguments

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        selection = parse_tool_arguments(AgentSelectionArguments, invocation.arguments)
        agent = invocation.agents.interrupt_agent(selection.agent_id)
        if agent is None:
            raise ToolCallException(
                "Agent cannot be interrupted on this chat branch.",
                "That agent cannot be interrupted: it is you, the root, or not on this "
                "chat branch. Use list_agents to find agents.",
            )
        return ToolResult(content=f"Interruption requested for {agent.path}.")


class WaitAgentsTool(_SubagentTool):
    name = WAIT_AGENTS_TOOL_NAME
    display_name = "Wait for agents"
    description = (
        "Wait for agents that you started and end your response. When they finish, a "
        "new response starts with all of their results."
    )
    arguments = WaitAgentsArguments

    def __init__(self, *, has_open_cells: Callable[[], bool]) -> None:
        self.has_open_cells = has_open_cells

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(WaitAgentsArguments, invocation.arguments)
        if self.has_open_cells():
            raise ToolCallException(
                "A code cell is open.",
                "A code cell is still open, and ending your response would stop "
                "it. Wait for it with wait_code first.",
            )
        control = invocation.agents
        children = {
            agent.id: agent
            for agent in control.discover_agents()
            if agent.parent_id == control.agent_id
        }
        agent_ids = request.agent_ids
        unknown = [agent_id for agent_id in agent_ids or [] if agent_id not in children]
        if unknown:
            raise ToolCallException(
                "Agents to wait for are not the caller's agents.",
                f"You did not start these agents: {', '.join(unknown)}. "
                "Use list_agents to find the agents that you started.",
            )
        running = sorted(
            children[agent_id].path
            for agent_id in agent_ids or children
            if (status := children[agent_id].status) is not None
            and not status.is_terminal
        )
        # The saved details also hold agents that this turn starts later, from
        # this step's spawns or queued messages. Without a running agent the
        # run goes on.
        return ToolResult(
            content=f"Waiting for {len(running)} "
            f"{'agent' if len(running) == 1 else 'agents'}: {', '.join(running)}."
            if running
            else "Wait recorded, but none of these agents is running, so your "
            "response continues and their results arrive before your next step.",
            details=AgentWaitDetails(agent_ids=agent_ids),
            terminate=bool(running),
        )
