from typing import Type
from typing import Union

from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
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
    FileReaderTool,
    MemoryTool,
]

BUILT_IN_TOOL_MAP: dict[str, Type[BUILT_IN_TOOL_TYPES]] = {
    SearchTool.__name__: SearchTool,
    ImageGenerationTool.__name__: ImageGenerationTool,
    WebSearchTool.__name__: WebSearchTool,
    KnowledgeGraphTool.__name__: KnowledgeGraphTool,
    OpenURLTool.__name__: OpenURLTool,
    PythonTool.__name__: PythonTool,
    FileReaderTool.__name__: FileReaderTool,
    MemoryTool.__name__: MemoryTool,
}

STOPPING_TOOLS_NAMES: list[str] = [ImageGenerationTool.NAME]
CITEABLE_TOOLS_NAMES: list[str] = [
    SearchTool.NAME,
    WebSearchTool.NAME,
    OpenURLTool.NAME,
]


def get_built_in_tool_ids() -> list[str]:
    return list(BUILT_IN_TOOL_MAP.keys())


def get_built_in_tool_by_id(in_code_tool_id: str) -> Type[BUILT_IN_TOOL_TYPES]:
    return BUILT_IN_TOOL_MAP[in_code_tool_id]


def _tool_llm_name(cls: Type[BUILT_IN_TOOL_TYPES]) -> str:
    """Extract the LLM-facing tool name from a tool class."""
    name_attr = cls.__dict__.get("name")
    if isinstance(name_attr, property) and name_attr.fget is not None:
        return name_attr.fget(cls)
    if isinstance(name_attr, str):
        return name_attr
    raise ValueError(
        f"Built-in tool {cls.__name__} must define a valid LLM-facing tool name"
    )


def _build_tool_name_to_class() -> dict[str, Type[BUILT_IN_TOOL_TYPES]]:
    """Build a mapping from LLM-facing tool name to tool class."""
    return {_tool_llm_name(cls): cls for cls in BUILT_IN_TOOL_MAP.values()}


TOOL_NAME_TO_CLASS: dict[str, Type[BUILT_IN_TOOL_TYPES]] = _build_tool_name_to_class()

_IN_CODE_TOOL_ID_TO_LLM_NAME: dict[str, str] = {
    in_code_tool_id: _tool_llm_name(cls)
    for in_code_tool_id, cls in BUILT_IN_TOOL_MAP.items()
}


def llm_tool_name(in_code_tool_id: str | None, db_name: str) -> str:
    """LLM-facing name for a tool table row.

    For built-in tools the class constant is the source of truth: the DB name
    column is seeded once by migration and may lag code renames (e.g. the
    Code Interpreter's "python" -> "run_python" rename after OpenAI reserved
    the name "python"). Custom/MCP tools have no in-code class, so their DB
    name is authoritative.
    """
    if in_code_tool_id is not None:
        llm_name = _IN_CODE_TOOL_ID_TO_LLM_NAME.get(in_code_tool_id)
        if llm_name is not None:
            return llm_name
    return db_name
