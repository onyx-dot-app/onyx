import asyncio

import pytest

from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework import setup
from onyx.tracing.framework.create import ensure_trace
from onyx.tracing.framework.provider import DefaultTraceProvider
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.llm_utils import traced_llm_call
from tests.unit.onyx.tracing.capture import CaptureProcessor


@pytest.mark.asyncio
async def test_timed_out_llm_call_records_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = CaptureProcessor()
    provider = DefaultTraceProvider()
    provider.register_processor(processor)
    monkeypatch.setattr(setup, "GLOBAL_TRACE_PROVIDER", provider)
    started = asyncio.Event()

    async def synthesize() -> None:
        with (
            ensure_trace("voice_tts"),
            traced_llm_call(flow=LLMFlow.TTS, model="tts-1", provider="openai"),
        ):
            started.set()
            await asyncio.Future[None]()

    task = asyncio.create_task(synthesize())
    await started.wait()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(task, timeout=0)

    assert task.cancelled()
    (span,) = processor.ended_spans
    assert span.error == {"message": "CancelledError", "data": None}


@pytest.mark.parametrize("mark_error", [False, True])
def test_span_records_exception_type_and_preserves_explicit_error(
    mark_error: bool,
) -> None:
    processor = CaptureProcessor()
    provider = DefaultTraceProvider()
    provider.register_processor(processor)

    with provider.create_trace("test"):
        with pytest.raises(BaseException, match="private details"):
            with provider.create_span(GenerationSpanData()) as span:
                if mark_error:
                    span.set_error({"message": "Safe error", "data": None})
                raise BaseException("private details")

    (ended_span,) = processor.ended_spans
    expected_message = "Safe error" if mark_error else "BaseException"
    assert ended_span.error == {"message": expected_message, "data": None}
