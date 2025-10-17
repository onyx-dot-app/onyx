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
from onyx.tools.tool_implementations_v2.image_generation import image_generation
from onyx.tools.tool_implementations_v2.internal_search import internal_search
from onyx.tools.tool_implementations_v2.okta_profile import okta_profile
from onyx.tools.tool_implementations_v2.web import open_url
from onyx.tools.tool_implementations_v2.web import web_search

BUILT_IN_TOOL_MAP_V2: dict[str, list[FunctionTool]] = {
    SearchTool.__name__: [internal_search],
    ImageGenerationTool.__name__: [image_generation],
    WebSearchTool.__name__: [web_search, open_url],
    OktaProfileTool.__name__: [okta_profile],
}
