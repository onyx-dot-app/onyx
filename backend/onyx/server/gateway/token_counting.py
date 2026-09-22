"""Local token estimates for gateway protocols without a count endpoint."""

import json
from typing import Any


def count_gateway_tokens(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int:
    import tiktoken

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    image_tokens = 0

    def text_payload(value: Any) -> Any:
        nonlocal image_tokens
        if isinstance(value, list):
            return [text_payload(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value.get("type") in {"image", "image_url", "input_image"}:
            image = value.get("image_url", {})
            detail = image.get("detail") if isinstance(image, dict) else None
            detail = value.get("detail", detail)
            # Local estimates exclude encoded bytes and assume four high-detail tiles.
            image_tokens += 85 if detail == "low" else 765
            return {"type": "image"}
        return {key: text_payload(item) for key, item in value.items()}

    payload: dict[str, Any] = {"messages": text_payload(messages)}
    if tools:
        payload["tools"] = tools
    return image_tokens + len(
        encoding.encode(json.dumps(payload), disallowed_special=())
    )
