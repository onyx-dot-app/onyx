"""Utility functions for prompt caching."""

from collections.abc import Sequence
from typing import Any

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import UserMessageWithText


def normalize_language_model_input(
    input: LanguageModelInput,
) -> Sequence[ChatCompletionMessage]:
    """Normalize LanguageModelInput to Sequence[ChatCompletionMessage]."""
    if isinstance(input, str):
        # Convert string to user message
        return [UserMessageWithText(role="user", content=input)]
    else:
        return input


def normalize_content(
    content: str | list[str | dict[str, Any]] | Any,
) -> list[str | dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    elif isinstance(content, list):
        return content
    else:
        raise ValueError(f"Unsupported content type: {type(content)}")
