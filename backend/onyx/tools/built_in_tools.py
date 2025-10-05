from typing import Type
from typing import Union

from agents import FunctionTool

from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.okta_profile.okta_profile_tool import (
    OktaProfileTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)
from onyx.tools.tool_implementations_v2.image_generation import image_generation_tool
from onyx.tools.tool_implementations_v2.internal_search import internal_search_tool
from onyx.tools.tool_implementations_v2.okta_profile import okta_profile_tool
from onyx.tools.tool_implementations_v2.web import web_fetch_tool
from onyx.tools.tool_implementations_v2.web import web_search_tool
from onyx.utils.logger import setup_logger

logger = setup_logger()


BUILT_IN_TOOL_TYPES = Union[
    SearchTool, ImageGenerationTool, WebSearchTool, KnowledgeGraphTool, OktaProfileTool
]

# same as d09fc20a3c66_seed_builtin_tools.py
BUILT_IN_TOOL_MAP: dict[str, Type[BUILT_IN_TOOL_TYPES]] = {
    SearchTool.__name__: SearchTool,
    ImageGenerationTool.__name__: ImageGenerationTool,
    WebSearchTool.__name__: WebSearchTool,
    KnowledgeGraphTool.__name__: KnowledgeGraphTool,
    OktaProfileTool.__name__: OktaProfileTool,
}

BUILT_IN_TOOL_MAP_V2: dict[str, list[FunctionTool]] = {
    SearchTool.__name__: [internal_search_tool],
    ImageGenerationTool.__name__: [image_generation_tool],
    WebSearchTool.__name__: [web_search_tool, web_fetch_tool],
    # KnowledgeGraphTool.__name__: KnowledgeGraphTool.run,
    OktaProfileTool.__name__: [okta_profile_tool],
}


def get_built_in_tool_ids() -> list[str]:
    return list(BUILT_IN_TOOL_MAP.keys())


def get_built_in_tool_by_id(in_code_tool_id: str) -> Type[BUILT_IN_TOOL_TYPES]:
    return BUILT_IN_TOOL_MAP[in_code_tool_id]
