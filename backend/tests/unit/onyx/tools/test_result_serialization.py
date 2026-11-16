import pytest

from onyx.tools.models import CustomToolCallSummary, CustomToolUserFileSnapshot


@pytest.mark.parametrize("response_type", ["image", "csv", "json"])
def test_custom_result_json_distinguishes_files_from_ordinary_data(
    response_type: str,
) -> None:
    data = {"file_ids": ["file"], "description": "keep this field"}
    summary = CustomToolCallSummary(
        tool_name="custom",
        response_type=response_type,
        tool_result={"file_ids": ["file"]} if response_type != "json" else data,
    )
    restored = CustomToolCallSummary.model_validate_json(summary.model_dump_json())
    if response_type == "json":
        assert restored.tool_result == data
    else:
        assert isinstance(restored.tool_result, CustomToolUserFileSnapshot)
        assert restored.tool_result.file_ids == ["file"]
