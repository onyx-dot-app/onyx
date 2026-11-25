GENERATE_PLAN_TOOL_NAME = "generate_plan"


GENERATE_REPORT_TOOL_NAME = "generate_report"


RESEARCH_AGENT_TOOL_NAME = "research_agent"


# ruff: noqa: E501, W605 start

# The research agent's tool definitions show only each tool's summary, so its
# prompt carries the tools' guidance.
INTERNAL_SEARCH_TOOL_DESCRIPTION = """
## internal_search
Use the `internal_search` tool to search connected applications for information. Some examples of when to use `internal_search` include:
- Internal information: any time where there may be some information stored in internal applications that could help better answer the query.
- Niche/Specific information: information that is likely not found in public sources, things specific to a project or product, team, process, etc.
- Keyword Queries: queries that are heavily keyword based are often internal document search queries.
- Ambiguity: questions about something that is not widely known or understood.
""".lstrip()

# Hard for the URL reading tool to be called for a ton of search results all at once so limit to 3
WEB_SEARCH_TOOL_DESCRIPTION = """

## web_search
Use the `web_search` tool to get search results from the web. You should use this tool to get context for your research. These should be optimized for search engines like Google. \
Use concise and specific queries and avoid merging multiple queries into one. You can call web_search with multiple queries at once (3 max) but generally only do this when there is a clear opportunity for parallel searching. \
If you use multiple queries, ensure that the queries are related in topic but not similar such that the results would be redundant.
"""

# This one is mostly similar to the one for the main flow but there won't be any user specified URLs to open.
# `{name}` is the URL reading tool's name in the model's tool family.
OPEN_URLS_TOOL_DESCRIPTION = """

## {name}
Use the `{name}` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your searches. \
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources. \
You should almost always use {name} after a web_search call.
"""

# NOTE: Internal search tool uses the same description as the default flow, not duplicating here.

# ruff: noqa: E501, W605 end
