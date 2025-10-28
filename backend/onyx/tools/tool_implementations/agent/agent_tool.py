"""AgentTool implementation for agent-to-agent delegation."""

from collections.abc import Generator
from typing import Any

from onyx.db.models import Persona
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.base_tool import BaseTool
from onyx.tools.models import ToolResponse
from onyx.utils.special_types import JSON_ro


class AgentTool(BaseTool):
    """Tool that delegates tasks to another persona (subagent)."""

    def __init__(
        self,
        tool_id: int,
        target_persona: Persona,
    ) -> None:
        self._id = tool_id
        self._target_persona = target_persona
        self._name = f"call_{target_persona.name.lower().replace(' ', '_')}"
        self._display_name = f"{target_persona.name}"
        self._description = (
            f"Delegate tasks to the {target_persona.name} agent. "
            f"{target_persona.description or ''}"
        )

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def target_persona_id(self) -> int:
        return self._target_persona.id

    def tool_definition(self) -> dict:
        """Return the tool definition for LLM tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self._description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": f"The question or task to delegate to {self._target_persona.name}",
                        }
                    },
                    "required": ["query"],
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        """Build the message content from tool responses."""
        # AgentTool returns JSON responses
        if not args:
            return "No response from subagent"

        # The response is already a JSON string
        return str(args[0].response)

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        """For non-tool-calling LLMs, always run the agent tool with the query."""
        # Return the query as the argument for the agent tool
        return {"query": query}

    def run(
        self, override_kwargs: None = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        """Execute the agent tool by delegating to the target persona.

        This is a placeholder implementation. The actual execution happens in the
        v2 agent tool infrastructure or through direct persona invocation.
        """
        # Extract the query from llm_kwargs
        query = llm_kwargs.get("query", "")

        # Return a placeholder response indicating delegation
        yield ToolResponse(
            id="agent_tool_delegation",
            response={
                "type": "agent_delegation",
                "target_persona": self._target_persona.name,
                "query": query,
                "message": f"Delegating to {self._target_persona.name} agent",
            },
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        """Return the final result from the agent tool execution."""
        if not args:
            return {}

        # Return the aggregated response from all tool responses
        # For now, return the last response
        return args[-1].response
