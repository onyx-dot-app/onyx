from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME

CODING_AGENT_IN_CODE_ID = "CodingAgent"
CODING_AGENT_TOOL_NAME = "coding_agent"
CODING_AGENT_QUERY_KEY = "query"
CODING_AGENT_REPO_KEY = "github_repo"
CODING_AGENT_REF_KEY = "ref"

BASH_TOOL_NAME = "bash"
BASH_TOOL_CMD_KEY = "cmd"


GENERATE_ANSWER_TOOL_NAME = "generate_answer"


CODING_AGENT_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": CODING_AGENT_TOOL_NAME,
        "description": (
            "Deep investigation of a GitHub repository. The agent extracts a "
            "tarball of the repo at one revision into an isolated sandbox "
            "(no .git metadata — git commands are unavailable) and explores "
            "the source tree with shell commands before returning a text "
            "answer. This is a "
            "slow, expensive multi-step agent run (tens of seconds to "
            "minutes). Use it only when the question needs cross-file "
            "tracing, verification against the exact current code, or "
            "analysis the code search index cannot provide. Do NOT use it "
            "for simple lookups the internal search tool already answers "
            "(where something is defined, a config default, what one "
            "function does)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                CODING_AGENT_QUERY_KEY: {
                    "type": "string",
                    "description": (
                        "The user's question or task to perform against the repository."
                    ),
                },
                CODING_AGENT_REPO_KEY: {
                    "type": "string",
                    "description": (
                        "GitHub repository URL or 'owner/repo' identifier "
                        "(e.g. 'https://github.com/onyx-dot-app/onyx' or "
                        "'onyx-dot-app/onyx')."
                    ),
                },
                CODING_AGENT_REF_KEY: {
                    "type": "string",
                    "description": (
                        "Optional branch or commit SHA to analyze. Defaults "
                        "to the latest default-branch state. Pass the commit "
                        "SHA from retrieved code chunks when the answer must "
                        "match the indexed revision."
                    ),
                },
            },
            "required": [CODING_AGENT_QUERY_KEY, CODING_AGENT_REPO_KEY],
        },
    },
}


BASH_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": BASH_TOOL_NAME,
        "description": (
            "Run a bash command in the sandboxed session containing the "
            "checked-out repository. The session has no network access. "
            "Use commands like `ls`, `cat`, `grep -r`, `find`, `wc -l`, "
            "etc. to inspect the code. Filesystem state persists across "
            "calls within the same session."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                BASH_TOOL_CMD_KEY: {
                    "type": "string",
                    "description": "Bash command to execute.",
                },
            },
            "required": [BASH_TOOL_CMD_KEY],
        },
    },
}


GENERATE_ANSWER_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": GENERATE_ANSWER_TOOL_NAME,
        "description": (
            "Produce the final text answer to the user's query. Call this "
            "once you have gathered enough information from the repository "
            "to answer comprehensively. After this call no further tool "
            "calls are made."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


CODING_AGENT_THINK_TOOL_DESCRIPTION = {
    "type": "function",
    "function": {
        "name": THINK_TOOL_NAME,
        "description": (
            "Use this for reasoning between bash calls. Reflect on what you "
            "have learned about the codebase, identify knowledge gaps, and "
            "plan the next set of bash commands."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Your chain of thought reasoning.",
                }
            },
            "required": ["reasoning"],
        },
    },
}


def get_coding_agent_tool_definitions(include_think_tool: bool) -> list[dict]:
    tools = [
        BASH_TOOL_DESCRIPTION,
        GENERATE_ANSWER_TOOL_DESCRIPTION,
    ]
    if include_think_tool:
        tools.append(CODING_AGENT_THINK_TOOL_DESCRIPTION)
    return tools
