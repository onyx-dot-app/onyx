from onyx.llm.utils import model_is_reasoning_model


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
        assert (
            model_is_reasoning_model(model_name, provider) is True
        ), f"Expected {provider}/{model_name} to be identified as a reasoning model"

    # Test non-reasoning models
    for model_name, provider in non_reasoning_models:
        assert (
            model_is_reasoning_model(model_name, provider) is False
        ), f"Expected {provider}/{model_name} to NOT be identified as a reasoning model"
