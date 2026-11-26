"""Tool names, IDs, and invocation limits."""

from onyx.llm.constants import APPROX_CHARS_PER_TOKEN

# Tool names as referenced by tool results / tool calls
PYTHON_TOOL_NAME = "run_python"
# The URL reading tool's names (open_url/open_url_tool.py OPEN_URL_SHAPES).
# Its tool row keeps the name open_url whatever the model calls it.
OPEN_URL_TOOL_NAME = "open_url"
WEB_FETCH_TOOL_NAME = "web_fetch"

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

# The code mode run tool of every shape, and the wait tool of each shape
# (code_mode/shapes.py). Clients know the run tool's streamed code by its name
# (web and mobile `CODE_MODE_TOOL_TYPE`).
EXECUTE_CODE_TOOL_NAME = "execute_code"
WAIT_TOOL_NAME = "wait"
POLL_TOOL_NAME = "poll"
# The shell tools of each shape (sandbox/shapes.py SHELL_SHAPES).
EXEC_COMMAND_TOOL_NAME = "exec_command"
BASH_TOOL_NAME = "bash"
WRITE_STDIN_TOOL_NAME = "write_stdin"
# The agent tools of each shape (subagents/shapes.py AGENT_SHAPES).
SPAWN_AGENT_TOOL_NAME = "spawn_agent"
AGENT_TOOL_NAME = "agent"
SEND_MESSAGE_TOOL_NAME = "send_message"
WAIT_AGENT_TOOL_NAME = "wait_agent"
# The skill tools of each shape (skills/skill_tools.py SKILL_READ_SHAPES).
SKILLS_LIST_TOOL_NAME = "skills_list"
SKILLS_READ_TOOL_NAME = "skills_read"
SKILL_TOOL_NAME = "skill"
LOAD_SKILL_TOOL_NAME = "load_skill"
ASK_USER_QUESTION_TOOL_NAME = "ask_user_question"
REQUEST_USER_INPUT_TOOL_NAME = "request_user_input"

INTERNAL_SEARCH_TOOL_NAME = "internal_search"
WEB_SEARCH_TOOL_NAME = "web_search"
POSTGRES_TOOL_NAME = "postgres_query"

FILE_READER_MAX_CHARS = 16000

# The model's cut of a tool's output in characters (code mode cells and the
# shell tools): the default and the most.
DEFAULT_MAX_OUTPUT_CHARS = 40_000
MAX_OUTPUT_CHARS = 160_000
# The same cut in tokens, for arguments that take it in tokens
# (`output_chars_from_tokens` converts it).
DEFAULT_MAX_OUTPUT_TOKENS = DEFAULT_MAX_OUTPUT_CHARS // APPROX_CHARS_PER_TOKEN
MAX_OUTPUT_TOKENS_DESCRIPTION = (
    "Token budget for the output this call returns; longer output is cut in the "
    f"middle. Defaults to {DEFAULT_MAX_OUTPUT_TOKENS} tokens, at most "
    f"{MAX_OUTPUT_CHARS // APPROX_CHARS_PER_TOKEN}."
)
