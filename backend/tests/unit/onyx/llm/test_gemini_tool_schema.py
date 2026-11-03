"""Gemini behind an OpenAI-compatible provider parses tool parameters as its
OpenAPI Schema subset and rejects other JSON Schema keywords with a 400."""

import copy
from typing import Any
from unittest.mock import patch

from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_request import UserMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.multi_llm import LitellmLLM

# OpenCode's bash tool, as Zod v4 emits it for z.number().int().positive().
_BASH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Executes a given bash command",
        "parameters": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {
                    "minimum": -9007199254740991,
                    "exclusiveMinimum": 0,
                    "type": "integer",
                    "maximum": 9007199254740991,
                    "description": "Optional timeout in milliseconds",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


def _sent_tools(
    model_provider: str, model_name: str, tools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    llm = LitellmLLM(
        api_key="test-key",
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=100000,
        api_base="https://gateway.example/v1",
    )
    with patch("onyx.llm.litellm_singleton.litellm.completion") as completion:
        llm._completion(
            prompt=[UserMessage(content="hi")],
            tools=tools,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.OFF,
        )
    return completion.call_args.kwargs["tools"]


def test_gemini_on_openai_compatible_drops_unsupported_schema_keywords() -> None:
    tools = [copy.deepcopy(_BASH_TOOL)]

    sent = _sent_tools(LlmProviderNames.OPENAI_COMPATIBLE, "gemini-3.8-flash", tools)

    parameters = sent[0]["function"]["parameters"]
    assert parameters == {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {
                "minimum": -9007199254740991,
                "type": "integer",
                "maximum": 9007199254740991,
                "description": "Optional timeout in milliseconds",
            },
        },
        "required": ["command"],
    }
    assert tools == [_BASH_TOOL]


def test_non_gemini_on_openai_compatible_keeps_schema() -> None:
    sent = _sent_tools(
        LlmProviderNames.OPENAI_COMPATIBLE, "qwen3-coder", [copy.deepcopy(_BASH_TOOL)]
    )

    assert sent == [_BASH_TOOL]
