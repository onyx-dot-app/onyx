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
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from onyx.db.models import User
from onyx.llm.models import ToolResult
from onyx.server.features.build import request_context
from onyx.server.features.build.configs import CRAFT_SESSION_HEADER
from onyx.server.features.search import api as search_api
from onyx.server.features.search.api import search
from onyx.server.features.search.models import SearchRequest
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tracing.framework import set_trace_processors
from onyx.tracing.framework.create import generation_span
from onyx.tracing.framework.span_data import FunctionSpanData, GenerationSpanData
from tests.unit.onyx.tracing.capture import CaptureProcessor

_API = "onyx.server.features.search.api"
_QUERY = "what is the refund policy"
_LLM_FACING = json.dumps({"results": []})


@pytest.fixture
def processor() -> Generator[CaptureProcessor, None, None]:
    capture = CaptureProcessor()
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
    """Stub out everything the endpoint needs to reach ``SearchTool.search``."""
    tool = MagicMock()
    tool.id = 7
    tool.in_code_tool_id = SEARCH_TOOL_ID

    search_tool_cls = MagicMock()
    search_tool_cls.NAME = SearchTool.NAME

    with (
        patch(f"{_API}.get_default_llm"),
        patch(f"{_API}.check_llm_cost_limit_for_provider"),
        patch(f"{_API}.check_model_spend_limits"),
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
        trace_metadata={},
    )


def test_search_records_pipeline_spans_under_one_trace(
    processor: CaptureProcessor,
    user: MagicMock,
    search_dependencies: MagicMock,
) -> None:
    def run(*_args: Any, **_kwargs: Any) -> ToolResult:
        # Stands in for the query expansion / rerank / selection calls the real
        # pipeline makes; each opens a generation span.
        with generation_span(model="some-model"):
            pass
        return ToolResult(content=_LLM_FACING)

    search_dependencies.search.side_effect = run

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
    processor: CaptureProcessor,
    user: MagicMock,
    search_dependencies: MagicMock,
) -> None:
    search_dependencies.search.return_value = ToolResult(content=_LLM_FACING)

    with patch(f"{_API}.get_persona_by_id"), patch(f"{_API}.get_llm_for_persona"):
        _run_search(user, persona_id=42)

    metadata = (processor.started_traces[0].export() or {})["metadata"]
    assert metadata["persona_id"] == 42


def test_search_failure_is_recorded_on_the_tool_span(
    processor: CaptureProcessor,
    user: MagicMock,
    search_dependencies: MagicMock,
) -> None:
    search_dependencies.search.side_effect = RuntimeError("index unreachable")

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


@pytest.mark.parametrize("path", ["/search", "/search/raw"])
@pytest.mark.parametrize("owned", [True, False])
def test_search_api_joins_only_an_owned_craft_turn(
    path: str,
    owned: bool,
    request: pytest.FixtureRequest,
    processor: CaptureProcessor,
    user: MagicMock,
    search_dependencies: MagicMock,
) -> None:
    session_id = uuid4()
    turn_id = uuid4().hex
    search_dependencies.search.return_value = ToolResult(content=_LLM_FACING)
    app = FastAPI()
    app.include_router(search_api.router)
    app.dependency_overrides[search_api._search_user] = lambda: user
    engine = create_engine(
        "sqlite://",
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.01,
        connect_args={"check_same_thread": False},
    )

    request.addfinalizer(engine.dispose)

    def search_session() -> Generator[Session, None, None]:
        # Match schema-translated sessions: the outer context owns the connection.
        with engine.connect() as connection, Session(bind=connection) as session:
            yield session

    app.dependency_overrides[search_api.get_session] = search_session

    def read_turn(_session_id: object) -> str:
        # A single-connection pool cannot service this while search setup holds it.
        with engine.connect():
            return turn_id

    for dependency in (
        search_api.require_vector_db,
        search_api.check_token_rate_limits,
    ):
        app.dependency_overrides[dependency] = lambda: None
    with (
        patch("onyx.server.api_key_usage.is_usage_limits_enabled", return_value=False),
        patch.object(request_context, "get_session_with_current_tenant"),
        patch.object(
            request_context, "get_build_session", return_value=user if owned else None
        ),
        patch.object(
            request_context, "get_craft_turn_trace_id", side_effect=read_turn
        ) as lookup,
        TestClient(app) as client,
    ):
        for _ in range(2):
            response = client.post(
                path,
                json={"query": _QUERY},
                headers={CRAFT_SESSION_HEADER: str(session_id)},
            )
            assert response.status_code == 200, response.text
        for active in processor.started_traces:
            metadata = (active.export() or {})["metadata"]
            assert metadata["user_id"] == str(user.id)
            if owned:
                assert metadata["craft_session_id"] == str(session_id)
                assert metadata["distributed_trace_id"] == turn_id
                assert metadata["distributed_parent_span_id"] == turn_id[:16]
            else:
                assert "craft_session_id" not in metadata
                assert "distributed_trace_id" not in metadata
        assert len({active.trace_id for active in processor.started_traces}) == 2
        assert lookup.call_count == (2 if owned else 0)
        # The next ordinary API call must not inherit the prior request's context.
        processor.started_traces.clear()
        assert client.post(path, json={"query": _QUERY}).status_code == 200
        assert (
            "craft_session_id"
            not in (processor.started_traces[0].export() or {})["metadata"]
        )


@pytest.mark.parametrize("path", ["/search", "/search/raw"])
def test_disabled_search_stops_before_session_attribution(path: str) -> None:
    app = FastAPI()
    app.include_router(search_api.router)
    user_calls: list[bool] = []

    def authenticate() -> MagicMock:
        user_calls.append(True)
        return MagicMock()

    app.dependency_overrides[search_api._search_user] = authenticate
    with (
        patch("onyx.server.utils_vector_db.DISABLE_VECTOR_DB", True),
        TestClient(app) as client,
        pytest.raises(search_api.OnyxError) as error,
    ):
        client.post(path, json={"query": _QUERY})
    assert error.value.error_code == search_api.OnyxErrorCode.NOT_IMPLEMENTED
    assert not user_calls
