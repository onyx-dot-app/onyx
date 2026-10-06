# ruff: noqa: E501, W605 start
# If there are any tools, this section is included, the sections below are for the available tools
TOOL_SECTION_HEADER = "\n# Tools\n\n"


# This section is included if there are search type tools, currently internal_search and web_search
TOOL_DESCRIPTION_SEARCH_GUIDANCE = """
Search tools answer questions outside current knowledge: time-sensitive topics, niche specifics, and documents the user references. \
Prefer searching when unsure; do not repeat queries already run in this chat.
""".lstrip()


INTERNAL_SEARCH_GUIDANCE = """
## internal_search
Searches connected applications for organization-internal information: team, project, and process knowledge, keyword-heavy queries, and facts not in public sources. \
At most 3 queries per call.
""".lstrip()


WEB_SEARCH_GUIDANCE = """
## web_search
Fetches current public web content: fast-moving topics and facts where staleness is costly.{site_colon_disabled}
""".lstrip()

WEB_SEARCH_SITE_DISABLED_GUIDANCE = """
Do not use the "site:" operator in your web search queries.
""".lstrip()


OPEN_URLS_GUIDANCE = """
## open_url
Reads full web pages by URL, not image files: the most promising results of a web_search, or URLs the user provides. Accepts multiple URLs per call.
""".lstrip()

PYTHON_TOOL_GUIDANCE = """
## run_python
Executes Python in an isolated sandbox (60s timeout, no internet). Uploaded files are in the current directory; files saved there return a `file_link` for downloads or inline images. \
Libraries include numpy, pandas, scipy, matplotlib, PIL, and openpyxl. Each call is a fresh sandbox: state and files do not persist between calls, so batch multi-step work into one script. \
The sandbox fonts cannot shape Arabic or render CJK, so write rendered text in English for those languages.
""".lstrip()

GENERATE_IMAGE_GUIDANCE = """
## generate_image
Generates images only when the user requests one. To edit an existing image, pass its file_id from `[attached image — file_id: <id>]` tags or prior tool results in `reference_image_file_ids`.
""".lstrip()

MEMORY_GUIDANCE = """
## add_memory
Stores user-shared facts for future conversations: enduring preferences, long-term goals, stable constraints, and explicit "remember this" requests.
""".lstrip()

TOOL_CALL_FAILURE_PROMPT = """
LLM attempted to call a tool but failed. Most likely the tool name or arguments were misspelled.
""".strip()
# ruff: noqa: E501, W605 end
