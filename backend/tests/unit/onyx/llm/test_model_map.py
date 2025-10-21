from onyx.llm.utils import find_model_obj
from onyx.llm.utils import get_model_map


def test_partial_match_in_model_map() -> None:
    """
    We should handle adding/not adding the provider prefix to the model name.
    """

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
