from unittest.mock import patch

import litellm

from onyx.llm.utils import find_model_obj
from onyx.llm.utils import get_model_map


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
        "supports_system_messages": True,
        "supports_tool_choice": True,
        "supports_vision": True,
    }

    result1 = find_model_obj(model_map, "openai", "gemini/gemma-3-27b-it")
    assert result1 is not None
    for key, value in _EXPECTED_FIELDS.items():
        assert key in result1
        assert result1[key] == value

    result2 = find_model_obj(model_map, "openai", "gemma-3-27b-it")
    assert result2 is not None
    for key, value in _EXPECTED_FIELDS.items():
        assert key in result2
        assert result2[key] == value

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
        result = find_model_obj(model_map, "openai", "gpt-4o")
        assert result is not None
        assert result["is_correct"] is True

    get_model_map.cache_clear()
