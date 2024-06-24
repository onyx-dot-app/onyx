from typing import cast

from danswer.tools.custom.custom_tool import CustomToolCallSummary
from danswer.tools.models import ToolResponse


def build_user_message_for_custom_tool_for_non_tool_calling_llm(
    query: str,
    tool_name: str,
    *args: ToolResponse,
) -> str:
    tool_run_summary = cast(CustomToolCallSummary, args[0].response).tool_result
    return f"""
Here's the result from the {tool_name} tool:

{tool_run_summary}

Now respond to the following:

{query}
""".strip()
