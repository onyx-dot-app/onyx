from onyx.llm.utils import find_model_obj
from onyx.llm.utils import get_model_map


def test_partial_match_in_model_map() -> None:
    model_map = get_model_map()

    _EXPECTED_DICT = {
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

    assert (
        find_model_obj(model_map, "openai", "gemini/gemma-3-27b-it") == _EXPECTED_DICT
    )
    assert find_model_obj(model_map, "openai", "gemma-3-27b-it") == _EXPECTED_DICT
