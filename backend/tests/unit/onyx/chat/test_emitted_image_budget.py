"""Charge image tokens only when the translated request contains the image."""

from collections.abc import Mapping
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import litellm
import pytest
from litellm.types.utils import Delta

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import NullEmitter
from onyx.chat.llm_loop import construct_message_history, run_llm_loop
from onyx.chat.models import ChatLoadedFile, ChatMessageSimple, ExtractedContextFiles
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType
from onyx.llm.exceptions import InputBudgetExceededError
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.input_budget import estimate_request_tokens
from onyx.llm.multi_llm import LitellmLLM

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _run_image_history(
    history: list[ChatMessageSimple],
    max_input_tokens: int,
    *,
    capped: bool,
    vision: bool,
    context_files: ExtractedContextFiles | None = None,
) -> tuple[Mapping[str, Any], int]:
    llm = LitellmLLM(
        api_key="test-key",
        model_provider="azure",
        model_name="gpt-4o",
        max_input_tokens=max_input_tokens,
        timeout=30,
    )
    response = litellm.ModelResponse(
        choices=[
            litellm.Choices(
                delta=Delta(role="assistant", content="done"), finish_reason="stop"
            )
        ],
        model="gpt-4o",
    )
    with (
        patch("litellm.completion", return_value=[response]) as completion,
        patch("onyx.llm.litellm_singleton.config.initialize_litellm"),
        patch("onyx.chat.llm_step.ENABLE_AZURE_IMAGE_CAP", capped),
        patch("onyx.chat.llm_step._AZURE_DEFAULT_IMAGE_CAP", 1),
        patch("onyx.chat.llm_step.model_supports_image_input", return_value=vision),
        patch("onyx.chat.llm_loop.model_supports_image_input", return_value=vision),
        patch("onyx.chat.llm_loop.get_default_base_system_prompt", return_value=""),
        patch(
            "onyx.chat.llm_loop.get_session_with_current_tenant",
            return_value=nullcontext(MagicMock()),
        ),
        patch(
            "onyx.llm.multi_llm.estimate_request_tokens", wraps=estimate_request_tokens
        ) as final_estimator,
    ):
        run_llm_loop(
            emitter=NullEmitter(),
            state_container=ChatStateContainer(),
            simple_chat_history=history,
            tools=[],
            custom_agent_prompt=None,
            context_files=(
                context_files
                if context_files is not None
                else ExtractedContextFiles(
                    file_texts=[],
                    image_files=[],
                    total_token_count=0,
                    use_as_search_filter=False,
                    file_metadata=[],
                    uncapped_token_count=0,
                )
            ),
            persona=None,
            user_memory_context=None,
            llm=llm,
            token_counter=get_llm_token_counter(llm),
        )
    completion.assert_called_once()
    return completion.call_args.kwargs, final_estimator.call_args.args[3]


def _image_history(*, invalid_images: bool = False) -> list[ChatMessageSimple]:
    images = [
        ChatLoadedFile(
            file_id=f"image-{index}",
            file_type=ChatFileType.IMAGE,
            filename=f"image-{index}.png",
            content=_PNG_BYTES if index == 0 or not invalid_images else b"invalid",
            content_text=None,
            token_count=3_000,
        )
        for index in range(3)
    ]
    return [
        ChatMessageSimple(
            message="Keep this earlier question.",
            token_count=10,
            message_type=MessageType.USER,
        ),
        ChatMessageSimple(
            message="Keep this earlier answer.",
            token_count=10,
            message_type=MessageType.ASSISTANT,
        ),
        ChatMessageSimple(
            message="Describe the images.",
            token_count=9_010,
            image_token_count=9_000,
            message_type=MessageType.USER,
            image_files=images,
        ),
    ]


@pytest.mark.parametrize(
    (
        "capped",
        "vision",
        "invalid_images",
        "maximum",
        "expected_images",
        "expected_tokens",
    ),
    [
        (True, True, False, 8_000, 1, 3_000),
        (False, True, True, 8_000, 1, 3_000),
        (False, False, False, 8_000, 0, 0),
        (False, True, False, 15_000, 3, 9_000),
    ],
)
def test_only_emitted_images_consume_the_request_budget(
    capped: bool,
    vision: bool,
    invalid_images: bool,
    maximum: int,
    expected_images: int,
    expected_tokens: int,
) -> None:
    history = _image_history(invalid_images=invalid_images)
    saved_images = history[-1].image_files
    saved_counts = [
        (message.token_count, message.image_token_count) for message in history
    ]
    request, image_tokens = _run_image_history(
        history, maximum, capped=capped, vision=vision
    )
    messages = request["messages"]
    assert messages[0]["content"] == "Keep this earlier question."
    assert messages[1]["content"] == "Keep this earlier answer."
    emitted_parts = [
        part
        for message in messages
        if isinstance(message.get("content"), list)
        for part in message["content"]
    ]
    assert sum(part["type"] == "image_url" for part in emitted_parts) == expected_images
    assert image_tokens == expected_tokens
    assert all("token_count" not in part for part in emitted_parts)
    assert history[-1].image_files is saved_images
    assert [
        (message.token_count, message.image_token_count) for message in history
    ] == saved_counts
    if not vision:
        assert sum("image-" in part.get("text", "") for part in emitted_parts) == 3


def test_project_images_are_charged_without_a_stored_message_image_cost() -> None:
    history = _image_history()
    history[-1].token_count = 10
    history[-1].image_token_count = 0
    with pytest.raises(InputBudgetExceededError):
        _run_image_history(history, 8_000, capped=False, vision=True)


@pytest.mark.parametrize("vision", [True, False])
def test_mixed_project_images_do_not_evict_project_text(vision: bool) -> None:
    history = _image_history()
    history[-1].token_count = 10
    history[-1].image_token_count = 0
    images = history[-1].image_files
    assert images is not None
    context_files = ExtractedContextFiles(
        file_texts=["Keep this project text."],
        image_files=images,
        total_token_count=9_010,
        use_as_search_filter=False,
        file_metadata=[],
        uncapped_token_count=9_010,
    )
    request, image_tokens = _run_image_history(
        history, 8_000, capped=True, vision=vision, context_files=context_files
    )
    assert request["messages"][0]["content"] == "Keep this earlier question."
    assert any(
        isinstance(message.get("content"), str)
        and "Keep this project text." in message["content"]
        for message in request["messages"]
    )
    assert image_tokens == (3_000 if vision else 0)
    assert context_files.total_token_count == 9_010
    assert history[-1].image_token_count == 0
    with pytest.raises(InputBudgetExceededError):
        construct_message_history(
            system_prompt=None,
            custom_agent_prompt=None,
            simple_chat_history=history,
            reminder_message=None,
            context_files=context_files,
            available_tokens=8_000,
        )
