from __future__ import annotations

from unittest.mock import patch

from onyx.llm.interfaces import LLMConfig
from onyx.llm.model_request import ChatCompletionMessage, SystemMessage, UserMessage
from onyx.llm.prompt_cache import processor as processor_module
from onyx.llm.prompt_cache.processor import process_with_prompt_cache
from onyx.llm.prompt_cache.providers.anthropic import AnthropicPromptCacheProvider
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.providers.factory import get_provider_adapter
from onyx.llm.prompt_cache.providers.noop import NoOpPromptCacheProvider
from onyx.llm.prompt_cache.providers.openai import OpenAIPromptCacheProvider


def _config(
    provider: str,
    model_name: str,
    custom_config: dict[str, str] | None = None,
) -> LLMConfig:
    return LLMConfig(
        model_provider=provider,
        model_name=model_name,
        temperature=0,
        max_input_tokens=200_000,
        custom_config=custom_config,
    )


def test_gateway_anthropic_model_gets_anthropic_adapter() -> None:
    for provider in ("litellm_proxy", "bifrost", "openai_compatible", "portkey"):
        adapter: PromptCacheProvider = get_provider_adapter(
            _config(provider, "claude-sonnet-5")
        )
        assert isinstance(adapter, AnthropicPromptCacheProvider), provider


def test_gateway_prefixed_anthropic_model_gets_anthropic_adapter() -> None:
    adapter: PromptCacheProvider = get_provider_adapter(
        _config("bifrost", "anthropic/claude-sonnet-4-5")
    )
    assert isinstance(adapter, AnthropicPromptCacheProvider)


def test_portkey_messages_surface_gets_anthropic_adapter() -> None:
    adapter: PromptCacheProvider = get_provider_adapter(
        _config("portkey", "any-model", custom_config={"portkey_api_mode": "messages"})
    )
    assert isinstance(adapter, AnthropicPromptCacheProvider)


def test_gateway_non_anthropic_model_stays_noop() -> None:
    for provider in ("litellm_proxy", "bifrost", "openai_compatible", "portkey"):
        adapter: PromptCacheProvider = get_provider_adapter(
            _config(provider, "gpt-5-mini")
        )
        assert isinstance(adapter, NoOpPromptCacheProvider), provider


def test_gateway_unknown_model_stays_noop() -> None:
    adapter: PromptCacheProvider = get_provider_adapter(
        _config("litellm_proxy", "my-deployment")
    )
    assert isinstance(adapter, NoOpPromptCacheProvider)


def test_gateway_substring_lookalikes_stay_noop() -> None:
    for name in ("claudio-fast", "myanthropic-proxy", "declauded-v1"):
        adapter: PromptCacheProvider = get_provider_adapter(
            _config("litellm_proxy", name)
        )
        assert isinstance(adapter, NoOpPromptCacheProvider), name


def test_bedrock_cache_capable_models_get_anthropic_adapter() -> None:
    # LiteLLM translates cache_control into Converse cachePoint blocks, so the
    # Anthropic-style marker works for any cache-capable Bedrock model.
    for provider in ("bedrock", "bedrock_converse"):
        adapter: PromptCacheProvider = get_provider_adapter(
            _config(provider, "anthropic.claude-sonnet-4-5-20250929-v1:0")
        )
        assert isinstance(adapter, AnthropicPromptCacheProvider), provider

        # Cross-region inference profile names resolve too.
        adapter = get_provider_adapter(
            _config(provider, "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        )
        assert isinstance(adapter, AnthropicPromptCacheProvider), provider


def test_bedrock_nova_models_get_anthropic_adapter() -> None:
    for provider in ("bedrock", "bedrock_converse"):
        adapter: PromptCacheProvider = get_provider_adapter(
            _config(provider, "amazon.nova-pro-v1:0")
        )
        assert isinstance(adapter, AnthropicPromptCacheProvider), provider


def test_bedrock_non_cacheable_models_stay_noop() -> None:
    # Claude 3.5 Sonnet v1 predates prompt caching — a name-substring match
    # would mark it anyway and the Converse call would fail on cachePoint.
    for provider in ("bedrock", "bedrock_converse"):
        for name in (
            "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "meta.llama3-3-70b-instruct-v1:0",
        ):
            adapter: PromptCacheProvider = get_provider_adapter(_config(provider, name))
            assert isinstance(adapter, NoOpPromptCacheProvider), (provider, name)


def test_bedrock_unknown_model_stays_noop() -> None:
    adapter: PromptCacheProvider = get_provider_adapter(
        _config("bedrock", "some.custom-fine-tune")
    )
    assert isinstance(adapter, NoOpPromptCacheProvider)


def test_direct_providers_unchanged() -> None:
    assert isinstance(
        get_provider_adapter(_config("openai", "gpt-5-mini")),
        OpenAIPromptCacheProvider,
    )
    assert isinstance(
        get_provider_adapter(_config("anthropic", "claude-sonnet-5")),
        AnthropicPromptCacheProvider,
    )
    assert isinstance(
        get_provider_adapter(_config("openrouter", "anthropic/claude-sonnet-5")),
        AnthropicPromptCacheProvider,
    )
    assert isinstance(
        get_provider_adapter(_config("openrouter", "openai/gpt-5-mini")),
        OpenAIPromptCacheProvider,
    )
    assert isinstance(
        get_provider_adapter(_config("ollama", "llama3")),
        NoOpPromptCacheProvider,
    )


def test_anthropic_marks_head_and_tail_breakpoints() -> None:
    prefix: list[ChatCompletionMessage] = [
        SystemMessage(content="system prompt"),
        UserMessage(content="earlier turn"),
        UserMessage(content="latest cached turn"),
    ]
    suffix: list[ChatCompletionMessage] = [UserMessage(content="new request")]

    with patch.object(processor_module, "ENABLE_PROMPT_CACHING", True):
        processed, _ = process_with_prompt_cache(
            llm_config=_config("anthropic", "claude-sonnet-5"),
            cacheable_prefix=prefix,
            suffix=suffix,
            continuation=False,
            with_metadata=False,
        )

    assert processed[0].cache_control == {"type": "ephemeral"}
    assert processed[1].cache_control is None
    assert processed[2].cache_control == {"type": "ephemeral"}
    assert processed[3].cache_control is None


def test_anthropic_single_message_prefix_marks_one_breakpoint() -> None:
    prefix: list[ChatCompletionMessage] = [SystemMessage(content="system prompt")]
    suffix: list[ChatCompletionMessage] = [UserMessage(content="new request")]

    with patch.object(processor_module, "ENABLE_PROMPT_CACHING", True):
        processed, _ = process_with_prompt_cache(
            llm_config=_config("anthropic", "claude-sonnet-5"),
            cacheable_prefix=prefix,
            suffix=suffix,
            continuation=False,
            with_metadata=False,
        )

    assert processed[0].cache_control == {"type": "ephemeral"}
    assert processed[1].cache_control is None
