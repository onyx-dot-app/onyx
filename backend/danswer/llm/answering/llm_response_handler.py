from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage
from pydantic.v1 import BaseModel as BaseModel__v1

from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import DanswerQuotes
from danswer.chat.models import StreamStopInfo
from danswer.chat.models import StreamStopReason
from danswer.file_store.models import InMemoryChatFile
from danswer.llm.answering.prompts.build import AnswerPromptBuilder
from danswer.tools.force import ForceUseTool
from danswer.tools.models import ToolCallFinalResult
from danswer.tools.models import ToolCallKickoff
from danswer.tools.models import ToolResponse
from danswer.tools.tool import Tool


if TYPE_CHECKING:
    from danswer.llm.answering.stream_processing.answer_response_handler import (
        AnswerResponseHandler,
    )
    from danswer.llm.answering.tool.tool_response_handler import ToolResponseHandler


ResponsePart = (
    DanswerAnswerPiece
    | CitationInfo
    | DanswerQuotes
    | ToolCallKickoff
    | ToolResponse
    | ToolCallFinalResult
    | StreamStopInfo
)


class LLMCall(BaseModel__v1):
    prompt_builder: AnswerPromptBuilder
    tools: list[Tool]
    force_use_tool: ForceUseTool
    files: list[InMemoryChatFile]
    tool_call_info: list[ToolCallKickoff | ToolResponse | ToolCallFinalResult]
    using_tool_calling_llm: bool

    class Config:
        arbitrary_types_allowed = True


class LLMResponseHandlerManager:
    def __init__(
        self,
        tool_handler: "ToolResponseHandler",
        answer_handler: "AnswerResponseHandler",
        is_cancelled: Callable[[], bool],
    ):
        self.tool_handler = tool_handler
        self.answer_handler = answer_handler
        self.is_cancelled = is_cancelled

    def handle_llm_response(
        self,
        stream: Iterator[BaseMessage],
    ) -> Generator[ResponsePart, None, None]:
        all_messages: list[BaseMessage] = []
        for message in stream:
            if self.is_cancelled():
                yield StreamStopInfo(stop_reason=StreamStopReason.CANCELLED)
                return
            # tool handler doesn't do anything until the full message is received
            # NOTE: still need to run list() to get this to run
            list(self.tool_handler.handle_response_part(message, all_messages))
            yield from self.answer_handler.handle_response_part(message, all_messages)
            all_messages.append(message)

        # potentially give back all info on the selected tool call + its result
        yield from self.tool_handler.handle_response_part(None, all_messages)
        yield from self.answer_handler.handle_response_part(None, all_messages)

    def next_llm_call(self, llm_call: LLMCall) -> LLMCall | None:
        return self.tool_handler.next_llm_call(llm_call)
