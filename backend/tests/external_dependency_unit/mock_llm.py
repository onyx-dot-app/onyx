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
from unittest.mock import patch

from pydantic import BaseModel

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ReasoningEffort
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import Delta
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice


class LLMResponseType(str, Enum):
    REASONING = "reasoning"
    ANSWER = "answer"
    TOOL_CALL = "tool_call"


class LLMResponse(BaseModel):
    type: LLMResponseType = ""


class LLMReasoningResponse(LLMResponse):
    type: LLMResponseType = LLMResponseType.REASONING
    reasoning_tokens: list[str]


class LLMAnswerResponse(LLMResponse):
    type: LLMResponseType = LLMResponseType.ANSWER
    answer_tokens: list[str]


class LLMToolCallResponse(LLMResponse):
    type: LLMResponseType = LLMResponseType.TOOL_CALL
    tool_name: str
    tool_call_id: str
    tool_call_argument_tokens: list[str]


class StreamItem(BaseModel):
    """Represents a single item in the mock LLM stream with its type."""

    response_type: LLMResponseType
    data: Any


def _response_to_stream_items(response: LLMResponse) -> list[StreamItem]:
    match response.type:
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
        # First tick has tool_call_id and tool_name, subsequent ticks have arguments
        if data["tool_call_id"] is not None:
            return Delta(
                tool_calls=[
                    {
                        "id": data["tool_call_id"],
                        "function": {"name": data["tool_name"], "arguments": ""},
                    }
                ]
            )
        else:
            return Delta(
                tool_calls=[{"id": None, "function": {"arguments": data["arguments"]}}]
            )
    else:
        raise ValueError(f"Unknown response type: {response_type}")


class MockLLMController(abc.ABC):
    @abc.abstractmethod
    def add_response(self, response: LLMResponse) -> None:
        """Add a response to the current stream."""
        raise NotImplementedError

    @abc.abstractmethod
    def forward(self, n: int) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def forward_till_end(self) -> None:
        raise NotImplementedError


class MockLLM(LLM, MockLLMController):
    def __init__(self):
        self.stream_controller = SyncStreamController()

    def add_response(self, response: LLMResponse) -> None:
        items = _response_to_stream_items(response)
        self.stream_controller.queue_items(items)

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
        reasoning_effort: ReasoningEffort | None = None,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        raise NotImplementedError("We only care about streaming atm")

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
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


class SyncStreamController:
    def __init__(self, items: list[Any] | None = None, timeout: float = 5.0):
        self.items = items if items is not None else []
        self.position = 0
        self.pending: list[int] = []  # The indices of the tokens that are pending
        self.timeout = timeout  # Maximum time to wait for tokens before failing

        self._has_pending = threading.Event()

    def queue_items(self, new_items: list[Any]) -> None:
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

    def __iter__(self) -> SyncStreamController:
        return self

    def __next__(self) -> str:
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
