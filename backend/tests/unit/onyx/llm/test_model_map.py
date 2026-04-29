from unittest.mock import patch

import litellm

from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.llm.constants import LlmProviderNames
from onyx.llm.utils import find_model_obj
from onyx.llm.utils import get_model_map
from onyx.llm.utils import model_is_reasoning_model


def test_partial_match_in_model_map() -> None:
    """
    We should handle adding/not adding the provider prefix to the model name.
    """
    get_model_map.cache_clear()

    model_map = get_model_map()

    _EXPECTED_FIELDS = {
        "input_cost_per_audio_per_second": 0,
        "input_cost_per_audio_per_second_above_128k_tokens": 0,
        "input_cost_per_character": 0,
        "input_cost_per_character_above_128k_tokens": 0,
        "input_cost_per_image": 0,
        "input_cost_per_image_above_128k_tokens": 0,
        "input_cost_per_token": 0,
        "input_cost_per_token_above_128k_tokens": 0,
        "input_cost_per_video_per_second": 0,
        "input_cost_per_video_per_second_above_128k_tokens": 0,
        "max_input_tokens": 131072,
        "max_output_tokens": 8192,
        "max_tokens": 8192,
        "output_cost_per_character": 0,
        "output_cost_per_character_above_128k_tokens": 0,
        "output_cost_per_token": 0,
        "output_cost_per_token_above_128k_tokens": 0,
        "source": "https://aistudio.google.com",
        "supports_audio_output": False,
        "supports_function_calling": True,
        "supports_response_schema": True,
        "supports_system_messages": False,
        "supports_tool_choice": True,
        "supports_vision": True,
    }

    result1 = find_model_obj(
        model_map, LlmProviderNames.OPENAI, "gemini/gemma-3-27b-it"
    )
    assert result1 is not None
    for key, value in _EXPECTED_FIELDS.items():
        assert key in result1
        assert result1[key] == value, "Unexpected value for key: {}".format(key)

    result2 = find_model_obj(model_map, LlmProviderNames.OPENAI, "gemma-3-27b-it")
    assert result2 is not None
    for key, value in _EXPECTED_FIELDS.items():
        assert key in result2
        assert result2[key] == value, "Unexpected value for key: {}".format(key)

    get_model_map.cache_clear()


def test_no_overwrite_in_model_map() -> None:
    """Make sure we use the original entry if it exists."""
    # Create a mock model_cost dict with multiple entries for "onyx-llm"
    mock_original_model_cost = {
        "gpt-4o": {
            "is_correct": True,
        },
        "provider/gpt-4o": {
            "is_correct": False,
        },
    }

    with patch.object(litellm, "model_cost", mock_original_model_cost):
        get_model_map.cache_clear()  # Clear the LRU cache to use the patched data

        model_map = get_model_map()
        result = find_model_obj(model_map, LlmProviderNames.OPENAI, "gpt-4o")
        assert result is not None
        assert result["is_correct"] is True

    get_model_map.cache_clear()


def test_model_is_reasoning_model_handles_none_in_model_map() -> None:
    """Regression: litellm may set supports_reasoning=None for some models.
    model_is_reasoning_model must always return a bool, never None."""
    mock_model_cost = {
        "openai/gpt-4o": {
            "supports_reasoning": None,
        },
        "openai/o3": {
            "supports_reasoning": True,
        },
        "openai/gpt-4o-mini": {
            # key missing entirely
        },
    }

    with patch.object(litellm, "model_cost", mock_model_cost):
        get_model_map.cache_clear()
        try:
            # None in map — should fall through to litellm.supports_reasoning
            result = model_is_reasoning_model("gpt-4o", "openai")
            assert result is False or result is True  # must be a bool, not None

            # True in map — should return True
            result = model_is_reasoning_model("o3", "openai")
            assert result is True

            # Missing key — should fall through to litellm.supports_reasoning
            result = model_is_reasoning_model("gpt-4o-mini", "openai")
            assert result is False or result is True
        finally:
            get_model_map.cache_clear()


def test_twelvelabs_pegasus_override_present() -> None:
    get_model_map.cache_clear()
    try:
        model_map = get_model_map()
        model_obj = find_model_obj(
            model_map,
            "twelvelabs",
            "us.twelvelabs.pegasus-1-2-v1:0",
        )
        assert model_obj is not None
        assert model_obj["max_input_tokens"] == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        assert model_obj["max_tokens"] == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        assert model_obj["supports_reasoning"] is False
    finally:
        get_model_map.cache_clear()
