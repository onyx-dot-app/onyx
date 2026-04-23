"""Tests for ``ImageGenerationTool._resolve_reference_image_file_ids``.

The resolver turns the LLM's ``reference_image_file_ids`` argument into a
cleaned list of file IDs to hand to ``_load_reference_images``. It trusts
the LLM's picks — the LLM can only see file IDs that actually appear in
the conversation (via ``[attached image — file_id: <id>]`` tags on user
messages and the JSON returned by prior generate_image calls), so we
don't re-validate against an allow-list in the tool itself.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    REFERENCE_IMAGE_FILE_IDS_FIELD,
)


def _make_tool(
    supports_reference_images: bool = True,
    max_reference_images: int = 16,
) -> ImageGenerationTool:
    """Construct a tool with a mock provider so no credentials/network are needed."""
    with patch(
        "onyx.tools.tool_implementations.images.image_generation_tool.get_image_generation_provider"
    ) as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.supports_reference_images = supports_reference_images
        mock_provider.max_reference_images = max_reference_images
        mock_get_provider.return_value = mock_provider

        return ImageGenerationTool(
            image_generation_credentials=MagicMock(),
            tool_id=1,
            emitter=MagicMock(),
            model="gpt-image-1",
            provider="openai",
        )


class TestResolveReferenceImageFileIds:
    def test_unset_returns_empty_plain_generation(self) -> None:
        tool = _make_tool()
        assert tool._resolve_reference_image_file_ids(llm_kwargs={}) == []

    def test_empty_list_is_treated_like_unset(self) -> None:
        tool = _make_tool()
        result = tool._resolve_reference_image_file_ids(
            llm_kwargs={REFERENCE_IMAGE_FILE_IDS_FIELD: []},
        )
        assert result == []

    def test_passes_llm_supplied_ids_through(self) -> None:
        tool = _make_tool()
        result = tool._resolve_reference_image_file_ids(
            llm_kwargs={REFERENCE_IMAGE_FILE_IDS_FIELD: ["upload-1", "gen-1"]},
        )
        # Order preserved — first entry is the primary edit source.
        assert result == ["upload-1", "gen-1"]

    def test_invalid_shape_raises(self) -> None:
        tool = _make_tool()
        with pytest.raises(ToolCallException):
            tool._resolve_reference_image_file_ids(
                llm_kwargs={REFERENCE_IMAGE_FILE_IDS_FIELD: "not-a-list"},
            )

    def test_non_string_element_raises(self) -> None:
        tool = _make_tool()
        with pytest.raises(ToolCallException):
            tool._resolve_reference_image_file_ids(
                llm_kwargs={REFERENCE_IMAGE_FILE_IDS_FIELD: ["ok", 123]},
            )

    def test_deduplicates_preserving_first_occurrence(self) -> None:
        tool = _make_tool()
        result = tool._resolve_reference_image_file_ids(
            llm_kwargs={REFERENCE_IMAGE_FILE_IDS_FIELD: ["gen-1", "gen-2", "gen-1"]},
        )
        assert result == ["gen-1", "gen-2"]

    def test_strips_whitespace_and_skips_empty_strings(self) -> None:
        tool = _make_tool()
        result = tool._resolve_reference_image_file_ids(
            llm_kwargs={REFERENCE_IMAGE_FILE_IDS_FIELD: ["  gen-1  ", "", "   "]},
        )
        assert result == ["gen-1"]

    def test_provider_without_reference_support_raises(self) -> None:
        tool = _make_tool(supports_reference_images=False)
        with pytest.raises(ToolCallException):
            tool._resolve_reference_image_file_ids(
                llm_kwargs={REFERENCE_IMAGE_FILE_IDS_FIELD: ["gen-1"]},
            )

    def test_truncates_to_provider_max_preserving_head(self) -> None:
        """When the LLM lists more images than the provider allows, keep the
        HEAD of the list (the primary edit source + earliest extras) rather
        than the tail, since the LLM put the most important one first."""
        tool = _make_tool(max_reference_images=2)
        result = tool._resolve_reference_image_file_ids(
            llm_kwargs={REFERENCE_IMAGE_FILE_IDS_FIELD: ["a", "b", "c", "d"]},
        )
        assert result == ["a", "b"]
