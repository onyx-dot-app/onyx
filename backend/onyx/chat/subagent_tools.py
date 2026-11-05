"""Direct controls for independent agents on the selected chat branch."""

from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel

from onyx.agents.models import AgentInfo, RunResult, RunState
from onyx.agents.runtime import Agent, RunFailed, result_from_snapshot
from onyx.agents.tools import (
    AgentLifetime,
    ChildRunWait,
    ToolInvocation,
    ToolOutcome,
)
from onyx.chat.citation_utils import (
    collapse_citations,
    extract_citation_order_from_text,
    message_citation_sources,
)
from onyx.chat.models import (
    ListAgentsInput,
    SpawnAgentInput,
    SubagentSelection,
)
from onyx.configs.chat_configs import CHAT_EXECUTION_TIMEOUT_S, MAX_LLM_CYCLES
from onyx.llm.cancellation import AgentCancelled
from onyx.llm.models import ToolDefinition, ToolResult, UserMessage
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.tools.interface import CITATIONS_PER_TOOL_CALL, Tool, parse_tool_arguments
from onyx.tools.models import (
    SubagentResult,
    ToolCallException,
    ToolContext,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _selected_agent(invocation: ToolInvocation) -> AgentInfo:
    selection = parse_tool_arguments(SubagentSelection, invocation.arguments)
    agent = next(
        (
            child
            for child in invocation.agents.discover_children()
            if child.id == selection.agent_id
        ),
        None,
    )
    if agent is None:
        raise ToolCallException(
            "Subagent is unavailable on this chat branch.",
            "Subagent is unavailable on this chat branch. Use list_agents to find available agents.",
        )
    return agent


def _completed_result(
    result: RunResult, invocation: ToolInvocation, context: ToolContext
) -> ToolResult:
    sources = message_citation_sources(result.output)
    cited = extract_citation_order_from_text(result.output.text)
    imported = {number: sources[number] for number in cited if number in sources}
    if len(imported) > CITATIONS_PER_TOOL_CALL:
        raise ValueError("Subagent answer exceeds the citation limit for one tool call")
    by_document = {document.document_id: document for document in imported.values()}
    existing = {
        number: by_document[document_id]
        for number, document_id in context.citation_mapping.items()
        if document_id in by_document
    }
    answer, citations = collapse_citations(
        result.output.text,
        existing,
        imported,
        minimum_citation_number=context.next_citation_num
        + invocation.call_index * CITATIONS_PER_TOOL_CALL,
    )
    return ToolResult(
        content=answer, details=SubagentResult(citation_mapping=citations)
    )


class _SubagentTool(Tool):
    id = None
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
        "The agent continues after this response ends. Use inspect_agent or wait_agent "
        "to obtain its answer. Give it complete instructions; it cannot see this conversation."
    )
    input_model = SpawnAgentInput

    def __init__(self, create_agent: Callable[[], Agent]) -> None:
        self.create_agent = create_agent

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(SpawnAgentInput, invocation.arguments)
        started = invocation.agents.spawn_agent(
            self.create_agent(),
            name=request.name,
            description=request.instruction,
            max_steps=MAX_LLM_CYCLES,
            messages=[UserMessage(content=request.instruction)],
            lifetime=AgentLifetime.BACKGROUND,
            total_timeout_s=CHAT_EXECUTION_TIMEOUT_S,
        )
        return ToolResult(content=started.model_dump_json())


class ListAgentsTool(_SubagentTool):
    name = "list_agents"
    display_name = "List agents"
    description = "List agents available on this chat branch, including agents from earlier turns."
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


class InspectAgentTool(_SubagentTool):
    name = "inspect_agent"
    display_name = "Inspect agent"
    description = "Check an agent without waiting. Returns its answer when complete, otherwise its status."
    input_model = SubagentSelection

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        agent = _selected_agent(invocation)
        if agent.latest_run_id is None:
            raise ValueError("Subagent has no run")
        result = invocation.agents.wait_run(agent.latest_run_id, timeout=0)
        if result is None:
            return ToolResult(
                content=agent.model_dump_json(exclude={"restoration_config"})
            )
        return _completed_result(result, invocation, context)


class WaitAgentTool(_SubagentTool):
    name = "wait_agent"
    display_name = "Wait for agent"
    description = (
        "Wait for an agent's final answer. Other independent agents continue. "
        "Stopping this wait does not cancel the agent; use cancel_agent for that."
    )
    input_model = SubagentSelection

    def __init__(self) -> None:
        self.result_from_children = self._result_from_children

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:  # noqa: ARG002
        agent = _selected_agent(invocation)
        if agent.latest_run_id is None:
            raise ValueError("Subagent has no run")
        return ChildRunWait(run_ids=[agent.latest_run_id])

    def _result_from_children(
        self, invocation: ToolInvocation, context: ToolContext, children: list[RunState]
    ) -> ToolResult:
        if len(children) != 1:
            raise ValueError("Wait requires one subagent result")
        try:
            result = result_from_snapshot(children[0])
        except RunFailed as error:
            logger.warning("Subagent %s failed: %s", children[0].agent_id, error)
            return ToolResult(content=f"Subagent failed: {error}", is_error=True)
        except AgentCancelled:
            invocation.cancellation.check()
            logger.debug("Subagent %s was cancelled", children[0].agent_id)
            return ToolResult(content="Subagent was cancelled.", is_error=True)
        return _completed_result(result, invocation, context)


class CancelAgentTool(_SubagentTool):
    name = "cancel_agent"
    display_name = "Cancel agent"
    description = (
        "Request cancellation of an agent. Inspect it to confirm when it has stopped."
    )
    input_model = SubagentSelection

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        agent = _selected_agent(invocation)
        if agent.latest_run_id is None:
            raise ValueError("Subagent has no run")
        invocation.agents.cancel_run(agent.latest_run_id)
        return ToolResult(content=f"Cancellation requested for {agent.path}.")
