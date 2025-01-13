from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator

from langchain_core.messages import BaseMessage

from onyx.chat.models import ResponsePart
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.prompt_builder.build import LLMCall
from onyx.chat.stream_processing.answer_response_handler import AnswerResponseHandler
from onyx.chat.tool_handling.tool_response_handler import ToolResponseHandler


class LLMResponseHandlerManager:
    def __init__(
        self,
        tool_handler: ToolResponseHandler,
        answer_handler: AnswerResponseHandler,
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
