from collections.abc import Generator
from typing import Any
from typing import cast

from onyx.agents.agent_search.dr.sub_agents.internet_search.providers import (
    get_default_provider,
)
from onyx.configs.chat_configs import NUM_INTERNET_SEARCH_RESULTS
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.special_types import JSON_ro

# TODO: Align on separation of Tools and SubAgents. Right now, we're only keeping this around for backwards compatibility.
QUERY_FIELD = "query"
_GENERIC_ERROR_MESSAGE = "InternetSearchTool should only be used by the Deep Research Agent, not via tool calling."


class InternetSearchTool(Tool[None]):
    _NAME = "run_internet_search"
    _DESCRIPTION = "Search the internet for information. Never call this tool."
    _DISPLAY_NAME = "Internet Search"

    def __init__(self, tool_id: int) -> None:
        self._id = tool_id
        # La variable est maintenant définie dans le constructeur pour éviter le NameError
        # et la dépendance circulaire.
        self.num_results = NUM_INTERNET_SEARCH_RESULTS

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    # Added to make tools work better with LLMs in prompts. Should be unique
    # TODO: looks at ways how to best ensure uniqueness.
    # TODO: extra review regarding coding style
    @property
    def llm_name(self) -> str:
        return self.display_name

    """For LLMs which support explicit tool calling"""

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for",
                        },
                        "num_results": {
                            "type": "integer",
                            # Utiliser l'attribut de l'instance pour définir la valeur par défaut
                            "default": self.num_results,
                            "description": "Number of search results to return",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    """For LLMs which do NOT support explicit tool calling"""

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[Any],
        llm: Any,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    """Some tools may want to modify the prompt based on the tool call summary and tool responses.
    Default behavior is to continue with just the raw tool call request/result passed to the LLM."""

    def build_next_prompt(
        self,
        prompt_builder: Any,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> Any:
        raise ValueError(_GENERIC_ERROR_MESSAGE)