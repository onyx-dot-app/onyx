"""Tests for ``ImageGenerationTool._resolve_reference_image_file_ids``.

The resolver turns the LLM's ``reference_image_file_ids`` argument into a
cleaned list of file IDs to hand to ``_load_reference_images``. It trusts
the LLM's picks — the LLM can only see file IDs that actually appear in
the conversation (via ``[attached image — file_id: <id>]`` tags on user
messages and the JSON returned by prior generate_image calls), so we
don't re-validate against an allow-list in the tool itself.
"""

import threading
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.agents.runtime import Agent
from onyx.image_gen.interfaces import ImageShape
from onyx.llm.cancellation import AgentCancelled
from onyx.llm.models import AssistantMessage, ToolCall
from onyx.tools.interface import ToolContext
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.images.image_generation_tool import (
    REFERENCE_IMAGE_FILE_IDS_FIELD,
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import ImageGenerationResponse
from onyx.tools.tool_runner import bind_tool
from tests.unit.onyx.agents.fakes import FakeModelClient


def _make_tool(
    supports_reference_images: bool = True,
    max_reference_images: int = 16,
    model: str = "gpt-image-1",
) -> ImageGenerationTool:
    """Construct a tool with a mock provider so no credentials/network are needed."""
    with patch(
        "onyx.tools.tool_implementations.images.image_generation_tool.get_image_generation_provider"
    ) as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.supports_reference_images = supports_reference_images
        mock_provider.max_reference_images = max_reference_images
        item = MagicMock()
        item.model_dump.return_value = {"b64_json": "YWJj", "revised_prompt": "r"}
        response = MagicMock()
        response.data = [item]
        mock_provider.generate_image.return_value = response
        mock_get_provider.return_value = mock_provider

        return ImageGenerationTool(
            image_generation_credentials=MagicMock(),
            tool_id=1,
            chat_session_id=uuid4(),
            model=model,
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


class TestGenerateImageSize:
    @pytest.mark.parametrize(
        "model,shape,expected",
        [
            ("gpt-image-1", ImageShape.SQUARE, "1024x1024"),
            ("gpt-image-1", ImageShape.LANDSCAPE, "1536x1024"),
            ("gpt-image-1", ImageShape.PORTRAIT, "1024x1536"),
            ("dall-e-3", ImageShape.LANDSCAPE, "1792x1024"),
            ("dall-e-3", ImageShape.PORTRAIT, "1024x1792"),
        ],
    )
    def test_size_forwarded_to_provider(
        self, model: str, shape: ImageShape, expected: str
    ) -> None:
        tool = _make_tool(model=model)
        tool._generate_image(prompt="a cat", shape=shape)
        provider = cast(MagicMock, tool.img_provider)
        assert provider.generate_image.call_args.kwargs["size"] == expected


def test_cancelled_image_run_retains_provider_work_until_idle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    tool = _make_tool()

    def generate() -> ImageGenerationResponse:
        started.set()
        try:
            assert release.wait(5)
            raise ValueError("image provider failed during cleanup")
        finally:
            finished.set()

    llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(
            content=[ToolCall(id="image", name=tool.name, arguments={"prompt": "test"})]
        )
    )
    with (
        patch.object(tool, "_generate_image", side_effect=lambda *_args: generate()),
        patch(
            "onyx.tools.tool_implementations.images.image_generation_tool.CANCELLATION_POLL_INTERVAL",
            0.01,
        ),
    ):
        agent = Agent(llm, tools=[bind_tool(tool, ToolContext())])
        run = agent.start(max_steps=1)
        try:
            assert started.wait(2)
            run.cancel()
            with pytest.raises(AgentCancelled):
                run.result(2)
            assert not run.wait_for_idle(0.1)
            assert not finished.is_set()
            with pytest.raises(RuntimeError, match="draining"):
                agent.start(max_steps=1)
        finally:
            release.set()
            assert finished.wait(2)
            assert run.wait_for_idle(2)
    assert "Image provider failed after cancellation" in caplog.text
    assert "image provider failed during cleanup" in caplog.text
