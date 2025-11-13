from typing import cast
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from onyx.llm.utils import message_to_prompt_and_imgs
from onyx.tools.tool import Tool

if TYPE_CHECKING:
    from onyx.tools.tool_implementations.custom.custom_tool import (
        CustomToolCallSummary,
    )
    from onyx.tools.models import ToolResponse


def build_user_message_for_non_tool_calling_llm(
    message: HumanMessage,
    tool_name: str,
    *args: "ToolResponse",
) -> str:
    query, _ = message_to_prompt_and_imgs(message)

    tool_run_summary = cast("CustomToolCallSummary", args[0].response).tool_result
    return f"""
Here's the result from the {tool_name} tool:

{tool_run_summary}

Now respond to the following:

{query}
""".strip()


class BaseTool(Tool[None]):
    # Removed the v2 run method since we're consolidating
    pass
