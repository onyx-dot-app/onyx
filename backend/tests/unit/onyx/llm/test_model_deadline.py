"""Generation deadlines interrupt pending provider I/O and preserve parent runs."""

import threading
from concurrent.futures import Future
from unittest.mock import patch

import pytest

from onyx.llm.cancellation import (
    AgentCancelled,
    CancellableStream,
    CancellationSignal,
    current_cancellation,
)
from onyx.llm.exceptions import LLMTimeoutError
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import GenerationRequest
from onyx.llm.multi_llm import LitellmLLM, LitellmTransport


@pytest.mark.parametrize("streaming", [False, True])
def test_deadline_interrupts_pending_provider_call(streaming: bool) -> None:
    cleaned_up = threading.Event()
    parent = CancellationSignal()
    operations: list[Future[None]] = []
    client = LitellmLLM(
        LitellmTransport(
            api_key="test-key",
            model_provider="openai",
            model_name="gpt-5-mini",
            max_input_tokens=1000,
        )
    )

    def pending_response(**_kwargs: object) -> None:
        signal = current_cancellation()
        assert signal is not None
        interrupted = threading.Event()
        try:
            with signal.on_cancel(interrupted.set):
                assert interrupted.wait(2)
            signal.check()
        finally:
            cleaned_up.set()

    context = GenerationContext(cancellation=parent, total_timeout=0.05)
    with (
        parent.on_operation(operations.append),
        patch("onyx.llm.litellm_singleton.litellm.completion", pending_response),
    ):
        with pytest.raises(LLMTimeoutError, match="total timeout"):
            if streaming:
                list(client.stream(GenerationRequest(), context))
            else:
                client.invoke(GenerationRequest(), context)
    assert cleaned_up.is_set()
    assert operations
    for operation in operations:
        operation.result(timeout=1)
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


def test_cleanup_failure_preserves_provider_error() -> None:
    with (
        patch(
            "onyx.llm.litellm_singleton.litellm.completion",
            side_effect=RuntimeError("provider connection failed"),
        ),
        patch(
            "litellm.llms.custom_httpx.http_handler.HTTPHandler.close",
            side_effect=RuntimeError("cleanup failed"),
        ),
    ):
        with pytest.raises(RuntimeError, match="provider connection failed"):
            CancellableStream({"model": "test"}, CancellationSignal(), timeout=1)


def test_cleanup_failure_preserves_cancellation() -> None:
    signal = CancellationSignal()

    def pending(**_kwargs: object) -> None:
        signal.cancel()
        signal.check()

    with (
        patch("onyx.llm.litellm_singleton.litellm.completion", pending),
        patch(
            "litellm.llms.custom_httpx.http_handler.HTTPHandler.close",
            side_effect=RuntimeError("cleanup failed"),
        ),
    ):
        with pytest.raises(AgentCancelled):
            CancellableStream({"model": "test"}, signal, timeout=1)


def test_cancelled_provider_remains_owned_until_cleanup_finishes() -> None:
    signal = CancellationSignal()
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()
    operations: list[Future[None]] = []
    errors: list[BaseException] = []
    active_handler: list[object] = []

    def pending(**kwargs: object) -> None:
        active_handler.append(kwargs["client"])
        signal.cancel()
        signal.check()

    def cleanup(handler: object) -> None:
        if not active_handler or handler is not active_handler[0]:
            return
        cleanup_started.set()
        assert release_cleanup.wait(2)

    def run() -> None:
        try:
            with signal.on_operation(operations.append):
                CancellableStream({"model": "test"}, signal, timeout=1)
        except AgentCancelled:
            pass
        except BaseException as error:
            errors.append(error)

    with (
        patch("onyx.llm.litellm_singleton.litellm.completion", pending),
        patch("litellm.llms.custom_httpx.http_handler.HTTPHandler.close", cleanup),
    ):
        worker = threading.Thread(target=run)
        worker.start()
        try:
            assert cleanup_started.wait(2)
            assert len(operations) == 1
            assert not operations[0].done()
            assert not operations[0].cancel()
        finally:
            release_cleanup.set()
            worker.join(timeout=2)
        assert not worker.is_alive()
        assert not errors
        operations[0].result(timeout=1)


def test_deadline_cancels_generation_without_cancelling_parent() -> None:
    from onyx.llm.multi_llm import _generation_scope

    signal = CancellationSignal()
    context = GenerationContext(cancellation=signal, total_timeout=0.02)
    expired = threading.Event()
    with _generation_scope(context) as generation:
        with generation.on_cancel(expired.set):
            assert expired.wait(timeout=1)
        with pytest.raises(LLMTimeoutError):
            generation.check()
    assert not signal.cancelled


def test_nested_operation_listener_keeps_outer_registration() -> None:
    signal = CancellationSignal()
    operations: list[Future[None]] = []
    inner: Future[None] = Future()
    outer: Future[None] = Future()
    ignored: Future[None] = Future()
    with signal.on_operation(operations.append):
        with signal.on_operation(operations.append):
            signal.track_operation(inner)
        signal.track_operation(outer)
    signal.track_operation(ignored)
    assert operations.count(inner) == 2
    assert operations.count(outer) == 1
    assert ignored not in operations


def test_nested_cancel_listener_keeps_outer_registration() -> None:
    signal = CancellationSignal()
    cancelled = threading.Event()
    with signal.on_cancel(cancelled.set):
        with signal.on_cancel(cancelled.set):
            pass
        signal.cancel()
    assert cancelled.is_set()
