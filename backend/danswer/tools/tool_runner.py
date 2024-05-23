from collections.abc import Generator
from typing import Any

from pydantic import BaseModel
from pydantic import root_validator

from danswer.llm.answering.models import PreviousMessage
from danswer.llm.interfaces import LLM
from danswer.tools.tool import Tool
from danswer.tools.tool import ToolResponse
from danswer.utils.threadpool_concurrency import run_functions_tuples_in_parallel


class ToolRunKickoff(BaseModel):
    tool_name: str
    tool_args: dict[str, Any]


class ToolRunnerResponse(BaseModel):
    tool_run_kickoff: ToolRunKickoff | None = None
    tool_response: ToolResponse | None = None
    tool_message_content: str | list[str | dict[str, Any]] | None = None

    @root_validator
    def validate_tool_runner_response(
        cls, values: dict[str, ToolResponse | str]
    ) -> dict[str, ToolResponse | str]:
        fields = ["tool_response", "tool_message_content", "tool_run_kickoff"]
        provided = sum(1 for field in fields if values.get(field) is not None)

        if provided != 1:
            raise ValueError(
                "Exactly one of 'tool_response', 'tool_message_content', "
                "or 'tool_run_kickoff' must be provided"
            )

        return values


class ToolRunner:
    def __init__(self, tool: Tool, args: dict[str, Any]):
        self.tool = tool
        self.args = args

        self._tool_responses: list[ToolResponse] | None = None

    def kickoff(self) -> ToolRunKickoff:
        return ToolRunKickoff(tool_name=self.tool.name(), tool_args=self.args)

    def tool_responses(self) -> Generator[ToolResponse, None, None]:
        if self._tool_responses is not None:
            yield from self._tool_responses

        tool_responses: list[ToolResponse] = []
        for tool_response in self.tool.run(**self.args):
            yield tool_response
            tool_responses.append(tool_response)

        self._tool_responses = tool_responses

    def tool_message_content(self) -> str | list[str | dict[str, Any]]:
        tool_responses = list(self.tool_responses())
        return self.tool.build_tool_message_content(*tool_responses)


def check_which_tools_should_run_for_non_tool_calling_llm(
    tools: list[Tool], query: str, history: list[PreviousMessage], llm: LLM
) -> list[dict[str, Any] | None]:
    tool_args_list = [
        (tool.get_args_for_non_tool_calling_llm, (query, history, llm))
        for tool in tools
    ]
    return run_functions_tuples_in_parallel(tool_args_list)
