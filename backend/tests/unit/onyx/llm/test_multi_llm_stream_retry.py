from collections.abc import Iterator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from litellm.exceptions import Timeout as LiteLLMTimeout

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.model_response import Delta
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LitellmLLM


def _make_fake_llm() -> MagicMock:
    llm = MagicMock()
    llm.config.model_name = "gpt-test"
    llm.config.model_provider = "openai"
    llm._timeout = 30
    llm._track_llm_cost = MagicMock()
    return llm


def _make_prompt() -> LanguageModelInput:
    return [UserMessage(content="hello")]


def _make_stream_response(content: str) -> ModelResponseStream:
    return ModelResponseStream(
        id="chunk-1",
        created="1",
        choice=StreamingChoice(delta=Delta(content=content)),
    )


def test_stream_retries_timeout_before_first_chunk() -> None:
    fake_llm = _make_fake_llm()
    translated_chunk = _make_stream_response("hello")
    attempt_count = 0

    def completion_side_effect(**_kwargs: object) -> list[object]:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise LiteLLMTimeout("timed out", "gpt-test", "openai")
        return [object()]

    fake_llm._completion = MagicMock(side_effect=completion_side_effect)

    with (
        patch("onyx.llm.multi_llm.LLM_FIRST_CHUNK_MAX_RETRIES", 1),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch(
            "onyx.llm.model_response.from_litellm_model_response_stream",
            return_value=translated_chunk,
        ),
        patch("onyx.llm.multi_llm.logger") as mock_logger,
    ):
        # Bind the unbound method to a fake self to isolate retry behavior.
        results = list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    assert len(results) == 1
    assert results[0].choice.delta.content == "hello"
    assert fake_llm._completion.call_count == 2
    mock_logger.warning.assert_called_once()


def test_stream_does_not_retry_after_first_chunk() -> None:
    fake_llm = _make_fake_llm()
    translated_chunk = _make_stream_response("partial")

    def stream_then_timeout() -> Iterator[object]:
        yield object()
        raise LiteLLMTimeout("timed out", "gpt-test", "openai")

    fake_llm._completion = MagicMock(return_value=stream_then_timeout())

    with (
        patch("onyx.llm.multi_llm.LLM_FIRST_CHUNK_MAX_RETRIES", 2),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch(
            "onyx.llm.model_response.from_litellm_model_response_stream",
            return_value=translated_chunk,
        ),
        patch("onyx.llm.multi_llm.logger") as mock_logger,
    ):
        # Bind the unbound method to a fake self to isolate retry behavior.
        with pytest.raises(LiteLLMTimeout):
            list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    assert fake_llm._completion.call_count == 1
    mock_logger.warning.assert_not_called()
