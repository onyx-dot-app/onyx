from onyx.deep_research.tool_definitions import THINK_TOOL_NAME
from onyx.llm.models import ToolDefinition

CODING_AGENT_IN_CODE_ID = "CodingAgent"
CODING_AGENT_TOOL_NAME = "coding_agent"
CODING_AGENT_QUERY_KEY = "query"
CODING_AGENT_REPO_KEY = "github_repo"

BASH_TOOL_NAME = "bash"
BASH_TOOL_CMD_KEY = "cmd"


GENERATE_ANSWER_TOOL_NAME = "generate_answer"


BASH_TOOL_DESCRIPTION: ToolDefinition = ToolDefinition(
    name=BASH_TOOL_NAME,
    description=(
        "Run a bash command in the sandboxed session containing the "
        "checked-out repository. The session has no network access. "
        "Use commands like `ls`, `cat`, `grep -r`, `find`, `wc -l`, "
        "etc. to inspect the code. Filesystem state persists across "
        "calls within the same session."
    ),
    strict=True,
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            BASH_TOOL_CMD_KEY: {
                "type": "string",
                "description": "Bash command to execute.",
            },
        },
        "required": [BASH_TOOL_CMD_KEY],
    },
)


GENERATE_ANSWER_TOOL_DESCRIPTION: ToolDefinition = ToolDefinition(
    name=GENERATE_ANSWER_TOOL_NAME,
    description=(
        "Produce the final text answer to the user's query. Call this "
        "once you have gathered enough information from the repository "
        "to answer comprehensively. After this call no further tool "
        "calls are made."
    ),
    strict=True,
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    },
)


CODING_AGENT_THINK_TOOL_DESCRIPTION: ToolDefinition = ToolDefinition(
    name=THINK_TOOL_NAME,
    description=(
        "Use this for reasoning between bash calls. Reflect on what you "
        "have learned about the codebase, identify knowledge gaps, and "
        "plan the next set of bash commands."
    ),
    strict=True,
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "Your chain of thought reasoning.",
            }
        },
        "required": ["reasoning"],
    },
)
