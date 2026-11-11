"""Gemini behind an OpenAI-compatible provider parses tool parameters as its
OpenAPI Schema subset and rejects other JSON Schema keywords with a 400."""

import copy
from unittest.mock import patch

import pytest
from pydantic import JsonValue

from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_request import UserMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.multi_llm import LitellmLLM

# OpenCode's bash tool, as Zod v4 emits it for z.number().int().positive().
_BASH_PARAMETERS: dict[str, JsonValue] = {
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
}


def _tool(name: str, parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "type": "function",
        "function": {"name": name, "parameters": copy.deepcopy(parameters)},
    }


def _sent_parameters(
    model_provider: str,
    model_name: str,
    tool: dict[str, JsonValue],
    deployment_name: str | None = None,
) -> JsonValue:
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
            tools=[tool],
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.OFF,
            env_injection_enabled=False,
        )
    sent: list[dict[str, JsonValue]] = completion.call_args.kwargs["tools"]
    function = sent[0]["function"]
    assert isinstance(function, dict)
    return function["parameters"]


@pytest.mark.parametrize(
    ("model_name", "deployment_name"),
    [("gemini-3.8-flash", None), ("craft-default", "gemini-3.8-flash")],
)
def test_gemini_on_openai_compatible_drops_unsupported_schema_keywords(
    model_name: str, deployment_name: str | None
) -> None:
    tool = _tool("bash", _BASH_PARAMETERS)

    parameters = _sent_parameters(
        LlmProviderNames.OPENAI_COMPATIBLE, model_name, tool, deployment_name
    )

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
    assert tool == _tool("bash", _BASH_PARAMETERS)


def test_gemini_on_openai_compatible_inlines_defs() -> None:
    tool = _tool(
        "edit",
        {
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
    )

    parameters = _sent_parameters(
        LlmProviderNames.OPENAI_COMPATIBLE, "gemini-3.8-flash", tool
    )

    assert parameters == {
        "type": "object",
        "properties": {
            "range": {"type": "object", "properties": {"start": {"type": "integer"}}}
        },
    }


def test_gemini_on_openai_compatible_converts_nullable_any_of() -> None:
    tool = _tool(
        "read",
        {
            "type": "object",
            "properties": {"limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]}},
        },
    )

    parameters = _sent_parameters(
        LlmProviderNames.OPENAI_COMPATIBLE, "gemini-3.8-flash", tool
    )

    assert parameters == {
        "type": "object",
        "properties": {"limit": {"anyOf": [{"type": "integer", "nullable": True}]}},
    }


def test_gemini_on_openai_compatible_converts_type_arrays() -> None:
    tool = _tool(
        "grep",
        {
            "type": "object",
            "properties": {
                "path": {"type": ["string", "null"]},
                "value": {"type": ["string", "integer"]},
                "unset": {"type": ["null"]},
                "either": {
                    "type": ["string", "integer"],
                    "anyOf": [{"type": "string", "minLength": 1}],
                },
                "mode": {
                    "type": "string",
                    "enum": ["a", "b"],
                    "default": {"type": ["a", "b"]},
                },
                "default": {"type": ["string", "null"]},
            },
        },
    )

    parameters = _sent_parameters(
        LlmProviderNames.OPENAI_COMPATIBLE, "gemini-3.8-flash", tool
    )

    assert parameters == {
        "type": "object",
        "properties": {
            "path": {"type": "string", "nullable": True},
            "value": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
            "unset": {"type": "object", "nullable": True},
            "either": {"anyOf": [{"type": "string", "minLength": 1}]},
            "mode": {
                "type": "string",
                "enum": ["a", "b"],
                "default": {"type": ["a", "b"]},
            },
            "default": {"type": "string", "nullable": True},
        },
    }


def test_gemini_on_openai_compatible_forwards_unparseable_schema() -> None:
    boolean_subschema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"metadata": True},
    }

    parameters = _sent_parameters(
        LlmProviderNames.OPENAI_COMPATIBLE,
        "gemini-3.8-flash",
        _tool("write", boolean_subschema),
    )

    assert parameters == boolean_subschema


@pytest.mark.parametrize(
    ("model_provider", "model_name"),
    [
        (LlmProviderNames.OPENAI_COMPATIBLE, "qwen3-coder"),
        (LlmProviderNames.VERTEX_AI, "gemini-3.8-flash"),
    ],
)
def test_other_routes_keep_schema(model_provider: str, model_name: str) -> None:
    parameters = _sent_parameters(
        model_provider, model_name, _tool("bash", _BASH_PARAMETERS)
    )

    assert parameters == _BASH_PARAMETERS
