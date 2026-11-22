"""Direct controls for independent agents on the selected chat branch."""

from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel

from onyx.agents.models import AgentInfo, MessageDelivery, RunFailureKind
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


def _find_agent(agents: list[AgentInfo], caller_id: str, target: str) -> AgentInfo:
    """The agent at `target`: a path, `..` for the caller's parent, or an agent ID.

    `register_child` keeps paths unique, but an older chat can repeat a path.
    Discovery keeps the directory's order (spawned_by_message_id descending),
    so the agent from the newest spawning response wins.
    """
    if target == "..":
        parent_id = next(
            (agent.parent_id for agent in agents if agent.id == caller_id), None
        )
        if parent_id is None:
            raise ToolCallException(
                "The root has no parent.",
                "You are the root agent, so you have no parent. Use list_agents "
                "to find agents.",
            )
        target = parent_id
    found = next((agent for agent in agents if target in (agent.path, agent.id)), None)
    if found is None:
        raise ToolCallException(
            f"No visible agent matches {target!r}.",
            f"No agent on this chat branch has the path {target!r}. Use a path "
            "that list_agents shows.",
        )
    return found


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
        return ToolResult(content=f"Started {started.agent_path}.")


class ListAgentsTool(_SubagentTool):
    name = "list_agents"
    display_name = "List agents"
    description = "List agents with their path and status."
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
            line = f"{agent.path}: {status}"
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
        control = invocation.agents
        receipt = control.send_message(
            _find_agent(control.discover_agents(), control.agent_id, request.target).id,
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
        control = invocation.agents
        agent = control.interrupt_agent(
            _find_agent(
                control.discover_agents(), control.agent_id, selection.target
            ).id
        )
        if agent is None:
            raise ToolCallException(
                "Agent cannot be interrupted on this chat branch.",
                "That agent cannot be interrupted: it is you or the root. Use "
                "list_agents to find agents.",
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
        agents = control.discover_agents()
        children = {
            agent.id: agent for agent in agents if agent.parent_id == control.agent_id
        }
        selected = [
            _find_agent(agents, control.agent_id, target)
            for target in request.targets or []
        ]
        unknown = [agent.path for agent in selected if agent.id not in children]
        if unknown:
            raise ToolCallException(
                "Agents to wait for are not the caller's agents.",
                f"You did not start these agents: {', '.join(unknown)}. "
                "Use list_agents to find the agents that you started.",
            )
        # No targets means all of the caller's agents.
        agent_ids = [agent.id for agent in selected] or None
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
