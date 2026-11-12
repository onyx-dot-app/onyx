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
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import (
    CodeModeExposure,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.subagents.models import (
    AgentMessageInput,
    AgentWaitDetails,
    ChatConfiguration,
    ListAgentsInput,
    SpawnAgentInput,
    SubagentSelection,
    WaitAgentsInput,
)

# An agent name is a path segment shown in agent lists and the UI.
MAX_AGENT_NAME_BYTES = 256


class _SubagentTool(Tool):
    id = None
    code_mode_exposure = CodeModeExposure.DIRECT
    input_model: ClassVar[type[BaseModel]]

    def tool_definition(self) -> ToolDefinition:
        schema = self.input_model.model_json_schema()
        # Titles repeat the property names; leave them out of every request.
        schema.pop("title", None)
        for field in schema["properties"].values():
            field.pop("title", None)
        return ToolDefinition(
            name=self.name, description=self.description, parameters=schema
        )


class SpawnAgentTool(_SubagentTool):
    name = SPAWN_AGENT_TOOL_NAME
    display_name = "Start agent"
    description = (
        "Start a background agent with this chat's tools. Returns immediately, while "
        "the agent works. Its result arrives at your next step if you are running, "
        "or starts a new response if you are not. It cannot see this conversation, "
        "so give complete instructions."
    )
    input_model = SpawnAgentInput

    def __init__(self, create_agent: Callable[[], Agent], *, max_steps: int) -> None:
        self.create_agent = create_agent
        self.max_steps = max_steps

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SpawnAgentInput, invocation.arguments)
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
    description = (
        "List agents: path, agent_id, parent, status. [you] marks you. By default, "
        "lists the root, running agents, and agents started in this turn. Not a "
        "way to wait: results arrive without it."
    )
    input_model = ListAgentsInput

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(ListAgentsInput, invocation.arguments)
        control = invocation.agents
        discovered = control.discover_agents()
        # Chat run IDs are response IDs, which increase: a run newer than the
        # root's latest run started in this turn.
        turn_start = next(
            (
                int(agent.latest_run_id)
                for agent in discovered
                if agent.parent_id is None and agent.latest_run_id is not None
            ),
            None,
        )
        matching = sorted(
            (
                agent
                for agent in discovered
                if request.path_prefix is None
                or agent.path.startswith(request.path_prefix)
            ),
            key=lambda agent: agent.path,
        )
        agents = [
            agent
            for agent in matching
            if request.include_finished
            or agent.status is None
            or not agent.status.is_terminal
            or agent.latest_run_id is None
            or turn_start is None
            or int(agent.latest_run_id) >= turn_start
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
                f"Not shown: {hidden} finished agents from earlier turns. "
                "Use include_finished to list them."
            )
        return ToolResult(content="\n".join(lines))


class SendMessageTool(_SubagentTool):
    name = SEND_MESSAGE_TOOL_NAME
    display_name = "Send agent message"
    description = (
        "Message another agent. A running agent reads it at its next step; an idle "
        "agent starts a new run. queue: run after normal completion. Results go to the "
        "recipient's spawner, as for spawn_agent. A message never starts a root run."
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
        "Cancel an agent's current run, including its tool calls and foreground work. "
        "Agents it started in the background keep running. No result is reported. "
        "Not yourself or the root."
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


class WaitAgentsTool(_SubagentTool):
    name = WAIT_AGENTS_TOOL_NAME
    display_name = "Wait for agents"
    description = (
        "End your response and wait for agents that you started. Call it in a step "
        "after spawn_agent returns. Without agent_ids, waits for all of them. When "
        "all of them finish, a new response starts with their results. Results of "
        "other agents still arrive when they finish."
    )
    input_model = WaitAgentsInput

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(WaitAgentsInput, invocation.arguments)
        control = invocation.agents
        children = {
            agent.id: agent
            for agent in control.discover_agents()
            if agent.parent_id == control.agent_id
        }
        if request.agent_ids is None:
            selected = list(children.values())
        else:
            unknown = [
                agent_id for agent_id in request.agent_ids if agent_id not in children
            ]
            if unknown:
                raise ToolCallException(
                    "Agents to wait for are not the caller's agents.",
                    f"You did not start these agents: {', '.join(unknown)}. "
                    "Use list_agents to find the agents that you started.",
                )
            selected = [children[agent_id] for agent_id in request.agent_ids]
        running = sorted(
            (
                agent
                for agent in selected
                if agent.latest_run_id is not None
                and agent.status is not None
                and not agent.status.is_terminal
            ),
            key=lambda agent: agent.path,
        )
        if not running:
            return ToolResult(
                content="None of these agents is running. Their results are in "
                "this conversation, or arrive before your next step."
            )
        return ToolResult(
            content=f"Waiting for {', '.join(agent.path for agent in running)}. "
            "Your response ends now. When all of them finish, a new response "
            "starts with their results.",
            details=AgentWaitDetails(
                run_ids=[
                    agent.latest_run_id
                    for agent in running
                    if agent.latest_run_id is not None
                ]
            ),
            terminate=True,
        )
