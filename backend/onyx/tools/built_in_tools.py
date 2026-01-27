from typing import Any, Type
from typing import Union

from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


BUILT_IN_TOOL_TYPES = Union[
    SearchTool,
    ImageGenerationTool,
    WebSearchTool,
    KnowledgeGraphTool,
    OpenURLTool,
    PythonTool,
    Any,  # AgentTool loaded lazily
]


class _LazyToolMap(dict):
    """Dict subclass that lazily loads AgentTool on first access."""

    def __init__(self):
        super().__init__({
            SearchTool.__name__: SearchTool,
            ImageGenerationTool.__name__: ImageGenerationTool,
            WebSearchTool.__name__: WebSearchTool,
            KnowledgeGraphTool.__name__: KnowledgeGraphTool,
            OpenURLTool.__name__: OpenURLTool,
            PythonTool.__name__: PythonTool,
        })
        self._agent_tool_loaded = False

    def _ensure_agent_tool(self):
        """Lazy load AgentTool to avoid circular import."""
        if not self._agent_tool_loaded:
            from onyx.tools.tool_implementations.agent.agent_tool import AgentTool
            self[AgentTool.__name__] = AgentTool
            self._agent_tool_loaded = True

    def __getitem__(self, key):
        self._ensure_agent_tool()
        return super().__getitem__(key)

    def __iter__(self):
        self._ensure_agent_tool()
        return super().__iter__()

    def items(self):
        self._ensure_agent_tool()
        return super().items()

    def keys(self):
        self._ensure_agent_tool()
        return super().keys()

    def values(self):
        self._ensure_agent_tool()
        return super().values()


BUILT_IN_TOOL_MAP: dict[str, Type[Any]] = _LazyToolMap()


STOPPING_TOOLS_NAMES: list[str] = [ImageGenerationTool.NAME]
CITEABLE_TOOLS_NAMES: list[str] = [
    SearchTool.NAME,
    WebSearchTool.NAME,
    OpenURLTool.NAME,
]


def get_built_in_tool_ids() -> list[str]:
    return list(BUILT_IN_TOOL_MAP.keys())


def get_built_in_tool_by_id(in_code_tool_id: str) -> Type[Any]:
    return BUILT_IN_TOOL_MAP[in_code_tool_id]
