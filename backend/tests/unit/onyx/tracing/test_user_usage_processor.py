"""Unit tests for the per-user usage recording processor (in-memory SQLite)."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from onyx.db.models import UserUsage
from onyx.tracing.framework.span_data import FunctionSpanData
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.span_data import SpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.processors import user_usage_processor as proc_mod
from onyx.tracing.processors.user_usage_processor import UserUsageTracingProcessor
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR


# Map the postgres-only column types onto SQLite equivalents so the real
# UserUsage table from models.py can be created against an in-memory DB.
@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


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
def sqlite_engine() -> Engine:
    # StaticPool + single connection so the table is visible across the drain
    # thread's separately-opened sessions (a plain sqlite:// gives each
    # connection its own empty in-memory DB).
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    user_usage_table = cast(Table, UserUsage.__table__)
    user_usage_table.create(bind=engine)
    return engine


@pytest.fixture
def processor(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine: Engine
) -> Generator[UserUsageTracingProcessor, None, None]:
    """A processor whose flush thread writes to the in-memory SQLite engine.

    `get_session_with_tenant` is monkeypatched to bind sessions to the test
    engine; compute_cost_cents is pinned to a known value so the recorded cost
    is deterministic without touching litellm.
    """
    SessionLocal = sessionmaker(bind=sqlite_engine)

    from contextlib import contextmanager

    @contextmanager
    def _fake_session(*, tenant_id: str) -> Generator[Any, None, None]:  # noqa: ARG001
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(proc_mod, "get_session_with_tenant", _fake_session)
    monkeypatch.setattr(proc_mod, "compute_cost_cents", lambda *_a, **_k: (1.0, 2.0))

    p = UserUsageTracingProcessor(flush_interval_seconds=0.05)
    try:
        yield p
    finally:
        p.shutdown()


def _read_rows(engine: Engine) -> list[UserUsage]:
    with sessionmaker(bind=engine)() as s:
        return list(s.execute(select(UserUsage)).scalars().all())


def test_records_usage_when_user_id_set(
    processor: UserUsageTracingProcessor, sqlite_engine: Engine
) -> None:
    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
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

    rows = _read_rows(sqlite_engine)
    assert len(rows) == 1
    row = rows[0]
    assert row.input_tokens == 100
    assert row.output_tokens == 50
    assert row.cache_read_tokens == 20
    assert row.model == "gpt-4o"
    assert row.provider == "openai"
    assert row.flow == "chat_response"
    assert row.cost_cents == pytest.approx(3.0)  # 1.0 input + 2.0 output


def test_normalizes_prompt_completion_token_aliases(
    processor: UserUsageTracingProcessor, sqlite_engine: Engine
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

    rows = _read_rows(sqlite_engine)
    assert len(rows) == 1
    assert rows[0].input_tokens == 7
    assert rows[0].output_tokens == 3


def test_no_record_when_user_id_unset(
    processor: UserUsageTracingProcessor, sqlite_engine: Engine
) -> None:
    # No CURRENT_USER_ID_CONTEXTVAR set -> background-worker-like context.
    processor.on_span_end(_generation_span(usage={"input_tokens": 5}))
    processor.force_flush()
    assert _read_rows(sqlite_engine) == []


def test_ignores_non_generation_spans(
    processor: UserUsageTracingProcessor, sqlite_engine: Engine
) -> None:
    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        processor.on_span_end(
            _fake_span(FunctionSpanData(name="tool", input="x", output="y"))
        )
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)
    processor.force_flush()
    assert _read_rows(sqlite_engine) == []


def test_ignores_generation_span_without_usage(
    processor: UserUsageTracingProcessor, sqlite_engine: Engine
) -> None:
    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        processor.on_span_end(
            _fake_span(GenerationSpanData(model="gpt-4o", usage=None))
        )
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)
    processor.force_flush()
    assert _read_rows(sqlite_engine) == []


def test_on_span_end_never_raises_on_internal_error(
    processor: UserUsageTracingProcessor,
    sqlite_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An exception anywhere in capture must be swallowed (LLM hot path).
    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(proc_mod, "get_current_user_id", _boom)

    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        # Must not raise.
        processor.on_span_end(_generation_span(usage={"input_tokens": 1}))
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)

    processor.force_flush()
    assert _read_rows(sqlite_engine) == []


def test_real_pricing_excludes_cache_reads_from_input(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine: Engine
) -> None:
    # Real compute_cost_cents (NOT stubbed): the span carries the litellm prompt
    # total (input_tokens already includes cache reads). The processor must
    # price the non-cached remainder as input and the cache reads at the cache
    # rate — mirrors test_cost.py::test_cache_read_tokens_priced_as_input.
    # gpt-4o: 1000 non-cached @ $2.50/Mtok + 2000 cache-read @ $1.25/Mtok =
    # 0.25c + 0.25c = 0.5c input; 500 output tok @ $10/Mtok = 0.5c.
    SessionLocal = sessionmaker(bind=sqlite_engine)

    from contextlib import contextmanager

    @contextmanager
    def _fake_session(*, tenant_id: str) -> Generator[Any, None, None]:  # noqa: ARG001
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(proc_mod, "get_session_with_tenant", _fake_session)

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

    rows = _read_rows(sqlite_engine)
    assert len(rows) == 1
    row = rows[0]
    # Ledger keeps the full (cache-inclusive) input token count.
    assert row.input_tokens == 3000
    assert row.cache_read_tokens == 2000
    # Cost must NOT double-charge the 2000 cache reads at the full input rate.
    assert row.cost_cents == pytest.approx(1.0)


def test_flush_swallows_record_errors(
    processor: UserUsageTracingProcessor,
    sqlite_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failure while writing one record must not crash the drain loop nor leak.
    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(proc_mod, "record_user_usage", _boom)

    token = CURRENT_USER_ID_CONTEXTVAR.set(str(uuid4()))
    try:
        processor.on_span_end(_generation_span(usage={"input_tokens": 1}))
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)

    # Should not raise even though the write fails.
    processor.force_flush()
    assert _read_rows(sqlite_engine) == []
