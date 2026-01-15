# ruff: noqa: E501, W605 start
# If there are any tools, this section is included, the sections below are for the available tools
TOOL_SECTION_HEADER = "\n\n# Tools\n"


# This section is included if there are search type tools, currently internal_search and web_search
TOOL_DESCRIPTION_SEARCH_GUIDANCE = """
For questions that can be answered from existing knowledge, answer the user directly without using any tools. If you suspect your knowledge is outdated or for topics where things are rapidly changing, use search tools to get more context.

When using any search type tool, do not make any assumptions and stay as faithful to the user's query as possible. \
Between internal and web search (if both are available), think about if the user's query is likely better answered by team internal sources or online web pages. \
When searching for information, if the initial results cannot fully answer the user's query, try again with different tools or arguments. Do not repeat the same or very similar queries if it already has been run in the chat history.

If it is unclear which tool to use, consider using multiple in parallel to be efficient with time.
"""


INTERNAL_SEARCH_GUIDANCE = """

## internal_search
Use the `internal_search` tool to search connected applications for information. Some examples of when to use `internal_search` include:
- Internal information: any time where there may be some information stored in internal applications that could help better answer the query.
- Niche/Specific information: information that is likely not found in public sources, things specific to a project or product, team, process, etc.
- Keyword Queries: queries that are heavily keyword based are often internal document search queries.
- Ambiguity: questions about something that is not widely known or understood.
Never provide more than 3 queries at once to `internal_search`.
"""


WEB_SEARCH_GUIDANCE = """

## web_search
Use the `web_search` tool to access up-to-date information from the web. Some examples of when to use `web_search` include:
- Freshness: if up-to-date information on a topic could change or enhance the answer. Very important for topics that are changing or evolving.
- Niche Information: detailed info not widely known or understood (but that is likely found on the internet).
- Accuracy: if the cost of outdated information is high, use web sources directly.{site_colon_disabled}
"""

WEB_SEARCH_SITE_DISABLED_GUIDANCE = """
Do not use the "site:" operator in your web search queries.
""".rstrip()


OPEN_URLS_GUIDANCE = """

## open_url
Use the `open_url` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your searches.
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources.
You should almost always use open_url after a web_search call. Use this tool when a user asks about a specific provided URL.
"""

PYTHON_TOOL_GUIDANCE = """

## python
Use the `python` tool to execute Python code in an isolated sandbox. The tool will respond with the output of the execution or time out after 60.0 seconds.
Any files uploaded to the chat will be automatically be available in the execution environment's current directory. \
The current directory in the file system can be used to save and persist user files. Files written to the current directory will be returned with a `file_link`. \
Use this to give the user a way to download the file OR to display generated images.
Internet access for this session is disabled. Do not make external web requests or API calls as they will fail.
Use `openpyxl` to read and write Excel files. You have access to libraries like numpy, pandas, scipy, matplotlib, and PIL.
IMPORTANT: each call to this tool is independent. Variables from previous calls will NOT be available in the current call.
"""

GENERATE_IMAGE_GUIDANCE = """

## generate_image
NEVER use generate_image unless the user specifically requests an image.
"""

TOOL_CALL_FAILURE_PROMPT = """
LLM attempted to call a tool but failed. Most likely the tool name or arguments were misspelled.
""".strip()
# ruff: noqa: E501, W605 end
