from typing import Any

from sqlalchemy.orm import Session

from onyx.chat.infra import Emitter
from onyx.db.kg_config import get_kg_config_settings
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()

QUERY_FIELD = "query"


class KnowledgeGraphTool(Tool[None]):
    _NAME = "run_kg_search"
    _DESCRIPTION = "Search the knowledge graph for information. Never call this tool."
    _DISPLAY_NAME = "Knowledge Graph Search"

    def __init__(self, tool_id: int, emitter: Emitter) -> None:
        raise NotImplementedError(
            "KnowledgeGraphTool should not be getting used right now."
        )
        super().__init__(emitter=emitter)

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

    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available only if KG is enabled and exposed."""
        kg_configs = get_kg_config_settings()
        return kg_configs.KG_ENABLED and kg_configs.KG_EXPOSED

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

    def emit_start(self, turn_index: int, tab_index: int) -> None:
        raise NotImplementedError("KnowledgeGraphTool.emit_start is not implemented.")

    def run(
        self,
        run_context: None,
        turn_index: int,
        tab_index: int,
        override_kwargs: None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        raise NotImplementedError("KnowledgeGraphTool.run is not implemented.")
