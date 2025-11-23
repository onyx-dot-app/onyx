from typing import TypeVar

from onyx.chat.infra import Emitter
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import SearchToolRunContext
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_tool import SearchTool


R = TypeVar("R")
C = TypeVar("C")

# TODO clean this up
# to be removed
# class ToolRunner(Generic[R, C]):
#     def __init__(
#         self, tool: Tool[R, C], args: dict[str, Any], override_kwargs: R | None = None
#     ):
#         self.tool = tool
#         self.args = args
#         self.override_kwargs = override_kwargs
#
#         self._tool_responses: list[ToolResponse] | None = None
#
#     def kickoff(self) -> ToolCallKickoff:
#         return ToolCallKickoff(tool_name=self.tool.name, tool_args=self.args, tool_call_id=uuid.uuid4())
#
#     def tool_responses(self) -> Generator[ToolResponse, None, None]:
#         if self._tool_responses is not None:
#             yield from self._tool_responses
#             return
#
#         tool_responses: list[ToolResponse] = []
#         for tool_response in self.tool.run(
#             override_kwargs=self.override_kwargs, **self.args
#         ):
#             yield tool_response
#             tool_responses.append(tool_response)
#
#         self._tool_responses = tool_responses
#
#     def tool_message_content(self) -> str | list[str | dict[str, Any]]:
#         tool_responses = list(self.tool_responses())
#         return self.tool.get_llm_tool_response(*tool_responses)
#
#     def tool_final_result(self) -> ToolCallFinalResult:
#         return ToolCallFinalResult(
#             tool_name=self.tool.name,
#             tool_args=self.args,
#             tool_result=self.tool.get_final_result(*self.tool_responses()),
#         )


def run_tool_calls(
    tool_calls: list[ToolCallKickoff],
    tools: list[Tool],
    turn_index: int,
    # The stuff below is needed for the different individual built-in tools
    emitter: Emitter,
    message_history: list[ChatMessageSimple],
    memories: list[str] | None,
    user_info: str | None,
    starting_citation_num: int,
) -> list[ToolResponse]:
    # TODO parallelize this
    # TODO it should do tool call combination here, if multiple copies of the same tool are called
    # the tool args should just be combined.
    tools_by_name = {tool.name: tool for tool in tools}
    tool_responses: list[ToolResponse] = []

    for tool_call in tool_calls:
        tool = tools_by_name[tool_call.tool_name]

        # Emit the tool start packet before running the tool
        tool.emit_start(turn_index=turn_index)

        run_context = SearchToolRunContext(emitter=emitter)
        override_kwargs = None

        if isinstance(tool, SearchTool):
            minimal_history = [
                ChatMinimalTextMessage(
                    message=msg.message, message_type=msg.message_type
                )
                for msg in message_history
            ]
            last_user_message = None
            for i in range(len(minimal_history) - 1, -1, -1):
                if minimal_history[i].message_type == MessageType.USER:
                    last_user_message = minimal_history[i].message
                    break

            if last_user_message is None:
                raise ValueError("No user message found in message history")

            override_kwargs = SearchToolOverrideKwargs(
                starting_citation_num=starting_citation_num,
                original_query=last_user_message,
                message_history=minimal_history,
                memories=memories,
                user_info=user_info,
            )

        tool_response = tool.run(
            run_context=run_context,
            turn_index=turn_index,
            override_kwargs=override_kwargs,
            **tool_call.tool_args,
        )

        tool_responses.append(tool_response)

    return tool_responses
