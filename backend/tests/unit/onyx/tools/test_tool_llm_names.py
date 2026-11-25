"""Guards the tool names that OpenAI-family models get against OpenAI's
reserved function names.

OpenAI rejects any request whose tools array defines one of them (400
invalid_request_error: "The function name 'python' is reserved for use by this
model."). A collision breaks every chat that offers the tool to a GPT model
served via api.openai.com.
"""

from onyx.llm.model_capabilities import ToolFamily
from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP
from onyx.tools.constants import (
    SEND_MESSAGE_TOOL_NAME,
    SKILLS_LIST_TOOL_NAME,
    WRITE_STDIN_TOOL_NAME,
)
from onyx.tools.tool_implementations.code_mode.shapes import CODE_MODE_SHAPES
from onyx.tools.tool_implementations.open_url.open_url_tool import OPEN_URL_SHAPES
from onyx.tools.tool_implementations.question.shapes import QUESTION_SHAPES
from onyx.tools.tool_implementations.sandbox.sandbox_tools import SANDBOX_TOOLS
from onyx.tools.tool_implementations.skills.skill_tools import SKILL_READ_SHAPES
from onyx.tools.tool_implementations.subagents.shapes import AGENT_SHAPES
from onyx.tools.tool_implementations.subagents.subagent_tools import (
    InterruptAgentTool,
    ListAgentsTool,
)

# Names OpenAI is known to reserve. Extend if OpenAI reserves more of its
# harness tool names and starts rejecting them.
OPENAI_RESERVED_FUNCTION_NAMES = {"python"}


def test_openai_family_tool_names_avoid_openai_reserved_names() -> None:
    family = ToolFamily.OPENAI
    code_mode = CODE_MODE_SHAPES[family]
    agents = AGENT_SHAPES[family]
    sandbox = SANDBOX_TOOLS[family]
    # Tools that a shape names have no NAME of their own.
    class_names = (
        getattr(tool, "NAME", None)  # ods: ignore[getattr] shape-named tools have none
        for tool in (*BUILT_IN_TOOL_MAP.values(), *sandbox.tools)
    )
    names = {
        *(name for name in class_names if isinstance(name, str)),
        sandbox.shell.name,
        WRITE_STDIN_TOOL_NAME,
        code_mode.run_name,
        code_mode.wait_name,
        QUESTION_SHAPES[family].name,
        SKILL_READ_SHAPES[family].name,
        SKILLS_LIST_TOOL_NAME,
        OPEN_URL_SHAPES[family].name,
        agents.spawn_name,
        SEND_MESSAGE_TOOL_NAME,
        ListAgentsTool.name,
        InterruptAgentTool.name,
        *([agents.wait_name] if agents.wait_name is not None else []),
    }
    assert not names & OPENAI_RESERVED_FUNCTION_NAMES, (
        "An OpenAI-family tool name collides with an OpenAI-reserved function "
        "name; OpenAI rejects requests that define it. Rename the tool."
    )
