from agents import FunctionTool

from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
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

BUILT_IN_TOOL_MAP_V2: dict[str, list[FunctionTool]] = {
    SearchTool.__name__: [internal_search_tool],
    ImageGenerationTool.__name__: [image_generation_tool],
    WebSearchTool.__name__: [web_search_tool, web_fetch_tool],
    OktaProfileTool.__name__: [okta_profile_tool],
}
