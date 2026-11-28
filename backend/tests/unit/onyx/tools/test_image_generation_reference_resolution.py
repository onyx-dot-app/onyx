"""Tests for ``ImageGenerationTool._resolve_reference_image_file_ids``.

The resolver turns the LLM's ``reference_image_file_ids`` argument into a
cleaned list of file IDs to hand to ``_load_reference_images``. It trusts
the LLM's picks — the LLM can only see file IDs that actually appear in
the conversation (via ``[attached image — file_id: <id>]`` tags on user
messages and the JSON returned by prior generate_image calls), so we
don't re-validate against an allow-list in the tool itself.
"""

import contextvars
import threading
from collections.abc import Generator
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from jsonschema import Draft202012Validator
from pydantic import JsonValue

from onyx.agents.runtime import Agent
from onyx.agents.tools import ToolInvocation
from onyx.db.enums import UsageType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials, ImageShape
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import AssistantMessage, ToolCall
from onyx.tools.interface import parse_tool_arguments
from onyx.tools.models import ToolCallException, ToolContext
from onyx.tools.tool_implementations.images import image_generation_tool as module
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import (
    ImageGenerationArguments,
    ImageGenerationResponse,
)
from onyx.tracing.flows import LLMFlow
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
    @pytest.mark.parametrize(
        "arguments",
        [{}, {"reference_image_file_ids": None}, {"reference_image_file_ids": []}],
    )
    def test_unset_returns_empty_plain_generation(
        self, arguments: dict[str, JsonValue]
    ) -> None:
        parsed = parse_tool_arguments(
            ImageGenerationArguments, {"prompt": "test", **arguments}
        )
        assert parsed.reference_image_file_ids == []
        tool = _make_tool(supports_reference_images=False)
        assert tool._resolve_reference_image_file_ids([]) == []

    def test_passes_llm_supplied_ids_through(self) -> None:
        tool = _make_tool()
        result = tool._resolve_reference_image_file_ids(["upload-1", "gen-1"])
        # Order preserved — first entry is the primary edit source.
        assert result == ["upload-1", "gen-1"]

    @pytest.mark.parametrize("reference_ids", ["not-a-list", ["ok", 123]])
    def test_invalid_reference_ids_are_rejected(self, reference_ids: JsonValue) -> None:
        with pytest.raises(ToolCallException, match="reference_image_file_ids"):
            parse_tool_arguments(
                ImageGenerationArguments,
                {"prompt": "test", "reference_image_file_ids": reference_ids},
            )

    @pytest.mark.parametrize(
        ("reference_ids", "cleaned"),
        [
            (["gen-1", "gen-2", "gen-1"], ["gen-1", "gen-2"]),
            (["  gen-1  ", "", "   "], ["gen-1"]),
        ],
    )
    def test_strips_and_deduplicates_preserving_first_occurrence(
        self, reference_ids: JsonValue, cleaned: list[str]
    ) -> None:
        parsed = parse_tool_arguments(
            ImageGenerationArguments,
            {"prompt": "test", "reference_image_file_ids": reference_ids},
        )
        assert parsed.reference_image_file_ids == cleaned

    def test_provider_without_reference_support_raises(self) -> None:
        tool = _make_tool(supports_reference_images=False)
        with pytest.raises(ToolCallException):
            tool._resolve_reference_image_file_ids(["gen-1"])

    def test_truncates_to_provider_max_preserving_head(self) -> None:
        """When the LLM lists more images than the provider allows, keep the
        HEAD of the list (the primary edit source + earliest extras) rather
        than the tail, since the LLM put the most important one first."""
        tool = _make_tool(max_reference_images=2)
        result = tool._resolve_reference_image_file_ids(["a", "b", "c", "d"])
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
        agent = Agent(
            llm,
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            tools=[tool.bind(lambda: ToolContext())],
        )
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


def test_image_workers_inherit_independent_request_contexts() -> None:
    tenant: contextvars.ContextVar[str] = contextvars.ContextVar(
        "image_worker_tenant", default="unset"
    )
    barrier: threading.Barrier = threading.Barrier(2, timeout=5)
    tool: ImageGenerationTool = _make_tool()
    tool.num_imgs = 2

    def generate(*_args: object) -> ImageGenerationResponse:
        inherited: str = tenant.get()
        tenant.set("worker")
        barrier.wait()
        return ImageGenerationResponse(revised_prompt=inherited, image_data="YWJj")

    token: contextvars.Token[str] = tenant.set("request-tenant")
    try:
        with (
            patch.object(tool, "_generate_image", side_effect=generate),
            patch(
                "onyx.tools.tool_implementations.images.image_generation_tool.save_files",
                return_value=["first", "second"],
            ),
        ):
            result = tool._run(
                ToolInvocation(
                    call_id="images",
                    arguments={"prompt": "test"},
                    cancellation=CancellationSignal(),
                    update=lambda _progress: None,
                ),
                ToolContext(),
            )
        assert result.text.count('"revised_prompt": "request-tenant"') == 2
        assert tenant.get() == "request-tenant"
    finally:
        tenant.reset(token)


