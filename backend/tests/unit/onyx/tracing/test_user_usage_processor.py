"""Per-user usage recorder: capture, pricing args, drain, shutdown.

`record_user_usage` is Postgres-only; these tests mock it and assert call args
rather than executing the upsert against SQLite."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.tracing.framework.span_data import FunctionSpanData
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.span_data import SpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.processors import user_usage_processor as proc_mod
from onyx.tracing.processors.user_usage_processor import UserUsageTracingProcessor
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR


class _FakeSpan:
    """Minimal stand-in exposing the only attribute the processor reads."""

    def __init__(self, span_data: SpanData) -> None:
        self.span_data = span_data


def _fake_span(span_data: SpanData) -> Span[Any]:
    return cast(Span[Any], _FakeSpan(span_data))


def _generation_span(
    model: str = "gpt-4o",
    provider: str = "openai",
    flow: str = "chat_response",
    usage: dict[str, Any] | None = None,
) -> Span[Any]:
    return _fake_span(
        GenerationSpanData(
            model=model,
            model_config={"model_provider": provider, "flow": flow},
            usage=usage
            if usage is not None
            else {"input_tokens": 0, "output_tokens": 0},
        )
    )


@pytest.fixture
def recorded_calls() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def processor(
    monkeypatch: pytest.MonkeyPatch, recorded_calls: list[dict[str, Any]]
) -> Generator[UserUsageTracingProcessor, None, None]:
    """Processor with mocked session + record_user_usage; cost pinned."""

    @contextmanager
    def _fake_session(*, tenant_id: str) -> Generator[Any, None, None]:  # noqa: ARG001
        yield MagicMock()

    def _capture_record(db_session: Any, **kwargs: Any) -> None:  # noqa: ARG001
        recorded_calls.append(kwargs)

    monkeypatch.setattr(proc_mod, "get_session_with_tenant", _fake_session)
    monkeypatch.setattr(proc_mod, "compute_cost_cents", lambda *_a, **_k: (1.0, 2.0))
    monkeypatch.setattr(proc_mod, "record_user_usage", _capture_record)

    p = UserUsageTracingProcessor(flush_interval_seconds=0.05)
    try:
        yield p
    finally:
        p.shutdown()


def test_records_usage_when_user_id_set(
    processor: UserUsageTracingProcessor, recorded_calls: list[dict[str, Any]]
) -> None:
    user_id = str(uuid4())
    token = CURRENT_USER_ID_CONTEXTVAR.set(user_id)
    try:
        processor.on_span_end(
            _generation_span(
                usage={
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 20,
                }
            )
        )
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)

    processor.force_flush()

    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    assert call["user_id"] == user_id
    assert call["input_tokens"] == 100
    assert call["output_tokens"] == 50
    assert call["cache_read_tokens"] == 20
    assert call["model"] == "gpt-4o"
    assert call["provider"] == "openai"
    assert call["flow"] == "chat_response"
    assert call["cost_cents"] == pytest.approx(3.0)  # 1.0 input + 2.0 output


def test_normalizes_prompt_completion_token_aliases(
    processor: UserUsageTracingProcessor, recorded_calls: list[dict[str, Any]]
) -> None:
    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        processor.on_span_end(
            _generation_span(
                usage={"prompt_tokens": 7, "completion_tokens": 3},
            )
        )
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)

    processor.force_flush()

    assert len(recorded_calls) == 1
    assert recorded_calls[0]["input_tokens"] == 7
    assert recorded_calls[0]["output_tokens"] == 3


def test_no_record_when_user_id_unset(
    processor: UserUsageTracingProcessor, recorded_calls: list[dict[str, Any]]
) -> None:
    processor.on_span_end(_generation_span(usage={"input_tokens": 5}))
    processor.force_flush()
    assert recorded_calls == []


def test_ignores_non_generation_spans(
    processor: UserUsageTracingProcessor, recorded_calls: list[dict[str, Any]]
) -> None:
    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        processor.on_span_end(
            _fake_span(FunctionSpanData(name="tool", input="x", output="y"))
        )
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)
    processor.force_flush()
    assert recorded_calls == []


def test_ignores_generation_span_without_usage(
    processor: UserUsageTracingProcessor, recorded_calls: list[dict[str, Any]]
) -> None:
    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        processor.on_span_end(
            _fake_span(GenerationSpanData(model="gpt-4o", usage=None))
        )
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)
    processor.force_flush()
    assert recorded_calls == []


def test_on_span_end_never_raises_on_internal_error(
    processor: UserUsageTracingProcessor,
    recorded_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(proc_mod, "get_current_user_id", _boom)

    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        processor.on_span_end(_generation_span(usage={"input_tokens": 1}))
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)

    processor.force_flush()
    assert recorded_calls == []


def test_excludes_cache_reads_from_priced_input(
    monkeypatch: pytest.MonkeyPatch, recorded_calls: list[dict[str, Any]]
) -> None:
    @contextmanager
    def _fake_session(*, tenant_id: str) -> Generator[Any, None, None]:  # noqa: ARG001
        yield MagicMock()

    monkeypatch.setattr(proc_mod, "get_session_with_tenant", _fake_session)

    priced: list[tuple[int, int, int]] = []

    def _capture_cost(
        _model: str,
        _provider: Any,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        **_kw: Any,
    ) -> tuple[float, float]:
        priced.append((input_tokens, output_tokens, cache_read_tokens))
        return (0.0, 0.0)

    def _capture_record(db_session: Any, **kwargs: Any) -> None:  # noqa: ARG001
        recorded_calls.append(kwargs)

    monkeypatch.setattr(proc_mod, "compute_cost_cents", _capture_cost)
    monkeypatch.setattr(proc_mod, "record_user_usage", _capture_record)

    p = UserUsageTracingProcessor(flush_interval_seconds=0.05)
    try:
        token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
        try:
            p.on_span_end(
                _generation_span(
                    usage={
                        # input_tokens is the cache-inclusive prompt total.
                        "input_tokens": 3000,
                        "output_tokens": 500,
                        "cache_read_input_tokens": 2000,
                    }
                )
            )
        finally:
            CURRENT_USER_ID_CONTEXTVAR.reset(token)
        p.force_flush()
    finally:
        p.shutdown()

    assert priced == [(1000, 500, 2000)]
    assert len(recorded_calls) == 1
    assert recorded_calls[0]["input_tokens"] == 3000
    assert recorded_calls[0]["cache_read_tokens"] == 2000


def test_flush_swallows_record_errors(
    processor: UserUsageTracingProcessor,
    recorded_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(proc_mod, "record_user_usage", _boom)

    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        processor.on_span_end(_generation_span(usage={"input_tokens": 1}))
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)

    processor.force_flush()
    assert recorded_calls == []
