from collections.abc import Generator

from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langchain_core.messages import ToolCall

from onyx.chat.models import ResponsePart
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.prompt_builder.answer_prompt_builder import LLMCall
from onyx.chat.prompt_builder.schemas import PromptSnapshot
from onyx.llm.interfaces import LLM
from onyx.tools.force import ForceUseTool
from onyx.tools.message import build_tool_message
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolCallFinalResult
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_runner import (
    check_which_tools_should_run_for_non_tool_calling_llm,
)
from onyx.tools.tool_runner import ToolRunner
from onyx.tools.tool_selection import select_single_tool_for_non_tool_calling_llm
from onyx.utils.logger import setup_logger


logger = setup_logger()


def get_tool_by_name(tools: list[Tool], tool_name: str) -> Tool:
    for tool in tools:
        if tool.name == tool_name:
            return tool
    raise RuntimeError(f"Tool '{tool_name}' not found")


class ToolResponseHandler:
    def __init__(self, tools: list[Tool]):
        self.tools = tools

        self.tool_call_chunk: AIMessageChunk | None = None
        self.tool_call_requests: list[ToolCall] = []

        self.tool_runner: ToolRunner | None = None
        self.tool_call_summary: ToolCallSummary | None = None

        self.tool_kickoff: ToolCallKickoff | None = None
        self.tool_responses: list[ToolResponse] = []
        self.tool_final_result: ToolCallFinalResult | None = None

    @classmethod
    def get_tool_call_for_non_tool_calling_llm(
        cls, llm_call: LLMCall, llm: LLM
    ) -> tuple[Tool, dict] | None:
        return get_tool_call_for_non_tool_calling_llm_impl(
            force_use_tool=llm_call.force_use_tool,
            tools=llm_call.tools,
            prompt_builder=llm_call.prompt_builder,
            llm=llm,
        )

    def _handle_tool_call(self) -> Generator[ResponsePart, None, None]:
        if not self.tool_call_chunk or not self.tool_call_chunk.tool_calls:
            return

        self.tool_call_requests = self.tool_call_chunk.tool_calls

        selected_tool: Tool | None = None
        selected_tool_call_request: ToolCall | None = None
        for tool_call_request in self.tool_call_requests:
            known_tools_by_name = [
                tool for tool in self.tools if tool.name == tool_call_request["name"]
            ]

            if known_tools_by_name:
                selected_tool = known_tools_by_name[0]
                selected_tool_call_request = tool_call_request
                break

            logger.error(
                "Tool call requested with unknown name field. \n"
                f"self.tools: {self.tools}"
                f"tool_call_request: {tool_call_request}"
            )

        if not selected_tool or not selected_tool_call_request:
            return

        logger.info(f"Selected tool: {selected_tool.name}")
        logger.debug(f"Selected tool call request: {selected_tool_call_request}")
        self.tool_runner = ToolRunner(selected_tool, selected_tool_call_request["args"])
        self.tool_kickoff = self.tool_runner.kickoff()
        yield self.tool_kickoff

        for response in self.tool_runner.tool_responses():
            self.tool_responses.append(response)
            yield response

        self.tool_final_result = self.tool_runner.tool_final_result()
        yield self.tool_final_result

        self.tool_call_summary = ToolCallSummary(
            tool_call_request=self.tool_call_chunk,
            tool_call_result=build_tool_message(
                selected_tool_call_request, self.tool_runner.tool_message_content()
            ),
        )

    def handle_response_part(
        self,
        response_item: BaseMessage | str | None,
        previous_response_items: list[BaseMessage | str],
    ) -> Generator[ResponsePart, None, None]:
        if response_item is None:
            yield from self._handle_tool_call()

        if isinstance(response_item, AIMessageChunk) and (
            response_item.tool_call_chunks or response_item.tool_calls
        ):
            if self.tool_call_chunk is None:
                self.tool_call_chunk = response_item
            else:
                self.tool_call_chunk += response_item  # type: ignore

    def next_llm_call(self, current_llm_call: LLMCall) -> LLMCall | None:
        if (
            self.tool_runner is None
            or self.tool_call_summary is None
            or self.tool_kickoff is None
            or self.tool_final_result is None
        ):
            return None

        tool_runner = self.tool_runner
        new_prompt_builder = tool_runner.tool.build_next_prompt(
            prompt_builder=current_llm_call.prompt_builder,
            tool_call_summary=self.tool_call_summary,
            tool_responses=self.tool_responses,
            using_tool_calling_llm=current_llm_call.using_tool_calling_llm,
        )
        return LLMCall(
            prompt_builder=new_prompt_builder,
            tools=[],  # for now, only allow one tool call per response
            force_use_tool=ForceUseTool(
                force_use=False,
                tool_name="",
                args=None,
            ),
            files=current_llm_call.files,
            using_tool_calling_llm=current_llm_call.using_tool_calling_llm,
            tool_call_info=[
                self.tool_kickoff,
                *self.tool_responses,
                self.tool_final_result,
            ],
        )


def get_tool_call_for_non_tool_calling_llm_impl(
    force_use_tool: ForceUseTool,
    tools: list[Tool],
    prompt_builder: AnswerPromptBuilder | PromptSnapshot,
    llm: LLM,
) -> tuple[Tool, dict] | None:
    user_query = prompt_builder.raw_user_query
    history = prompt_builder.raw_message_history
    if isinstance(prompt_builder, AnswerPromptBuilder):
        history = prompt_builder.get_message_history()

    if force_use_tool.force_use:
        # if we are forcing a tool, we don't need to check which tools to run
        tool = get_tool_by_name(tools, force_use_tool.tool_name)

        tool_args = (
            force_use_tool.args
            if force_use_tool.args is not None
            else tool.get_args_for_non_tool_calling_llm(
                query=user_query,
                history=history,
                llm=llm,
                force_run=True,
            )
        )

        if tool_args is None:
            raise RuntimeError(f"Tool '{tool.name}' did not return args")

        # If we have override_kwargs, add them to the tool_args
        if force_use_tool.override_kwargs is not None:
            tool_args["override_kwargs"] = force_use_tool.override_kwargs

        return (tool, tool_args)
    else:
        tool_options = check_which_tools_should_run_for_non_tool_calling_llm(
            tools=tools,
            query=user_query,
            history=history,
            llm=llm,
        )

        available_tools_and_args = [
            (tools[ind], args)
            for ind, args in enumerate(tool_options)
            if args is not None
        ]

        logger.info(
            f"Selecting single tool from tools: {[(tool.name, args) for tool, args in available_tools_and_args]}"
        )

        chosen_tool_and_args = (
            select_single_tool_for_non_tool_calling_llm(
                tools_and_args=available_tools_and_args,
                history=history,
                query=user_query,
                llm=llm,
            )
            if available_tools_and_args
            else None
        )

        logger.notice(f"Chosen tool: {chosen_tool_and_args}")
        return chosen_tool_and_args
