"""Unit tests for ``onyx.tracing.flows`` and ``traced_llm_call``."""

from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.llm_utils import traced_llm_call


def test_llmflow_values_are_lower_snake_case() -> None:
    for member in LLMFlow:
        assert member.value == member.value.lower()
        assert " " not in member.value
        assert "-" not in member.value


def test_llmflow_values_are_unique() -> None:
    values = [m.value for m in LLMFlow]
    assert len(values) == len(set(values))


def test_untagged_sentinels_present() -> None:
    """Sentinels are how the LLM auto-wrap fallback identifies untagged sites."""
    assert LLMFlow.UNTAGGED_INVOKE.value == "untagged_invoke"
    assert LLMFlow.UNTAGGED_STREAM.value == "untagged_stream"


def test_traced_llm_call_records_flow_and_provider_on_span() -> None:
    with trace("test_traced_llm_call"):
        with traced_llm_call(
            flow=LLMFlow.IMAGE_GENERATION,
            model="gpt-image-1",
            provider="openai",
            extra_config={"size": "1024x1024"},
        ) as span:
            assert span.span_data.model == "gpt-image-1"
            assert span.span_data.model_config is not None
            assert span.span_data.model_config["flow"] == "image_generation"
            assert span.span_data.model_config["model_provider"] == "openai"
            assert span.span_data.model_config["size"] == "1024x1024"


def test_traced_llm_call_records_input_messages() -> None:
    with trace("test_traced_llm_input_messages"):
        with traced_llm_call(
            flow=LLMFlow.STT,
            model="whisper-1",
            provider="openai",
            input_messages=[{"audio_format": "webm", "audio_bytes": 1234}],
        ) as span:
            assert span.span_data.input == [
                {"audio_format": "webm", "audio_bytes": 1234}
            ]
