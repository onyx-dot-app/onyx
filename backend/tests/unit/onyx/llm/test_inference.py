import asyncio
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from pydantic_ai import messages as pm
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from onyx.llm.inference import run_inference
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode
from onyx.tracing.llm_utils import record_native_llm_response


class CountResult(BaseModel):
    count: int


def test_total_timeout_cancels_native_request() -> None:
    cancelled = False

    async def respond(
        _messages: list[pm.ModelMessage], _info: AgentInfo
    ) -> pm.ModelResponse:
        nonlocal cancelled
        try:
            await asyncio.sleep(60)
            return pm.ModelResponse(parts=[pm.TextPart("late response")])
        finally:
            cancelled = True

    llm = MagicMock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="test", model_name="test", max_input_tokens=8000, temperature=0
    )
    llm.model = FunctionModel(respond)
    llm.model_settings.return_value = {}
    with pytest.raises(TimeoutError):
        run_inference(
            llm=llm,
            messages=[pm.ModelRequest(parts=[pm.UserPromptPart("Count items")])],
            output_type=str,
            flow=LLMFlow.SEMANTIC_QUERY_REPHRASE,
            content_mode=TraceContentMode.METADATA_ONLY,
            total_timeout_override=0.05,
        )
    assert cancelled
    llm.record_usage.assert_not_called()


def test_structured_retry_records_each_native_request() -> None:
    requests: list[list[pm.ModelMessage]] = []
    spans: list[MagicMock] = []

    def respond(messages: list[pm.ModelMessage], info: AgentInfo) -> pm.ModelResponse:
        requests.append(list(messages))
        return pm.ModelResponse(
            parts=[
                pm.ToolCallPart(
                    info.output_tools[0].name,
                    {"count": "invalid" if len(requests) == 1 else 3},
                )
            ],
            usage=RequestUsage(input_tokens=20, output_tokens=5),
        )

    @contextmanager
    def capture_span(**_kwargs: object) -> Iterator[MagicMock]:
        span = MagicMock()
        span.content_mode = TraceContentMode.METADATA_ONLY
        spans.append(span)
        yield span

    llm = MagicMock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="test", model_name="test", max_input_tokens=8000, temperature=0
    )
    llm.model = FunctionModel(respond)
    llm.model_settings.return_value = {}
    with patch("onyx.llm.inference.llm_generation_span", capture_span):
        result = run_inference(
            llm=llm,
            messages=[pm.ModelRequest(parts=[pm.UserPromptPart("Count items")])],
            output_type=CountResult,
            flow=LLMFlow.SEMANTIC_QUERY_REPHRASE,
        )

    assert result == CountResult(count=3)
    assert llm.record_usage.call_count == 2
    assert len(spans) == 2
    assert all(span.span_data.usage["input_tokens"] == 20 for span in spans)
    assert any(
        isinstance(part, pm.RetryPromptPart)
        for message in requests[1]
        if isinstance(message, pm.ModelRequest)
        for part in message.parts
    )


@pytest.mark.parametrize(
    "mode", [TraceContentMode.FULL, TraceContentMode.METADATA_ONLY]
)
def test_native_trace_preserves_usage_and_content_policy(
    mode: TraceContentMode,
) -> None:
    span = MagicMock()
    span.content_mode = mode
    span.configure_mock(**{"span_data.output": None, "span_data.reasoning": None})
    response = pm.ModelResponse(
        parts=[
            pm.ThinkingPart("private thinking", signature="private signature"),
            pm.TextPart("private answer"),
            pm.ToolCallPart("lookup", {"query": "private query"}, "call-1"),
        ],
        usage=RequestUsage(
            input_tokens=20, output_tokens=5, cache_read_tokens=8, cache_write_tokens=4
        ),
    )
    record_native_llm_response(span, response)
    assert span.span_data.usage == {
        "input_tokens": 20,
        "output_tokens": 5,
        "total_tokens": 25,
        "cache_read_input_tokens": 8,
        "cache_creation_input_tokens": 4,
    }
    if mode == TraceContentMode.METADATA_ONLY:
        assert span.span_data.output is None
        assert span.span_data.reasoning is None
    else:
        assert span.span_data.output[0]["content"] == "private answer"
        assert span.span_data.output[0]["tool_calls"][0]["id"] == "call-1"
        assert span.span_data.reasoning == "private thinking"
        assert "private signature" not in str(span.span_data.output)
