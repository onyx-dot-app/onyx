"""Direct controls for independent agents on the selected chat branch."""

from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel

from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentLifetime, ToolInvocation
from onyx.configs.chat_configs import CHAT_EXECUTION_TIMEOUT_S
from onyx.llm.models import ToolDefinition, ToolResult, UserMessage
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import (
    CodeModeExposure,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.subagents.models import (
    AgentMessageInput,
    CancelMessageInput,
    ChatConfiguration,
    ListAgentsInput,
    SpawnAgentInput,
    SubagentSelection,
    WaitAgentInput,
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
        "The agent continues after this response ends. Its result arrives automatically "
        "before your next model step or on a later turn. Use wait_agent when you have "
        "no other work. Give it complete instructions; it cannot see this conversation."
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
        return ToolResult(content=started.model_dump_json())


class ListAgentsTool(_SubagentTool):
    name = "list_agents"
    display_name = "List agents"
    description = (
        "List agents available on this chat branch, including agents from earlier turns, "
        "their status, and pending message IDs."
    )
    input_model = ListAgentsInput

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        parse_tool_arguments(ListAgentsInput, invocation.arguments)
        children = invocation.agents.discover_children()
        return ToolResult(
            content="["
            + ",".join(
                child.model_dump_json(exclude={"restoration_config"})
                for child in children
            )
            + "]"
        )


class SendMessageTool(_SubagentTool):
    name = "send_message"
    display_name = "Send agent message"
    description = (
        "Send instructions to an existing agent. A running agent receives them before "
        "its next model step without resetting its limits. An idle agent starts a new "
        "run in its existing conversation. Returns immediately; results arrive separately."
    )
    input_model = AgentMessageInput

    def __init__(self, *, max_steps: int) -> None:
        self.max_steps = max_steps

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(AgentMessageInput, invocation.arguments)
        receipt = invocation.agents.send_message(
            request.agent_id,
            message=request.message,
            max_steps=self.max_steps,
            total_timeout_s=CHAT_EXECUTION_TIMEOUT_S,
        )
        return ToolResult(content=receipt.model_dump_json())


class QueueMessageTool(_SubagentTool):
    name = "queue_message"
    display_name = "Queue agent message"
    description = (
        "Queue instructions for a new run in an existing agent's conversation. "
        "The run starts after normal completion with fresh limits. A stopped, failed, "
        "or limited agent keeps its queue paused until send_message starts another run. "
        "An idle agent that completed normally starts immediately. Returns immediately."
    )
    input_model = AgentMessageInput

    def __init__(self, *, max_steps: int) -> None:
        self.max_steps = max_steps

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(AgentMessageInput, invocation.arguments)
        receipt = invocation.agents.queue_message(
            request.agent_id,
            message=request.message,
            max_steps=self.max_steps,
            total_timeout_s=CHAT_EXECUTION_TIMEOUT_S,
        )
        return ToolResult(content=receipt.model_dump_json())


class CancelMessageTool(_SubagentTool):
    name = "cancel_message"
    display_name = "Remove agent message"
    description = (
        "Remove a pending agent message by its ID from list_agents. "
        "Messages already accepted by the agent cannot be removed."
    )
    input_model = CancelMessageInput

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(CancelMessageInput, invocation.arguments)
        removed = invocation.agents.cancel_message(
            request.agent_id, message_id=request.message_id
        )
        return ToolResult(
            content="Message removed." if removed else "Message is no longer pending."
        )


class WaitAgentTool(_SubagentTool):
    name = "wait_agent"
    display_name = "Wait for agents"
    description = (
        "Wait for unread agent instructions or a background agent completion, or until the timeout. "
        "The message is delivered separately before your next model step. "
        "Other agents and code programs continue. Stopping this wait does not cancel them."
    )
    input_model = WaitAgentInput

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(WaitAgentInput, invocation.arguments)
        ready = invocation.agents.wait_for_agent_message(
            timeout=request.timeout_seconds
        )
        return ToolResult(
            content="An agent message is ready."
            if ready
            else "No agent message arrived before the timeout."
        )


class CancelAgentTool(_SubagentTool):
    name = "cancel_agent"
    display_name = "Cancel agent"
    description = "Request cancellation of an agent. Use list_agents to confirm when it has stopped."
    input_model = SubagentSelection

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        selection = parse_tool_arguments(SubagentSelection, invocation.arguments)
        agent = invocation.agents.lookup_agent(selection.agent_id)
        if agent is None:
            raise ToolCallException(
                "Subagent is unavailable on this chat branch.",
                "Subagent is unavailable on this chat branch. Use list_agents to find available agents.",
            )
        if agent.latest_run_id is None:
            raise ValueError("Subagent has no run")
        invocation.agents.cancel_run(agent.latest_run_id)
        return ToolResult(content=f"Cancellation requested for {agent.path}.")
