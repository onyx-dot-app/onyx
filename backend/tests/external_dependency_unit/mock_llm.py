from __future__ import annotations

import abc
import threading
import time
from collections.abc import Generator
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from typing import Any
from typing import cast
from typing import Generic
from typing import Literal
from typing import TypeVar
from unittest.mock import patch

from pydantic import BaseModel

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ReasoningEffort
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import Delta
from onyx.llm.model_response import FunctionCall
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice

T = TypeVar("T")


class LLMResponseType(str, Enum):
    REASONING = "reasoning"
    ANSWER = "answer"
    TOOL_CALL = "tool_call"


class LLMResponse(abc.ABC, BaseModel):
    type: str = ""

    @abc.abstractmethod
    def num_tokens(self) -> int:
        raise NotImplementedError


class LLMReasoningResponse(LLMResponse):
    type: Literal["reasoning"] = LLMResponseType.REASONING.value
    reasoning_tokens: list[str]

    def num_tokens(self) -> int:
        return len(self.reasoning_tokens)


class LLMAnswerResponse(LLMResponse):
    type: Literal["answer"] = LLMResponseType.ANSWER.value
    answer_tokens: list[str]

    def num_tokens(self) -> int:
        return len(self.answer_tokens)


class LLMToolCallResponse(LLMResponse):
    type: Literal["tool_call"] = LLMResponseType.TOOL_CALL.value
    tool_name: str
    tool_call_id: str
    tool_call_argument_tokens: list[str]

    def num_tokens(self) -> int:
        return (
            len(self.tool_call_argument_tokens) + 1
        )  # +1 for the tool_call_id and tool_name


class StreamItem(BaseModel):
    """Represents a single item in the mock LLM stream with its type."""

    response_type: LLMResponseType
    data: Any


def _response_to_stream_items(response: LLMResponse) -> list[StreamItem]:
    match LLMResponseType(response.type):
        case LLMResponseType.REASONING:
            response = cast(LLMReasoningResponse, response)
            return [
                StreamItem(
                    response_type=LLMResponseType.REASONING,
                    data=token,
                )
                for token in response.reasoning_tokens
            ]
        case LLMResponseType.ANSWER:
            response = cast(LLMAnswerResponse, response)
            return [
                StreamItem(
                    response_type=LLMResponseType.ANSWER,
                    data=token,
                )
                for token in response.answer_tokens
            ]
        case LLMResponseType.TOOL_CALL:
            response = cast(LLMToolCallResponse, response)
            return [
                StreamItem(
                    response_type=LLMResponseType.TOOL_CALL,
                    data={
                        "tool_call_id": response.tool_call_id,
                        "tool_name": response.tool_name,
                        "arguments": None,
                    },
                )
            ] + [
                StreamItem(
                    response_type=LLMResponseType.TOOL_CALL,
                    data={
                        "tool_call_id": None,
                        "tool_name": None,
                        "arguments": token,
                    },
                )
                for token in response.tool_call_argument_tokens
            ]
        case _:
            raise ValueError(f"Unknown response type: {response.type}")


def create_delta_from_stream_item(item: StreamItem) -> Delta:
    response_type = item.response_type
    data = item.data
    if response_type == LLMResponseType.REASONING:
        return Delta(reasoning_content=data)
    elif response_type == LLMResponseType.ANSWER:
        return Delta(content=data)
    elif response_type == LLMResponseType.TOOL_CALL:
        # Handle grouped tool calls (list) vs single tool call (dict)
        if isinstance(data, list):
            # Multiple tool calls emitted together in the same tick
            tool_calls = []
            for tc_data in data:
                if tc_data["tool_call_id"] is not None:
                    tool_calls.append(
                        ChatCompletionDeltaToolCall(
                            id=tc_data["tool_call_id"],
                            index=tc_data["index"],
                            function=FunctionCall(
                                arguments="",
                                name=tc_data["tool_name"],
                            ),
                        )
                    )
                else:
                    tool_calls.append(
                        ChatCompletionDeltaToolCall(
                            index=tc_data["index"],
                            id=None,
                            function=FunctionCall(
                                arguments=tc_data["arguments"],
                                name=None,
                            ),
                        )
                    )
            return Delta(tool_calls=tool_calls)
        else:
            # Single tool call (original behavior)
            # First tick has tool_call_id and tool_name, subsequent ticks have arguments
            if data["tool_call_id"] is not None:
                return Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            id=data["tool_call_id"],
                            function=FunctionCall(
                                name=data["tool_name"],
                                arguments="",
                            ),
                        )
                    ]
                )
            else:
                return Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            id=None,
                            function=FunctionCall(
                                name=None,
                                arguments=data["arguments"],
                            ),
                        )
                    ]
                )
    else:
        raise ValueError(f"Unknown response type: {response_type}")


class MockLLMController(abc.ABC):
    @abc.abstractmethod
    def add_response(self, response: LLMResponse) -> None:
        """Add a response to the current stream."""
        raise NotImplementedError

    @abc.abstractmethod
    def add_responses_together(self, *responses: LLMResponse) -> None:
        """Add multiple responses that should be emitted together in the same tick."""
        raise NotImplementedError

    @abc.abstractmethod
    def forward(self, n: int) -> None:
        """Forward the stream by n tokens."""
        raise NotImplementedError

    @abc.abstractmethod
    def forward_till_end(self) -> None:
        """Forward the stream until the end."""
        raise NotImplementedError

    @abc.abstractmethod
    def set_max_timeout(self, timeout: float = 5.0) -> None:
        raise NotImplementedError


