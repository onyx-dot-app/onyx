from __future__ import annotations

import abc
import threading
import time
from collections.abc import Generator
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

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


class MockLLMController(abc.ABC):
    @abc.abstractmethod
    def set_response(self, response_tokens: list[str]) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def forward(self, n: int) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def forward_till_end(self) -> None:
        raise NotImplementedError


class MockLLM(LLM, MockLLMController):
    def __init__(self) -> None:
        self.stream_controller: SyncStreamController | None = None

    def set_response(self, response_tokens: list[str]) -> None:
        self.stream_controller = SyncStreamController(response_tokens)

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
        if not self.stream_controller:
            return

        for idx, token in enumerate(self.stream_controller):
            yield ModelResponseStream(
                id="chatcmp-123",
                created="1",
                choice=StreamingChoice(
                    finish_reason=None,
                    index=idx,
                    delta=Delta(
                        content=token,
                    ),
                ),
                usage=None,
            )


class StreamTimeoutError(Exception):
    """Raised when the stream controller times out waiting for tokens."""


class SyncStreamController:
    def __init__(self, tokens: list[str], timeout: float = 5.0) -> None:
        self.tokens = tokens
        self.position = 0
        self.pending: list[int] = []  # The indices of the tokens that are pending
        self.timeout = timeout  # Maximum time to wait for tokens before failing

        self._has_pending = threading.Event()

    def forward(self, n: int) -> None:
        """Queue the next n tokens to be yielded"""
        end = min(self.position + n, len(self.tokens))
        self.pending.extend(range(self.position, end))
        self.position = end

        if self.pending:
            self._has_pending.set()

    def forward_till_end(self) -> None:
        self.forward(len(self.tokens) - self.position)

    @property
    def is_done(self) -> bool:
        return self.position >= len(self.tokens) and not self.pending

    def __iter__(self) -> SyncStreamController:
        return self

    def __next__(self) -> str:
        start_time = time.monotonic()
        while not self.is_done:
            if self.pending:
                token_idx = self.pending.pop(0)
                if not self.pending:
                    self._has_pending.clear()
                return self.tokens[token_idx]

            elapsed = time.monotonic() - start_time
            if elapsed >= self.timeout:
                raise StreamTimeoutError(
                    f"Stream controller timed out after {self.timeout}s waiting for tokens. "
                    f"Position: {self.position}/{len(self.tokens)}, Pending: {len(self.pending)}"
                )

            self._has_pending.wait(timeout=0.1)

        raise StopIteration


@contextmanager
def use_mock_llm() -> Generator[MockLLMController, None, None]:
    mock_llm = MockLLM()

    with patch("onyx.chat.process_message.get_llm_for_persona", return_value=mock_llm):
        yield mock_llm
