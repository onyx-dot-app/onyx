from sqlalchemy.orm import Session

from onyx.agents.tools import ToolInvocation
from onyx.db.kg_config import get_kg_config_settings
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.interface import Tool, ToolContext
from onyx.utils.logger import setup_logger

logger = setup_logger()

QUERY_FIELD = "query"


class KnowledgeGraphTool(Tool):
    _NAME = "run_kg_search"
    _DESCRIPTION = "Search the knowledge graph for information. Never call this tool."
    _DISPLAY_NAME = "Knowledge Graph Search"

    def __init__(self, tool_id: int) -> None:

        self._id = tool_id

        raise NotImplementedError(
            "KnowledgeGraphTool should not be getting used right now."
        )

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
    def is_available(cls, db_session: Session) -> bool:  # noqa: ARG003
        """Available only if KG is enabled and exposed."""
        kg_configs = get_kg_config_settings()
        return kg_configs.KG_ENABLED and kg_configs.KG_EXPOSED

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    QUERY_FIELD: {
                        "type": "string",
                        "description": "What to search for",
                    },
                },
                "required": [QUERY_FIELD],
            },
        )

    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        raise NotImplementedError("KnowledgeGraphTool.run is not implemented.")