@pytest.mark.parametrize(
    "arguments,expected_shape",
    [
        ({"prompt": "test"}, ImageShape.SQUARE),
        (
            {"prompt": "test", "shape": None, "reference_image_file_ids": None},
            ImageShape.SQUARE,
        ),
        ({"prompt": "test", "shape": "portrait"}, ImageShape.PORTRAIT),
    ],
)
def test_image_defaults_at_execution(
    arguments: dict[str, JsonValue], expected_shape: ImageShape
) -> None:
    tool = _make_tool()
    tool.num_imgs = 1
    with (
        patch.object(
            tool,
            "_generate_image",
            return_value=ImageGenerationResponse(
                revised_prompt="test", image_data="YWJj"
            ),
        ) as generate,
        patch(
            "onyx.tools.tool_implementations.images.image_generation_tool.save_files",
            return_value=["image"],
        ),
    ):
        tool._run(
            ToolInvocation(
                call_id="image",
                arguments=arguments,
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            ToolContext(),
        )
    generate.assert_called_once_with("test", expected_shape, None)


def test_image_schema_accepts_null_defaults_and_rejects_invalid_shape() -> None:
    definition = _make_tool().tool_definition()
    assert definition.strict
    assert definition.parameters["additionalProperties"] is False
    assert definition.parameters["required"] == [
        "prompt",
        "shape",
        "reference_image_file_ids",
    ]
    validator = Draft202012Validator(definition.parameters)
    arguments = {"prompt": "test", "shape": None, "reference_image_file_ids": None}
    validator.validate(arguments)
    assert not validator.is_valid({**arguments, "shape": "unsupported"})


# The playground's per-user image limit, checked before the tool generates.

_USER = UUID("00000000-0000-0000-0000-000000000001")


def _limited_tool(user_id: UUID | None, num_imgs: int = 2) -> ImageGenerationTool:
    with patch.object(module, "get_image_generation_provider"):
        return ImageGenerationTool(
            image_generation_credentials=ImageGenerationProviderCredentials(),
            tool_id=1,
            chat_session_id=uuid4(),
            num_imgs=num_imgs,
            user_id=user_id,
        )


@pytest.fixture
def limit_session() -> Generator[MagicMock, None, None]:
    with patch.object(module, "get_session_with_current_tenant") as session:
        session.return_value.__enter__.return_value = MagicMock()
        yield session


@pytest.mark.usefixtures("limit_session")
def test_checks_the_images_about_to_be_made_for_the_user() -> None:
    with (
        patch.object(module, "is_usage_type_limited", return_value=True),
        patch.object(module, "get_current_tenant_id", return_value="t"),
        patch.object(module, "check_usage_and_raise") as check,
    ):
        _limited_tool(_USER, num_imgs=2)._check_image_limit()
    assert check.call_args.kwargs["usage_type"] == UsageType.IMAGE_GENERATIONS
    assert check.call_args.kwargs["pending_amount"] == 2
    assert check.call_args.kwargs["user_id"] == _USER


@pytest.mark.usefixtures("limit_session")
def test_a_refusal_becomes_the_tools_answer() -> None:
    refusal = OnyxError(OnyxErrorCode.RATE_LIMITED, "You have used your 5 images.")
    with (
        patch.object(module, "is_usage_type_limited", return_value=True),
        patch.object(module, "get_current_tenant_id", return_value="t"),
        patch.object(module, "check_usage_and_raise", side_effect=refusal),
        pytest.raises(ToolCallException) as exc_info,
    ):
        _limited_tool(_USER)._check_image_limit()
    assert exc_info.value.llm_facing_message == "You have used your 5 images."


@pytest.mark.parametrize(("user_id", "limited"), [(None, True), (_USER, False)])
def test_skips_without_a_user_or_a_limit(
    limit_session: MagicMock, user_id: UUID | None, limited: bool
) -> None:
    with (
        patch.object(module, "is_usage_type_limited", return_value=limited),
        patch.object(module, "check_usage_and_raise") as check,
    ):
        _limited_tool(user_id)._check_image_limit()
    check.assert_not_called()
    limit_session.assert_not_called()
