"""Gemini behind an OpenAI-compatible provider parses tool parameters as its
OpenAPI Schema subset and rejects other JSON Schema keywords with a 400."""

import copy
from typing import Any
from unittest.mock import patch

import pytest

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
    model_provider: str,
    model_name: str,
    tools: list[dict[str, Any]],
    deployment_name: str | None = None,
) -> list[dict[str, Any]]:
    llm = LitellmLLM(
        api_key="test-key",
        model_provider=model_provider,
        model_name=model_name,
        deployment_name=deployment_name,
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
            env_injection_enabled=False,
        )
    return completion.call_args.kwargs["tools"]


@pytest.mark.parametrize(
    ("model_name", "deployment_name"),
    [("gemini-3.8-flash", None), ("craft-default", "gemini-3.8-flash")],
)
def test_gemini_on_openai_compatible_drops_unsupported_schema_keywords(
    model_name: str, deployment_name: str | None
) -> None:
    tools = [copy.deepcopy(_BASH_TOOL)]

    sent = _sent_tools(
        LlmProviderNames.OPENAI_COMPATIBLE, model_name, tools, deployment_name
    )

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


def test_gemini_on_openai_compatible_inlines_defs() -> None:
    tool: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "edit",
            "parameters": {
                "type": "object",
                "properties": {"range": {"$ref": "#/$defs/Range"}},
                "$defs": {
                    "Range": {
                        "type": "object",
                        "properties": {"start": {"type": "integer"}},
                        "additionalProperties": False,
                    }
                },
            },
        },
    }

    sent = _sent_tools(LlmProviderNames.OPENAI_COMPATIBLE, "gemini-3.8-flash", [tool])

    assert sent[0]["function"]["parameters"] == {
        "type": "object",
        "properties": {
            "range": {"type": "object", "properties": {"start": {"type": "integer"}}}
        },
    }


@pytest.mark.parametrize(
    ("model_provider", "model_name"),
    [
        (LlmProviderNames.OPENAI_COMPATIBLE, "qwen3-coder"),
        (LlmProviderNames.VERTEX_AI, "gemini-3.8-flash"),
    ],
)
def test_other_routes_keep_schema(model_provider: str, model_name: str) -> None:
    sent = _sent_tools(model_provider, model_name, [copy.deepcopy(_BASH_TOOL)])

    assert sent == [_BASH_TOOL]
