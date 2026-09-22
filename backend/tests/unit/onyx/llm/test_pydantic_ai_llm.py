"""Provider routing, scoped settings, streaming and deadline regressions."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from unittest.mock import patch

import pytest
from pydantic_ai import messages as pm
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModelSettings
from pydantic_ai.models.test import TestModel

from onyx.llm.exceptions import LLMTimeoutError
from onyx.llm.models import NamedToolChoice, ReasoningEffort, UserMessage
from onyx.llm.pydantic_ai_llm import PydanticAILLM
from onyx.llm.request_context import get_llm_request_params


def make_llm(
    provider: str = "openai", name: str = "gpt-5-mini", **kwargs: Any
) -> PydanticAILLM:
    return PydanticAILLM(
        api_key="tenant-key",
        model_provider=provider,
        model_name=name,
        max_input_tokens=100000,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("provider", "name", "kwargs", "model_type", "base"),
    [
        (
            "openai",
            "gpt-5-mini",
            {},
            "OpenAIResponsesModel",
            "https://api.openai.com/v1/",
        ),
        (
            "anthropic",
            "claude-haiku-4-5",
            {},
            "AnthropicModel",
            "https://api.anthropic.com",
        ),
        (
            "openai_compatible",
            "local-model",
            {"api_base": "http://localhost:1234"},
            "OpenAIChatModel",
            "http://localhost:1234/v1/",
        ),
        ("ollama_chat", "qwen3", {}, "OllamaNativeModel", "http://localhost:11434"),
        (
            "lm_studio",
            "local-model",
            {},
            "OpenAIChatModel",
            "http://localhost:1234/v1/",
        ),
        (
            "bifrost",
            "openai/gpt-5-mini",
            {
                "api_base": "https://gateway.example",
                "custom_config": {"bifrost_api_mode": "responses"},
            },
            "OpenAIResponsesModel",
            "https://gateway.example/v1/",
        ),
        (
            "portkey",
            "claude-haiku-4-5",
            {
                "api_base": "https://gateway.example",
                "custom_config": {"portkey_api_mode": "messages"},
            },
            "AnthropicModel",
            "https://gateway.example",
        ),
        (
            "azure",
            "gpt-5-mini",
            {
                "api_base": "https://azure.example",
                "api_version": "2024-10-21",
                "deployment_name": "my-deployment",
            },
            "OpenAIResponsesModel",
            "https://azure.example/openai/v1/",
        ),
    ],
)
def test_native_provider_routing(
    provider: str, name: str, kwargs: dict[str, Any], model_type: str, base: str
) -> None:
    model = make_llm(provider, name, **kwargs)._build_model()
    assert type(model).__name__ == model_type
    assert model.base_url == base


@pytest.mark.parametrize(
    ("requested", "default", "maximum", "expected"),
    [
        (ReasoningEffort.XHIGH, None, ReasoningEffort.LOW, "low"),
        (ReasoningEffort.AUTO, ReasoningEffort.HIGH, None, "high"),
        (ReasoningEffort.OFF, ReasoningEffort.HIGH, None, False),
        (ReasoningEffort.AUTO, None, None, "medium"),
    ],
)
def test_reasoning_defaults_and_caps(
    requested: ReasoningEffort,
    default: ReasoningEffort | None,
    maximum: ReasoningEffort | None,
    expected: str | bool,
) -> None:
    llm = make_llm(reasoning_effort_default=default, reasoning_effort_max=maximum)
    assert llm.model_settings(requested)["thinking"] == expected


def test_named_tool_choice_and_native_schema() -> None:
    llm = make_llm()
    assert llm.model_settings(tool_choice=NamedToolChoice(name="search"))[
        "tool_choice"
    ] == ["search"]
    parameters = llm._request_parameters(
        [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                },
            }
        ],
        {
            "type": "json_schema",
            "json_schema": {
                "name": "answer",
                "schema": {"type": "object", "properties": {}},
            },
        },
    )
    assert parameters.output_mode == "native"
    assert parameters.output_object and parameters.output_object.name == "answer"
    assert parameters.function_tools[0].name == "search"


def test_policy_values_and_input_dicts_are_preserved() -> None:
    kwargs = {"store": False, "extra_headers": {"retention": "none"}}
    llm = make_llm(
        model_kwargs=kwargs, extra_headers={"retention": "default", "other": "yes"}
    )
    settings = llm.model_settings()
    assert cast(OpenAIResponsesModelSettings, settings)["openai_store"] is False
    assert settings["extra_headers"] == {"retention": "none", "other": "yes"}
    settings["extra_headers"]["other"] = "changed"
    assert llm.model_settings()["extra_headers"]["other"] == "yes"
    assert kwargs == {"store": False, "extra_headers": {"retention": "none"}}


def test_tenant_credentials_do_not_mutate_environment() -> None:
    before = dict(os.environ)

    def create(key: str) -> str:
        llm = PydanticAILLM(
            api_key=key,
            model_provider="openai",
            model_name="gpt-5-mini",
            max_input_tokens=10000,
        )
        model = llm._build_model()
        assert model.provider is not None
        return model.provider.client.api_key

    with ThreadPoolExecutor(max_workers=8) as executor:
        keys = [f"tenant-{i}" for i in range(32)]
        assert list(executor.map(create, keys)) == keys
    assert dict(os.environ) == before


def test_invoke_and_stream_return_text_and_usage() -> None:
    llm = make_llm()
    llm.model = TestModel(custom_output_text="hello", call_tools=[])
    with patch.object(llm, "_track_llm_cost") as track:
        result = llm.invoke(UserMessage(content="hi"))
        chunks = list(llm.stream(UserMessage(content="hi")))
    assert result.choice.message.content == "hello"
    assert result.usage and result.usage.total_tokens > 0
    assert "".join(chunk.choice.delta.content or "" for chunk in chunks) == "hello"
    assert chunks[-1].usage and chunks[-1].usage.total_tokens > 0
    assert track.call_count == 2


def test_stream_closes_provider_on_early_exit() -> None:
    closed = False

    async def streaming(_messages: list[pm.ModelMessage], _info: AgentInfo):
        nonlocal closed
        try:
            yield "first"
            await asyncio.sleep(100)
        finally:
            closed = True

    llm = make_llm()
    llm.model = FunctionModel(stream_function=streaming)
    stream = llm.stream(UserMessage(content="hi"))
    next(stream)
    stream.close()
    assert closed


def test_total_deadline_cancels_inference() -> None:
    closed = False

    async def completion(
        _messages: list[pm.ModelMessage], _info: AgentInfo
    ) -> pm.ModelResponse:
        nonlocal closed
        try:
            await asyncio.sleep(100)
            return pm.ModelResponse(parts=[pm.TextPart("late")])
        finally:
            closed = True

    llm = make_llm()
    llm.model = FunctionModel(completion)
    with pytest.raises(LLMTimeoutError):
        llm.invoke(UserMessage(content="hi"), total_timeout_override=0.01)
    assert closed


def test_request_attribution_uses_effective_settings() -> None:
    from onyx.llm.provider_model import ProviderModel

    llm = make_llm(reasoning_effort_max=ReasoningEffort.LOW)
    llm.model = ProviderModel(
        TestModel(custom_output_text="hello", call_tools=[]), llm.config
    )
    with patch.object(llm, "_track_llm_cost"):
        llm.invoke(UserMessage(content="hi"), reasoning_effort=ReasoningEffort.XHIGH)
    params = get_llm_request_params()
    assert params is not None
    assert params["reasoning_effort"] == "low"


def test_each_agent_run_gets_an_independent_provider_client() -> None:
    llm = make_llm()
    first = llm.model
    second = llm.model
    assert first is not second
    assert first.provider is not second.provider


@pytest.mark.asyncio
async def test_model_context_closes_injected_sdk_client() -> None:
    llm = make_llm("openrouter", "openai/gpt-5-mini")
    model = llm.model
    assert model.provider is not None
    client = model.provider.client
    async with model:
        assert not client.is_closed()
    assert client.is_closed()


def test_recursive_policy_body_merge_preserves_deployment_siblings() -> None:
    llm = make_llm(
        extra_body={"routing": {"region": "us", "log": True}},
        model_kwargs={"extra_body": {"routing": {"log": False}}, "store": False},
    )
    settings = llm.model_settings()
    assert settings["extra_body"] == {"routing": {"region": "us", "log": False}}


def test_privacy_store_override_wins_over_extra_body() -> None:
    llm = make_llm(extra_body={"store": True}, model_kwargs={"store": False})
    settings = llm.model_settings()
    assert "extra_body" not in settings
    assert cast(OpenAIResponsesModelSettings, settings)["openai_store"] is False


def test_legacy_anthropic_budget_fits_output_limit() -> None:
    llm = make_llm("anthropic", "claude-haiku-4-5")
    settings = cast(dict[str, Any], llm.model_settings(ReasoningEffort.HIGH))
    assert settings["anthropic_thinking"] == {"type": "enabled", "budget_tokens": 4096}
    assert settings["max_tokens"] > 4096
    short = llm.model_settings(ReasoningEffort.HIGH, max_tokens=1000)
    assert short["thinking"] is False
    assert "anthropic_thinking" not in short


def test_forced_legacy_anthropic_tool_preserves_named_choice() -> None:
    llm = make_llm("anthropic", "claude-haiku-4-5")
    settings = llm.model_settings(
        ReasoningEffort.HIGH, tool_choice=NamedToolChoice(name="search")
    )
    assert settings["tool_choice"] == ["search"]
    assert settings["thinking"] is False


def test_reasoning_summary_only_for_reasoning_models() -> None:
    assert "openai_reasoning_summary" in make_llm().model_settings()
    assert "openai_reasoning_summary" not in make_llm(name="gpt-4o").model_settings()


@pytest.mark.parametrize("send_metadata", [True, False])
def test_openrouter_session_routing_respects_metadata_policy(
    send_metadata: bool,
) -> None:
    from onyx.llm.interfaces import LLMUserIdentity

    llm = make_llm("openrouter", "anthropic/claude-sonnet-4")
    with patch(
        "onyx.llm.pydantic_ai_llm.SEND_USER_METADATA_TO_LLM_PROVIDER", send_metadata
    ):
        settings = llm.model_settings(
            user_identity=LLMUserIdentity(user_id="user-1", session_id="chat-1")
        )
    body = cast(dict[str, Any], settings.get("extra_body", {}))
    assert body.get("session_id") == ("chat-1" if send_metadata else None)
    assert body.get("user") == ("user-1" if send_metadata else None)


@pytest.mark.asyncio
async def test_bedrock_request_override_scopes_and_closes_sdk_client() -> None:
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.bedrock import BedrockConverseModel

    llm = make_llm(
        "bedrock",
        "anthropic.claude-sonnet-4-20250514-v1:0",
        custom_config={"aws_region_name": "us-east-1"},
    )
    model = llm.model
    closed: list[float] = []

    async def respond(
        native: BedrockConverseModel,
        messages: list[pm.ModelMessage],
        settings: Any,
        parameters: ModelRequestParameters,
    ) -> pm.ModelResponse:
        del messages, settings, parameters
        assert native.client.meta.config.read_timeout == 901
        native.client.close = lambda: closed.append(
            native.client.meta.config.read_timeout
        )
        return pm.ModelResponse(parts=[pm.TextPart("report")])

    with patch.object(BedrockConverseModel, "request", respond):
        async with model:
            response = await model.request(
                [], llm.model_settings(timeout_override=901), ModelRequestParameters()
            )
    assert response.parts == [pm.TextPart("report")]
    assert closed == [901]


def test_openrouter_claude_thinking_does_not_force_unsupported_tool_choice() -> None:
    from onyx.llm.models import ToolChoiceOptions

    llm = make_llm("openrouter", "anthropic/claude-sonnet-4-6")
    settings = llm.model_settings(
        reasoning_effort=ReasoningEffort.HIGH, tool_choice=ToolChoiceOptions.REQUIRED
    )
    assert settings["tool_choice"] == "auto"
    assert settings["thinking"] == "high"
    named = llm.model_settings(
        reasoning_effort=ReasoningEffort.HIGH,
        tool_choice=NamedToolChoice(name="search"),
    )
    assert named["thinking"] is False
    assert named["tool_choice"] == ["search"]


@pytest.mark.parametrize("provider", ["groq", "bedrock", "httpx2"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_native_provider_timeouts_are_normalized(provider: str, wrapped: bool) -> None:
    import groq
    import httpx
    import httpx2
    from botocore.exceptions import ReadTimeoutError
    from pydantic_ai.exceptions import ModelAPIError

    from onyx.llm.provider_model import translate_provider_errors

    error: Exception
    if provider == "groq":
        error = groq.APITimeoutError(
            request=httpx.Request("POST", "https://example.com")
        )
    elif provider == "bedrock":
        error = ReadTimeoutError(endpoint_url="https://example.com")
    else:
        error = httpx2.ReadTimeout("Provider request timed out")
    with pytest.raises(LLMTimeoutError), translate_provider_errors():
        if wrapped:
            raise ModelAPIError("test-model", "Provider request failed") from error
        raise error


def test_claude_thinking_omits_incompatible_temperature() -> None:
    llm = make_llm("anthropic", "claude-haiku-4-5", temperature=0.2)
    assert "temperature" not in llm.model_settings(reasoning_effort=ReasoningEffort.LOW)
    assert (
        llm.model_settings(reasoning_effort=ReasoningEffort.OFF)["temperature"] == 0.2
    )


@pytest.mark.parametrize("provider", ["anthropic", "bedrock"])
def test_native_cache_defaults_respect_caching_disabled(provider: str) -> None:
    llm = make_llm(provider, "claude-haiku-4-5")
    with patch("onyx.llm.pydantic_ai_llm.ENABLE_PROMPT_CACHING", False):
        assert not any("cache" in key for key in llm.model_settings())
    with patch("onyx.llm.pydantic_ai_llm.ENABLE_PROMPT_CACHING", True):
        assert llm.model_settings().get(f"{provider}_cache_instructions") is True


def test_bedrock_cache_defaults_do_not_insert_cache_points_in_tool_results() -> None:
    llm = make_llm("bedrock", "amazon.nova-pro-v1:0")
    settings = llm.model_settings()
    assert not settings.get("bedrock_cache_messages")
    assert settings.get("bedrock_cache_instructions") is True