class MockLLM(LLM, MockLLMController):
    def __init__(self) -> None:
        self.stream_controller = SyncStreamController[StreamItem]()

    def add_response(self, response: LLMResponse) -> None:
        items = _response_to_stream_items(response)
        self.stream_controller.queue_items(items)

    def add_responses_together(self, *responses: LLMResponse) -> None:
        """Add multiple responses that should be emitted together in the same tick.

        Currently only supports multiple tool call responses being grouped together.
        The initial tool call info (id, name) for all tool calls will be emitted
        in a single delta, followed by argument tokens for each tool call.
        """
        tool_calls = [r for r in responses if r.type == LLMResponseType.TOOL_CALL]

        if len(tool_calls) != len(responses):
            raise ValueError(
                "add_responses_together currently only supports "
                "multiple tool call responses"
            )

        # Create combined first item with all tool call initial info
        combined_data = [
            {
                "index": idx,
                "tool_call_id": cast(LLMToolCallResponse, tc).tool_call_id,
                "tool_name": cast(LLMToolCallResponse, tc).tool_name,
                "arguments": None,
            }
            for idx, tc in enumerate(tool_calls)
        ]
        combined_item = StreamItem(
            response_type=LLMResponseType.TOOL_CALL,
            data=combined_data,
        )
        self.stream_controller.queue_items([combined_item])

        # Add argument tokens for each tool call with their index
        for idx, tc in enumerate(tool_calls):
            tc = cast(LLMToolCallResponse, tc)
            for token in tc.tool_call_argument_tokens:
                item = StreamItem(
                    response_type=LLMResponseType.TOOL_CALL,
                    data=[
                        {
                            "index": idx,
                            "tool_call_id": None,
                            "tool_name": None,
                            "arguments": token,
                        }
                    ],
                )
                self.stream_controller.queue_items([item])

    def forward(self, n: int) -> None:
        if self.stream_controller:
            self.stream_controller.forward(n)
        else:
            raise ValueError("No response set")

    def forward_till_end(self) -> None:
        if self.stream_controller:
            self.stream_controller.forward_till_end()
        else:
            raise ValueError("No response set")

    def set_max_timeout(self, timeout: float = 5.0) -> None:
        self.stream_controller.timeout = timeout

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="mock",
            model_name="mock",
            temperature=1.0,
            max_input_tokens=1000000000,
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        raise NotImplementedError("We only care about streaming atm")

    def stream(
        self,
        prompt: LanguageModelInput,  # noqa: ARG002
        tools: list[dict] | None = None,  # noqa: ARG002
        tool_choice: ToolChoiceOptions | None = None,  # noqa: ARG002
        structured_response_format: dict | None = None,  # noqa: ARG002
        timeout_override: int | None = None,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,  # noqa: ARG002
        user_identity: LLMUserIdentity | None = None,  # noqa: ARG002
    ) -> Iterator[ModelResponseStream]:
        if not self.stream_controller:
            return

        for idx, item in enumerate(self.stream_controller):
            yield ModelResponseStream(
                id="chatcmp-123",
                created="1",
                choice=StreamingChoice(
                    finish_reason=None,
                    index=0,  # Choice index should stay at 0 for all items in the same stream
                    delta=create_delta_from_stream_item(item),
                ),
                usage=None,
            )


class StreamTimeoutError(Exception):
    """Raised when the stream controller times out waiting for tokens."""


class SyncStreamController(Generic[T]):
    def __init__(self, items: list[T] | None = None, timeout: float = 5.0) -> None:
        self.items = items if items is not None else []
        self.position = 0
        self.pending: list[int] = []  # The indices of the tokens that are pending
        self.timeout = timeout  # Maximum time to wait for tokens before failing

        self._has_pending = threading.Event()

    def queue_items(self, new_items: list[T]) -> None:
        """Queue additional tokens to the stream (for chaining responses like reasoning + tool calls)."""
        self.items.extend(new_items)

    def forward(self, n: int) -> None:
        """Queue the next n tokens to be yielded"""
        end = min(self.position + n, len(self.items))
        self.pending.extend(range(self.position, end))
        self.position = end

        if self.pending:
            self._has_pending.set()

    def forward_till_end(self) -> None:
        self.forward(len(self.items) - self.position)

    @property
    def is_done(self) -> bool:
        return self.position >= len(self.items) and not self.pending

    def __iter__(self) -> SyncStreamController[T]:
        return self

    def __next__(self) -> T:
        start_time = time.monotonic()
        while not self.is_done:
            if self.pending:
                item_idx = self.pending.pop(0)
                if not self.pending:
                    self._has_pending.clear()
                return self.items[item_idx]

            elapsed = time.monotonic() - start_time
            if elapsed >= self.timeout:
                raise StreamTimeoutError(
                    f"Stream controller timed out after {self.timeout}s waiting for tokens. "
                    f"Position: {self.position}/{len(self.items)}, Pending: {len(self.pending)}"
                )

            self._has_pending.wait(timeout=0.1)

        raise StopIteration


@contextmanager
def use_mock_llm() -> Generator[MockLLMController, None, None]:
    mock_llm = MockLLM()

    with patch("onyx.chat.process_message.get_llm_for_persona", return_value=mock_llm):
        yield mock_llm
