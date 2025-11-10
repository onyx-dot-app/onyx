from collections.abc import Callable
from collections.abc import Iterator
from typing import Any

import pytest

from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import ToolChoiceOptions


class _FakeLLM(LLM):
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.stream_calls: list[dict[str, Any]] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="fake-provider",
            model_name="fake-model",
            temperature=0.0,
            max_input_tokens=1024,
        )

    def log_model_configs(self) -> None:
        return None

    def _invoke_implementation(
        self,
        prompt,
        tools=None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format=None,
        timeout_override=None,
        max_tokens=None,
    ):
        raise AssertionError("FakeLLM.invoke() should not be called in this test")

    def _stream_implementation(
        self,
        prompt,
        tools=None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format=None,
        timeout_override=None,
        max_tokens=None,
    ) -> Iterator[str]:
        self.stream_calls.append(
            {
                "prompt": prompt,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        for chunk in self._responses:
            yield chunk

    def _invoke_implementation_langchain(
        self,
        prompt,
        tools=None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format=None,
        timeout_override=None,
        max_tokens=None,
    ):
        raise NotImplementedError

    def _stream_implementation_langchain(
        self,
        prompt,
        tools=None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format=None,
        timeout_override=None,
        max_tokens=None,
    ):
        raise NotImplementedError


@pytest.fixture
def fake_llm() -> Callable[[list[str]], _FakeLLM]:
    def factory(responses: list[str]) -> _FakeLLM:
        return _FakeLLM(responses)

    return factory
