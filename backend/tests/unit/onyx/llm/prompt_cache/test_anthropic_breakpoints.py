from copy import deepcopy
from typing import Any

import pytest

from onyx.llm.interfaces import LLMConfig
from onyx.llm.model_request import (
    AssistantMessage,
    ChatCompletionMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from onyx.llm.models import ImageContentPart, ImageUrlDetail, TextContentPart
from onyx.llm.prompt_cache.processor import process_with_prompt_cache

_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1cAAAAASUVORK5CYII="
)


def _prepare(prefix: list[ChatCompletionMessage]) -> list[ChatCompletionMessage]:
    prepared, _ = process_with_prompt_cache(
        LLMConfig(
            model_provider="anthropic",
            model_name="claude-haiku-4-5",
            temperature=0,
            max_input_tokens=200_000,
        ),
        prefix,
        [],
        with_metadata=False,
    )
    return prepared


@pytest.mark.parametrize("image_last", [False, True])
def test_multimodal_breakpoint_survives_anthropic_serialization(
    image_last: bool,
) -> None:
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    content: list[TextContentPart | ImageContentPart] = [
        TextContentPart(text="Describe this image"),
        ImageContentPart(image_url=ImageUrlDetail(url=_IMAGE)),
    ]
    if not image_last:
        content.reverse()
    prefix: list[ChatCompletionMessage] = [UserMessage(content=content)]
    original = deepcopy(prefix)
    prepared = _prepare(prefix)
    body: dict[str, Any] = AnthropicConfig().transform_request(
        model="claude-haiku-4-5",
        messages=[message.model_dump(exclude_none=True) for message in prepared],
        optional_params={"max_tokens": 32},
        litellm_params={},
        headers={},
    )
    blocks = body["messages"][0]["content"]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0].get("cache_control") is None
    assert blocks[-1]["type"] == ("image" if image_last else "text")
    assert prefix == original


def test_shared_context_has_identical_breakpoint_for_different_questions() -> None:
    context = [
        SystemMessage(content="System instructions"),
        UserMessage(content="Shared project documents"),
    ]
    first = _prepare([*context, UserMessage(content="First question")])
    second = _prepare([*context, UserMessage(content="Different question")])
    assert first[:2] == second[:2]
    assert first[1].cache_control == {"type": "ephemeral"}
    assert first[-1].cache_control == {"type": "ephemeral"}
    assert second[-1].cache_control == {"type": "ephemeral"}
    assert all(message.cache_control is None for message in context)


def test_tool_round_keeps_context_and_tail_breakpoints() -> None:
    prefix: list[ChatCompletionMessage] = [
        SystemMessage(content="System instructions"),
        UserMessage(content="Shared project documents"),
        UserMessage(content="Question"),
        AssistantMessage(content="Checking a tool"),
        ToolMessage(content="Tool result", tool_call_id="call_1"),
    ]
    prepared = _prepare(prefix)
    assert [
        index for index, message in enumerate(prepared) if message.cache_control
    ] == [0, 1, 4]
    assert all(message.cache_control is None for message in prefix)
