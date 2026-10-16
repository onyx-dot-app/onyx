import pytest

from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
    current_cancellation,
)


def test_cancellation_scope_and_callback_lifetime() -> None:
    parent, child = CancellationSignal(), CancellationSignal()
    observed: list[str] = []
    with cancellation_scope(parent):
        with cancellation_scope(child):
            assert current_cancellation() is child
        assert current_cancellation() is parent
        with parent.on_cancel(lambda: observed.append("removed")):
            pass
        with parent.on_cancel(lambda: observed.append("active")):
            parent.cancel()
            parent.cancel()
        with parent.on_cancel(lambda: observed.append("late")):
            pass
        with pytest.raises(AgentCancelled):
            parent.check()
    assert current_cancellation() is None
    assert observed == ["active", "late"]


@pytest.mark.parametrize("streaming", [False, True])
def test_cancelled_generation_never_calls_provider(streaming: bool) -> None:
    from unittest.mock import patch

    from onyx.llm.interfaces import GenerationContext
    from onyx.llm.models import GenerationRequest
    from onyx.llm.multi_llm import LitellmLLM

    signal = CancellationSignal()
    signal.cancel()
    client = LitellmLLM(
        api_key="test",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=1000,
    )
    with patch("onyx.llm.litellm_singleton.litellm.completion") as completion:
        with pytest.raises(AgentCancelled):
            if streaming:
                list(
                    client.stream(
                        GenerationRequest(), GenerationContext(cancellation=signal)
                    )
                )
            else:
                client.invoke(
                    GenerationRequest(), GenerationContext(cancellation=signal)
                )
    completion.assert_not_called()
    assert current_cancellation() is None


@pytest.mark.parametrize("rejection", [False, True])
def test_cancelled_provider_failure_does_not_retry(rejection: bool) -> None:
    from unittest.mock import patch

    from litellm.exceptions import BadRequestError, Timeout

    from onyx.llm.interfaces import GenerationContext
    from onyx.llm.models import GenerationErrorEvent, GenerationRequest
    from onyx.llm.multi_llm import LitellmLLM

    signal = CancellationSignal()
    client = LitellmLLM(
        api_key="test",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=1000,
    )

    def fail(**_kwargs: object) -> None:
        signal.cancel()
        error = BadRequestError if rejection else Timeout
        raise error(
            message="provider failure", model="gpt-5-mini", llm_provider="openai"
        )

    errors: list[GenerationErrorEvent] = []
    with patch(
        "onyx.llm.litellm_singleton.litellm.completion", side_effect=fail
    ) as completion:
        with pytest.raises(AgentCancelled):
            errors.extend(
                event
                for event in client.stream(
                    GenerationRequest(), GenerationContext(cancellation=signal)
                )
                if isinstance(event, GenerationErrorEvent)
            )
    assert completion.call_count == 1
    assert [event.stop_reason for event in errors] == ["aborted"]
    assert current_cancellation() is None


def test_stream_cancellation_preserves_partial_text_and_closes_client() -> None:
    from unittest.mock import patch

    from litellm import ModelResponse

    from onyx.llm.interfaces import GenerationContext
    from onyx.llm.models import (
        AssistantMessage,
        GenerationErrorEvent,
        GenerationRequest,
        TextDeltaEvent,
        apply_generation_event,
    )
    from onyx.llm.multi_llm import LitellmLLM

    signal = CancellationSignal()
    client = LitellmLLM(
        api_key="test",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=1000,
    )
    chunks = [
        ModelResponse(
            stream=True, choices=[{"index": 0, "delta": {"content": "partial"}}]
        ),
        ModelResponse(
            stream=True, choices=[{"index": 0, "delta": {"content": "late"}}]
        ),
    ]
    message = AssistantMessage()
    errors: list[GenerationErrorEvent] = []
    with (
        patch.object(client, "_uses_isolated_client", return_value=True),
        patch("litellm.HTTPHandler") as handler,
        patch.object(client, "_completion", return_value=iter(chunks)) as completion,
    ):
        with pytest.raises(AgentCancelled):
            for event in client.stream(
                GenerationRequest(), GenerationContext(cancellation=signal)
            ):
                apply_generation_event(message, event)
                if isinstance(event, TextDeltaEvent):
                    signal.cancel()
                if isinstance(event, GenerationErrorEvent):
                    errors.append(event)
        handler.return_value.close.assert_called_once()
    assert message.text == "partial"
    assert message.stop_reason == "aborted"
    assert len(errors) == 1
    assert completion.call_count == 1
    assert current_cancellation() is None
