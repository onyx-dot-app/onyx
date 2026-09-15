"""Unit tests for the model id an OpenAI-compatible provider sends upstream.

LiteLLM strips one leading provider prefix before the wire call. An id that
itself starts with that provider (Groq serves "openai/gpt-oss-120b") must
still reach the endpoint unchanged.
"""

from unittest.mock import patch

import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.litellm_singleton import litellm
from onyx.llm.models import LanguageModelInput, UserMessage
from onyx.llm.multi_llm import LitellmLLM


def _completion_kwargs(model_name: str) -> dict:
    llm = LitellmLLM(
        api_key="test-key",
        timeout=30,
        model_provider=LlmProviderNames.OPENAI_COMPATIBLE,
        model_name=model_name,
        max_input_tokens=128_000,
        api_base="https://api.groq.com/openai/v1",
    )
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))
        return dict(mock_completion.call_args.kwargs)


@pytest.mark.parametrize(
    "model_name",
    [
        "openai/gpt-oss-120b",
        "groq/compound",
        "qwen/qwen3-32b",
        "llama-3.3-70b-versatile",
    ],
)
def test_model_id_reaches_endpoint_unchanged(model_name: str) -> None:
    kwargs = _completion_kwargs(model_name)
    sent_model, provider, _, _ = litellm.get_llm_provider(
        model=kwargs["model"], custom_llm_provider=kwargs["custom_llm_provider"]
    )
    assert provider == "openai"
    assert sent_model == model_name
