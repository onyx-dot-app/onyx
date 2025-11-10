from collections.abc import Iterator
from collections.abc import Sequence

from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.tools.tool import Tool


def query(
    llm_with_default_settings: LLM,
    messages: list[dict],
    tools: Sequence[Tool],
    tool_choice: ToolChoiceOptions | None = None,
) -> Iterator[str]:
    tool_definitions = [tool.tool_definition() for tool in tools]

    for chunk in llm_with_default_settings.stream(
        prompt=messages,
        tools=tool_definitions,
        tool_choice=tool_choice,
    ):
        yield chunk
