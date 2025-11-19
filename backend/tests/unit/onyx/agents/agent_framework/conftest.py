from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from typing import Any

import pytest
from langchain.schema.language_model import (
    LanguageModelInput as LangChainLanguageModelInput,
)
from langchain_core.messages import BaseMessage

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import Delta
from onyx.llm.model_response import FunctionCall
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice
from onyx.tools.models import ToolResponse
from onyx.tools.tool import RunContextWrapper
from onyx.tools.tool import Tool


class _FakeLLM(LLM):
    def __init__(self, responses: list[ModelResponseStream]) -> None:
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
        prompt: LanguageModelInput,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict[str, Any] | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        raise AssertionError("FakeLLM.invoke() should not be called in this test")

    def _stream_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict[str, Any] | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[ModelResponseStream]:
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
        prompt: LangChainLanguageModelInput,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict[str, Any] | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> BaseMessage:
        raise NotImplementedError

    def _stream_implementation_langchain(
        self,
        prompt: LangChainLanguageModelInput,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict[str, Any] | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[BaseMessage]:
        raise NotImplementedError


@pytest.fixture
def fake_llm() -> Callable[[list[ModelResponseStream]], _FakeLLM]:
    def factory(responses: list[ModelResponseStream]) -> _FakeLLM:
        return _FakeLLM(responses)

    return factory


# Helper functions for creating ModelResponseStream objects concisely
def stream_chunk(
    id: str = "test-id",
    created: str = "1234567890",
    content: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[ChatCompletionDeltaToolCall] | None = None,
    finish_reason: str | None = None,
) -> ModelResponseStream:
    """Helper to create a ModelResponseStream chunk concisely."""
    return ModelResponseStream(
        id=id,
        created=created,
        choice=StreamingChoice(
            finish_reason=finish_reason,
            delta=Delta(
                content=content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls or [],
            ),
        ),
    )


def tool_call_chunk(
    id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
    index: int = 0,
) -> ChatCompletionDeltaToolCall:
    """Helper to create a ChatCompletionDeltaToolCall concisely."""
    return ChatCompletionDeltaToolCall(
        id=id,
        function=FunctionCall(arguments=arguments, name=name),
        type="function",
        index=index,
    )


# Fake tools for testing
class FakeTool(Tool):
    """Base fake tool for testing."""

    def __init__(self, tool_name: str, tool_id: int = 1):
        self._tool_name = tool_name
        self._tool_id = tool_id
        self.calls: list[dict[str, Any]] = []

    @property
    def id(self) -> int:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        return f"{self._tool_name} tool"

    @property
    def display_name(self) -> str:
        return self._tool_name.replace("_", " ").title()

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self._tool_name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["queries"],
                },
            },
        }

    def run_v2(
        self,
        run_context: RunContextWrapper[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        queries = kwargs.get("queries", [])
        self.calls.append({"queries": queries})
        context = run_context.context
        flag_name = f"{self._tool_name}_called"
        context[flag_name] = True
        return f"{self.display_name} results for: {', '.join(queries)}"

    def build_tool_message_content(self, *args: Any) -> str:
        return ""

    def get_args_for_non_tool_calling_llm(
        self, query: Any, history: Any, llm: Any, force_run: bool = False
    ) -> None:
        return None

    def run(
        self, override_kwargs: Any = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        raise NotImplementedError
        yield  # Make this a generator

    def final_result(self, *args: Any) -> dict[str, Any]:
        return {}

    def build_next_prompt(
        self,
        prompt_builder: Any,
        tool_call_summary: Any,
        tool_responses: Any,
        using_tool_calling_llm: Any,
    ) -> Any:
        return prompt_builder


@pytest.fixture
def fake_internal_search_tool() -> FakeTool:
    """Fixture providing a fake internal search tool."""
    return FakeTool("internal_search", tool_id=1)


@pytest.fixture
def fake_web_search_tool() -> FakeTool:
    """Fixture providing a fake web search tool."""
    return FakeTool("web_search", tool_id=2)
