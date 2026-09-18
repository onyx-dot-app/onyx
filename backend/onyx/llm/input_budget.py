import json
from collections.abc import Callable
from typing import Any

from onyx.llm.models import ImageContentPart, LanguageModelInput, UserMessage


def count_prompt_image_tokens(prompt: LanguageModelInput) -> int:
    messages = prompt if isinstance(prompt, list) else [prompt]
    return sum(
        part.token_count
        for message in messages
        if isinstance(message, UserMessage) and isinstance(message.content, list)
        for part in message.content
        if isinstance(part, ImageContentPart)
    )


def estimate_request_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    token_counter: Callable[[str], int],
    image_tokens: int = 0,
) -> int:
    """Estimate prepared input, retaining image costs without tokenizing image data."""
    counted_messages: list[dict[str, Any]] = []
    for message in messages:
        counted_message = {
            key: value for key, value in message.items() if key != "cache_control"
        }
        content = message.get("content")
        if isinstance(content, list):
            counted_message["content"] = [
                {
                    key: value
                    for key, value in part.items()
                    if key not in {"image_url", "cache_control"}
                }
                for part in content
            ]
        counted_messages.append(counted_message)
    payload = {"messages": counted_messages, "tools": tools or None}
    return image_tokens + token_counter(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
