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


def _prepare(
    prefix: list[ChatCompletionMessage],
    suffix: list[ChatCompletionMessage] | None = None,
) -> list[ChatCompletionMessage]:
    prepared, _ = process_with_prompt_cache(
        LLMConfig(
            model_provider="anthropic",
            model_name="claude-haiku-4-5",
            temperature=0,
            max_input_tokens=200_000,
        ),
        prefix,
        suffix or [],
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


@pytest.mark.parametrize(
    ("prefix_markers", "suffix_marker"), [(2, True), (3, False), (3, True), (4, False)]
)
def test_existing_markers_share_the_request_breakpoint_budget(
    prefix_markers: int, suffix_marker: bool
) -> None:
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    content: list[TextContentPart | ImageContentPart] = [
        TextContentPart(
            text=f"Shared context {index}",
            cache_control={"type": "ephemeral", "ttl": "1h"}
            if index == 0
            else {"type": "ephemeral"},
        )
        for index in range(prefix_markers - 1)
    ]
    content.append(
        ImageContentPart(
            image_url=ImageUrlDetail(url=_IMAGE),
            cache_control={"type": "ephemeral"},
        )
    )
    prefix: list[ChatCompletionMessage] = [
        SystemMessage(content="Instructions"),
        UserMessage(content=content),
        UserMessage(content="Question"),
    ]
    suffix: list[ChatCompletionMessage] = (
        [UserMessage(content="Reminder", cache_control={"type": "ephemeral"})]
        if suffix_marker
        else []
    )
    original = deepcopy([*prefix, *suffix])
    prepared = _prepare(prefix, suffix)
    assert prepared[1] == prefix[1]
    if suffix:
        assert prepared[-1] == suffix[0]
    assert [*prefix, *suffix] == original

    body: dict[str, Any] = AnthropicConfig().transform_request(
        model="claude-haiku-4-5",
        messages=[message.model_dump(exclude_none=True) for message in prepared],
        optional_params={"max_tokens": 32},
        litellm_params={},
        headers={},
    )
    markers = [
        block["cache_control"]
        for message in body["messages"]
        for block in message["content"]
        if block.get("cache_control") is not None
    ]
    markers.extend(
        block["cache_control"]
        for block in body.get("system", [])
        if block.get("cache_control") is not None
    )
    assert len(markers) == 4
    assert markers[0] == {"type": "ephemeral", "ttl": "1h"}
    assert prepared[0].cache_control is None
    assert prepared[2].cache_control == (
        {"type": "ephemeral"} if prefix_markers + int(suffix_marker) < 4 else None
    )


def test_existing_message_marker_keeps_its_lifetime() -> None:
    prefix: list[ChatCompletionMessage] = [
        SystemMessage(
            content="Instructions", cache_control={"type": "ephemeral", "ttl": "1h"}
        ),
        UserMessage(content="Question"),
    ]
    prepared = _prepare(prefix)
    assert prepared[0] == prefix[0]
    assert prepared[-1].cache_control == {"type": "ephemeral"}


@pytest.mark.parametrize("multimodal", [False, True])
def test_continuation_preserves_prefix_and_suffix_markers_on_wire(
    multimodal: bool,
) -> None:
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    prefix: list[ChatCompletionMessage] = [
        UserMessage(
            content="Shared context",
            cache_control={"type": "ephemeral", "ttl": "1h"},
        )
    ]
    suffix: list[ChatCompletionMessage] = [
        UserMessage(
            content=[
                TextContentPart(text="Question"),
                ImageContentPart(image_url=ImageUrlDetail(url=_IMAGE)),
            ]
            if multimodal
            else "Question",
            cache_control={"type": "ephemeral"},
        )
    ]
    original = deepcopy((prefix, suffix))
    prepared, _ = process_with_prompt_cache(
        LLMConfig(
            model_provider="anthropic",
            model_name="claude-haiku-4-5",
            temperature=0,
            max_input_tokens=200_000,
        ),
        prefix,
        suffix,
        continuation=True,
        with_metadata=False,
    )
    assert len(prepared) == 1
    body: dict[str, Any] = AnthropicConfig().transform_request(
        model="claude-haiku-4-5",
        messages=[message.model_dump(exclude_none=True) for message in prepared],
        optional_params={"max_tokens": 32},
        litellm_params={},
        headers={},
    )
    blocks = body["messages"][0]["content"]
    assert blocks[0]["text"] == "Shared context"
    assert blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert sum("cache_control" in block for block in blocks) == 2
    assert (prefix, suffix) == original
