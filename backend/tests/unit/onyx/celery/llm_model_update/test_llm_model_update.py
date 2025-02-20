import pytest

from onyx.background.celery.tasks.llm_model_update.tasks import (
    _process_model_list_response,
)


@pytest.mark.parametrize(
    "input_data,expected_result,expected_error,error_match",
    [
        # Success cases
        (
            ["gpt-4", "gpt-3.5-turbo", "claude-2"],
            ["gpt-4", "gpt-3.5-turbo", "claude-2"],
            None,
            None,
        ),
        (
            [
                {"model_name": "gpt-4", "other_field": "value"},
                {"model_name": "gpt-3.5-turbo", "other_field": "value"},
            ],
            ["gpt-4", "gpt-3.5-turbo"],
            None,
            None,
        ),
        (
            [
                {"id": "gpt-4", "other_field": "value"},
                {"id": "gpt-3.5-turbo", "other_field": "value"},
            ],
            ["gpt-4", "gpt-3.5-turbo"],
            None,
            None,
        ),
        (
            {"data": ["gpt-4", "gpt-3.5-turbo"]},
            ["gpt-4", "gpt-3.5-turbo"],
            None,
            None,
        ),
        (
            {"models": ["gpt-4", "gpt-3.5-turbo"]},
            ["gpt-4", "gpt-3.5-turbo"],
            None,
            None,
        ),
        (
            {"models": [{"id": "gpt-4"}, {"id": "gpt-3.5-turbo"}]},
            ["gpt-4", "gpt-3.5-turbo"],
            None,
            None,
        ),
        # Error cases
        (
            "not a list",
            None,
            ValueError,
            "Invalid response from API - expected list",
        ),
        (
            {"wrong_field": []},
            None,
            ValueError,
            "Invalid response from API - expected dict with 'data' or 'models' field",
        ),
        (
            [{"wrong_field": "value"}],
            None,
            ValueError,
            "Invalid item in model list - expected dict with model_name or id",
        ),
        (
            [42],
            None,
            ValueError,
            "Invalid item in model list - expected string or dict",
        ),
    ],
)
def test_process_model_list_response(
    input_data: dict | list,
    expected_result: list[str] | None,
    expected_error: type[Exception] | None,
    error_match: str | None,
) -> None:
    if expected_error:
        with pytest.raises(expected_error, match=error_match):
            _process_model_list_response(input_data)
    else:
        result = _process_model_list_response(input_data)
        assert result == expected_result
