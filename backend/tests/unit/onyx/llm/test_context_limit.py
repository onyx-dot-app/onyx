"""Provider context failures keep their cause across the shared LLM boundary."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from litellm.exceptions import ContextWindowExceededError

from onyx.llm.exceptions import LLMContextLimitError, litellm_exception_to_safe_error
from onyx.llm.litellm_models import Delta, ModelResponseStream, StreamingChoice
from onyx.llm.models import GenerationRequest
from onyx.llm.multi_llm import LitellmLLM


@pytest.mark.parametrize(
    "streaming, after_chunk", [(False, False), (True, False), (True, True)]
)
def test_context_limit_normalization(streaming: bool, after_chunk: bool) -> None:
    client = LitellmLLM(
        api_key=None,
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=1000,
    )
    failure = ContextWindowExceededError(
        message="provider context overflow", model="gpt-5-mini", llm_provider="openai"
    )

    def chunks() -> Iterator[ModelResponseStream]:
        yield ModelResponseStream(
            id="partial",
            created="1",
            choice=StreamingChoice(delta=Delta(content="partial")),
        )
        raise failure

    with patch.object(
        client,
        "stream_raw" if streaming else "invoke_raw",
        side_effect=None if after_chunk else failure,
        return_value=chunks() if after_chunk else None,
    ):
        with pytest.raises(LLMContextLimitError) as caught:
            if streaming:
                list(client.stream(GenerationRequest()))
            else:
                client.invoke(GenerationRequest())
    assert caught.value.__cause__ is failure
    classified = litellm_exception_to_safe_error(caught.value)
    assert classified.error_code == "CONTEXT_TOO_LONG"
    assert not classified.is_retryable
