"""Tool names, IDs, and invocation limits."""

from onyx.llm.constants import APPROX_CHARS_PER_TOKEN

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

# The code mode run and wait tools of each shape (code_mode/shapes.py).
EXEC_TOOL_NAME = "exec"
WAIT_TOOL_NAME = "wait"
REPL_TOOL_NAME = "repl"
POLL_TOOL_NAME = "poll"
# The tool type that clients know the streamed code of a code mode run call
# of every shape by (web and mobile `CODE_MODE_TOOL_TYPE`).
CODE_MODE_STREAM_TOOL_TYPE = "execute_code"
SPAWN_AGENT_TOOL_NAME = "spawn_agent"
SEND_MESSAGE_TOOL_NAME = "send_message"
WAIT_AGENTS_TOOL_NAME = "wait_agents"
SKILLS_LIST_TOOL_NAME = "skills_list"
SKILLS_READ_TOOL_NAME = "skills_read"
LOAD_SKILL_TOOL_NAME = "load_skill"
SKILL_TOOL_NAMES = frozenset({SKILLS_LIST_TOOL_NAME, SKILLS_READ_TOOL_NAME})
ASK_USER_QUESTION_TOOL_NAME = "ask_user_question"
REQUEST_USER_INPUT_TOOL_NAME = "request_user_input"

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

# The model's cut of a tool's output in characters (code mode cells, and the
# `max_output_chars` argument of exec_command and write_stdin): the default
# and the most.
DEFAULT_MAX_OUTPUT_CHARS = 40_000
MAX_OUTPUT_CHARS = 160_000
MAX_OUTPUT_CHARS_DESCRIPTION = (
    "Character budget for the output this call returns; longer output is cut in "
    f"the middle. Defaults to {DEFAULT_MAX_OUTPUT_CHARS} characters, at most "
    f"{MAX_OUTPUT_CHARS}."
)
# The same cut in tokens, for arguments that take it in tokens
# (`output_chars_from_tokens` converts it).
DEFAULT_MAX_OUTPUT_TOKENS = DEFAULT_MAX_OUTPUT_CHARS // APPROX_CHARS_PER_TOKEN
MAX_OUTPUT_TOKENS_DESCRIPTION = (
    "Token budget for the output this call returns; longer output is cut in the "
    f"middle. Defaults to {DEFAULT_MAX_OUTPUT_TOKENS} tokens, at most "
    f"{MAX_OUTPUT_CHARS // APPROX_CHARS_PER_TOKEN}."
)
