from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.configs.chat_configs import EXA_API_KEY
from onyx.configs.chat_configs import SERPER_API_KEY
from onyx.tools.models import ToolResponse
from onyx.tools.tool import RunContextWrapper
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()

# TODO: Align on separation of Tools and SubAgents. Right now, we're only keeping this around for backwards compatibility.
QUERY_FIELD = "query"
_GENERIC_ERROR_MESSAGE = "WebSearchTool should only be used by the Deep Research Agent, not via tool calling."


class WebSearchTool(Tool[None, None]):
    _NAME = "run_web_search"
    _DESCRIPTION = "Search the web for information. Never call this tool."
    _DISPLAY_NAME = "Web Search"

    def __init__(self, tool_id: int) -> None:
        self._id = tool_id

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

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available only if EXA or SERPER API key is configured."""
        return bool(EXA_API_KEY) or bool(SERPER_API_KEY)

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        QUERY_FIELD: {
                            "type": "string",
                            "description": "What to search for",
                        },
                    },
                    "required": [QUERY_FIELD],
                },
            },
        }

    def get_llm_tool_response(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def run_v2(
        self,
        run_context: RunContextWrapper[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError("WebSearchTool.run_v2 is not implemented.")

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def get_final_result(self, *args: ToolResponse) -> JSON_ro:
        raise ValueError(_GENERIC_ERROR_MESSAGE)
