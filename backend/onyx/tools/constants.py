"""Tool names, IDs, and invocation limits."""

# Tool names as referenced by tool results / tool calls
SEARCH_TOOL_NAME = "run_search"
INTERNET_SEARCH_TOOL_NAME = "run_internet_search"
IMAGE_GENERATION_TOOL_NAME = "run_image_generation"
PYTHON_TOOL_NAME = "run_python"
OPEN_URL_TOOL_NAME = "open_url"

# In-code tool IDs that also correspond to the tool's name when associated with a persona
SEARCH_TOOL_ID = "SearchTool"
IMAGE_GENERATION_TOOL_ID = "ImageGenerationTool"
WEB_SEARCH_TOOL_ID = "WebSearchTool"
PYTHON_TOOL_ID = "PythonTool"
OPEN_URL_TOOL_ID = "OpenURLTool"
FILE_READER_TOOL_ID = "FileReaderTool"
MEMORY_TOOL_ID = "MemoryTool"

# Tool names as referenced by tool results / tool calls (read_file)
FILE_READER_TOOL_NAME = "read_file"

CODE_MODE_TOOL_NAME = "execute_code"
WAIT_CODE_TOOL_NAME = "wait_code"
SPAWN_AGENT_TOOL_NAME = "spawn_agent"
SEND_MESSAGE_TOOL_NAME = "send_message"
WAIT_AGENTS_TOOL_NAME = "wait_agents"
SKILLS_LIST_TOOL_NAME = "skills_list"
SKILLS_READ_TOOL_NAME = "skills_read"
SKILL_TOOL_NAMES = frozenset({SKILLS_LIST_TOOL_NAME, SKILLS_READ_TOOL_NAME})
# The question tool's name: the first for Claude models, the second for others.
ASK_USER_QUESTION_TOOL_NAME = "ask_user_question"
REQUEST_USER_INPUT_TOOL_NAME = "request_user_input"
QUESTION_TOOL_NAMES = frozenset(
    {ASK_USER_QUESTION_TOOL_NAME, REQUEST_USER_INPUT_TOOL_NAME}
)

INTERNAL_SEARCH_TOOL_NAME = "internal_search"
WEB_SEARCH_TOOL_NAME = "web_search"
POSTGRES_TOOL_NAME = "postgres_query"

CITEABLE_TOOLS_NAMES: list[str] = [
    INTERNAL_SEARCH_TOOL_NAME,
    WEB_SEARCH_TOOL_NAME,
    OPEN_URL_TOOL_NAME,
    POSTGRES_TOOL_NAME,
]

FILE_READER_MAX_CHARS = 16000

# The model's cut of a tool's output (code mode cells, exec_command and
# write_stdin, argument `max_output_chars`): the default and the most.
DEFAULT_MAX_OUTPUT_CHARS = 40_000
MAX_OUTPUT_CHARS = 160_000
MAX_OUTPUT_CHARS_DESCRIPTION = (
    "Character budget for the output this call returns; longer output is cut in "
    f"the middle. Defaults to {DEFAULT_MAX_OUTPUT_CHARS} characters, at most "
    f"{MAX_OUTPUT_CHARS}."
)
