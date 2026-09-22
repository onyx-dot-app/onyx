import pytest

from onyx.llm import model_capabilities
from onyx.llm.model_capabilities import model_is_reasoning_model


def test_model_is_reasoning_model() -> None:
    """Test that reasoning models are correctly identified and non-reasoning models are not"""

    # Models that should be identified as reasoning models
    reasoning_models = [
        ("o3", "openai"),
        ("o3-mini", "openai"),
        ("o4-mini", "openai"),
        ("deepseek-reasoner", "deepseek"),
        ("deepseek-r1", "openrouter/deepseek"),
        ("claude-sonnet-4-20250514", "anthropic"),
    ]

    # Models that should NOT be identified as reasoning models
    non_reasoning_models = [
        ("gpt-4o", "openai"),
        ("claude-3-5-sonnet-20240620", "anthropic"),
    ]

    # Test reasoning models
    for model_name, provider in reasoning_models:
        assert model_is_reasoning_model(model_name, provider) is True, (
            f"Expected {provider}/{model_name} to be identified as a reasoning model"
        )

    # Test non-reasoning models
    for model_name, provider in non_reasoning_models:
        assert model_is_reasoning_model(model_name, provider) is False, (
            f"Expected {provider}/{model_name} to NOT be identified as a reasoning model"
        )


def test_unknown_model_does_not_probe_external_hosts() -> None:
    assert model_is_reasoning_model("not-in-map-model", "custom") is False


def test_native_profile_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_capabilities, "get_model_map", dict)
    assert model_is_reasoning_model("gpt-5-mini", "openai") is True
    assert model_is_reasoning_model("gpt-4o", "openai") is False
