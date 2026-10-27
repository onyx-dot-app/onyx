"""POST /api/search opens its own trace.

The endpoint reaches ``SearchTool`` directly instead of going through the chat
LLM loop and the tool runner, so without a trace of its own every generation
span raised by the search pipeline becomes a ``NoOpSpan`` and nothing reaches
Braintrust or Langfuse.
"""

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.db.models import User
from onyx.server.features.search.api import search
from onyx.server.features.search.models import SearchRequest
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tracing.framework import set_trace_processors
from onyx.tracing.framework.create import generation_span
from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.span_data import FunctionSpanData, GenerationSpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace

_API = "onyx.server.features.search.api"
_QUERY = "what is the refund policy"
_LLM_FACING = json.dumps({"results": []})


class _CaptureProcessor(TracingProcessor):
    def __init__(self) -> None:
        self.started_traces: list[Trace] = []
        self.ended_spans: list[Span[Any]] = []

    def on_trace_start(self, trace: Trace) -> None:
        self.started_traces.append(trace)

    def on_trace_end(self, trace: Trace) -> None:
        pass

    def on_span_start(self, span: Span[Any]) -> None:
        pass

    def on_span_end(self, span: Span[Any]) -> None:
        self.ended_spans.append(span)

    def shutdown(self) -> None:
        pass

    def force_flush(self) -> None:
        pass


@pytest.fixture
def processor() -> Generator[_CaptureProcessor, None, None]:
    capture = _CaptureProcessor()
    set_trace_processors([capture])
    try:
        yield capture
    finally:
        set_trace_processors([])


@pytest.fixture
def user() -> MagicMock:
    fake_user = MagicMock(spec=User)
    fake_user.id = uuid4()
    return fake_user


@pytest.fixture
def search_dependencies() -> Generator[MagicMock, None, None]:
    """Stub out everything the endpoint needs to reach ``SearchTool.run``."""
    tool = MagicMock()
    tool.id = 7
    tool.in_code_tool_id = SEARCH_TOOL_ID

    search_tool_cls = MagicMock()
    search_tool_cls.NAME = SearchTool.NAME

    with (
        patch(f"{_API}.get_default_llm"),
        patch(f"{_API}.check_llm_cost_limit_for_provider"),
        patch(f"{_API}.get_current_search_settings"),
        patch(f"{_API}.get_default_document_index"),
        patch(f"{_API}.load_settings"),
        patch(f"{_API}.get_tools", return_value=[tool]),
        patch(f"{_API}.SearchTool", search_tool_cls),
    ):
        yield search_tool_cls.return_value


def _run_search(user: MagicMock, persona_id: int | None = None) -> Any:
    return search(
        request=SearchRequest(query=_QUERY, persona_id=persona_id),
        user=user,
        db_session=MagicMock(),
    )


def test_search_records_pipeline_spans_under_one_trace(
    processor: _CaptureProcessor,
    user: MagicMock,
    search_dependencies: MagicMock,
) -> None:
    def run(**_kwargs: Any) -> ToolResponse:
        # Stands in for the query expansion / rerank / selection calls the real
        # pipeline makes; each opens a generation span.
        with generation_span(model="some-model"):
            pass
        return ToolResponse(rich_response=None, llm_facing_response=_LLM_FACING)

    search_dependencies.run.side_effect = run

    _run_search(user)

    assert len(processor.started_traces) == 1
    trace = processor.started_traces[0]
    assert trace.name == "search_api"
    assert trace.export() is not None
    metadata = (trace.export() or {})["metadata"]
    assert metadata["user_id"] == str(user.id)
    assert metadata["persona_id"] is None
    assert metadata["tenant_id"]

    generation, tool_span = processor.ended_spans
    assert isinstance(generation.span_data, GenerationSpanData)
    assert isinstance(tool_span.span_data, FunctionSpanData)

    # The generation span nests under the tool span, which nests under the trace.
    assert generation.trace_id == trace.trace_id
    assert generation.parent_id == tool_span.span_id
    assert tool_span.trace_id == trace.trace_id
    assert tool_span.parent_id is None

    assert tool_span.span_data.name == SearchTool.NAME
    assert tool_span.span_data.input == _QUERY
    assert tool_span.span_data.output == _LLM_FACING


def test_search_records_persona_id_on_the_trace(
    processor: _CaptureProcessor,
    user: MagicMock,
    search_dependencies: MagicMock,
) -> None:
    search_dependencies.run.return_value = ToolResponse(
        rich_response=None, llm_facing_response=_LLM_FACING
    )

    with patch(f"{_API}.get_persona_by_id"), patch(f"{_API}.get_llm_for_persona"):
        _run_search(user, persona_id=42)

    metadata = (processor.started_traces[0].export() or {})["metadata"]
    assert metadata["persona_id"] == 42


def test_search_failure_is_recorded_on_the_tool_span(
    processor: _CaptureProcessor,
    user: MagicMock,
    search_dependencies: MagicMock,
) -> None:
    search_dependencies.run.side_effect = RuntimeError("index unreachable")

    with pytest.raises(RuntimeError):
        _run_search(user)

    (tool_span,) = processor.ended_spans
    error = tool_span.error
    assert error is not None
    assert error["message"] == "RuntimeError: search failed"
    # The exception text is deliberately left out: nothing redacts credentials
    # out of a provider error on this path.
    assert "index unreachable" not in error["message"]
    assert error["data"] is None
