"""Generation deadlines interrupt pending provider I/O and preserve parent runs."""

import asyncio
import threading
from unittest.mock import AsyncMock, patch

import pytest

from onyx.llm.cancellation import (
    AgentCancelled,
    CancellableStream,
    CancellationSignal,
    _NetworkLoop,
)
from onyx.llm.exceptions import LLMTimeoutError
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import GenerationRequest
from onyx.llm.multi_llm import LitellmLLM, LitellmTransport


@pytest.mark.parametrize("streaming", [False, True])
def test_deadline_interrupts_pending_provider_call(streaming: bool) -> None:
    cleaned_up = threading.Event()
    parent = CancellationSignal()
    client = LitellmLLM(
        LitellmTransport(
            api_key="test-key",
            model_provider="openai",
            model_name="gpt-5-mini",
            max_input_tokens=1000,
        )
    )

    async def pending_response(**_kwargs: object) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()

    context = GenerationContext(cancellation=parent, total_timeout=0.05)
    with patch("onyx.llm.litellm_singleton.litellm.acompletion", pending_response):
        with pytest.raises(LLMTimeoutError, match="total timeout"):
            if streaming:
                list(client.stream(GenerationRequest(), context))
            else:
                client.invoke(GenerationRequest(), context)
    assert cleaned_up.is_set()
    assert not parent.cancelled


@pytest.mark.parametrize("streaming", [False, True])
def test_parent_cancellation_keeps_cancellation_semantics(streaming: bool) -> None:
    parent = CancellationSignal()
    parent.cancel()
    client = LitellmLLM(
        LitellmTransport(
            api_key="test-key",
            model_provider="openai",
            model_name="gpt-5-mini",
            max_input_tokens=1000,
        )
    )
    context = GenerationContext(cancellation=parent, total_timeout=0.05)
    with pytest.raises(AgentCancelled):
        if streaming:
            list(client.stream(GenerationRequest(), context))
        else:
            client.invoke(GenerationRequest(), context)


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("rate_limit", [False, True])
def test_public_calls_normalize_provider_failures(
    streaming: bool, rate_limit: bool
) -> None:
    from litellm.exceptions import RateLimitError, Timeout

    from onyx.llm.exceptions import LLMRateLimitError

    client = LitellmLLM(
        LitellmTransport(
            api_key="test-key",
            model_provider="openai",
            model_name="gpt-5-mini",
            max_input_tokens=1000,
        )
    )
    error_type = RateLimitError if rate_limit else Timeout
    expected = LLMRateLimitError if rate_limit else LLMTimeoutError
    failure = error_type(
        message="provider error", model="gpt-5-mini", llm_provider="openai"
    )
    method = "stream" if streaming else "invoke"
    with patch.object(client.transport, method, side_effect=failure):
        with pytest.raises(expected, match="provider error"):
            if streaming:
                list(client.stream(GenerationRequest()))
            else:
                client.invoke(GenerationRequest())


def test_network_wait_expires_and_cancels_stalled_operation() -> None:
    cleaned = threading.Event()
    network = _NetworkLoop()

    async def pending() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    try:
        with pytest.raises(LLMTimeoutError, match="operation timeout"):
            network.call(pending(), None, timeout=0.02)
        assert cleaned.wait(timeout=1)
    finally:
        network.loop.call_soon_threadsafe(network.loop.stop)
        network.thread.join(timeout=1)
        assert not network.thread.is_alive()


def test_cleanup_failure_preserves_provider_error() -> None:
    provider_error = RuntimeError("provider connection failed")
    cleanup_error = RuntimeError("cleanup failed")
    with (
        patch(
            "onyx.llm.litellm_singleton.litellm.acompletion",
            new=AsyncMock(side_effect=provider_error),
        ),
        patch(
            "litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.close",
            new=AsyncMock(side_effect=cleanup_error),
        ),
    ):
        with pytest.raises(RuntimeError, match="provider connection failed"):
            CancellableStream({}, CancellationSignal(), isolated_client=True, timeout=1)


def test_cleanup_failure_preserves_cancellation() -> None:
    signal = CancellationSignal()
    started = threading.Event()
    stopped = threading.Event()
    errors: list[BaseException] = []

    async def pending(**_kwargs: object) -> None:
        started.set()
        await asyncio.Event().wait()

    def run() -> None:
        try:
            CancellableStream({}, signal, isolated_client=True, timeout=1)
        except AgentCancelled:
            stopped.set()
        except BaseException as error:
            errors.append(error)

    with (
        patch("onyx.llm.litellm_singleton.litellm.acompletion", pending),
        patch(
            "litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.close",
            new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
        ),
    ):
        worker = threading.Thread(target=run)
        worker.start()
        try:
            assert started.wait(timeout=1)
            signal.cancel()
            assert stopped.wait(timeout=1), errors
        finally:
            signal.cancel()
            worker.join(timeout=2)
        assert not worker.is_alive()
        assert not errors
