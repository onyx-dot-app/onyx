GENERATE_PLAN_TOOL_NAME = "generate_plan"


GENERATE_REPORT_TOOL_NAME = "generate_report"


RESEARCH_AGENT_TOOL_NAME = "research_agent"


# This is to ensure that even the non-reasoning models can have an ok time with this more complex flow.
THINK_TOOL_NAME = "think_tool"


# ruff: noqa: E501, W605 start

# Hard for the open_url tool to be called for a ton of search results all at once so limit to 3
WEB_SEARCH_TOOL_DESCRIPTION = """

## web_search
Use the `web_search` tool to get search results from the web. You should use this tool to get context for your research. These should be optimized for search engines like Google. \
Use concise and specific queries and avoid merging multiple queries into one. You can call web_search with multiple queries at once (3 max) but generally only do this when there is a clear opportunity for parallel searching. \
If you use multiple queries, ensure that the queries are related in topic but not similar such that the results would be redundant.
"""

# This one is mostly similar to the one for the main flow but there won't be any user specified URLs to open.
OPEN_URLS_TOOL_DESCRIPTION = f"""

## open_urls
Use the `open_urls` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your searches. \
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources. \
You should almost always use open_urls after a web_search call and sometimes after reasoning with the {THINK_TOOL_NAME} tool.
"""

OPEN_URLS_TOOL_DESCRIPTION_REASONING = """

## open_urls
Use the `open_urls` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your searches. \
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources. \
You should almost always use open_urls after a web_search call.
"""

# NOTE: Internal search tool uses the same description as the default flow, not duplicating here.

# ruff: noqa: E501, W605 end
