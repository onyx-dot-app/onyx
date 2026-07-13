"""Unit tests for Portkey's three API-mode routing in LitellmLLM.

Portkey is a single provider that can target three API surfaces, selected via a
`portkey_api_mode` value persisted in custom_config. The routing differences are
entirely: custom_llm_provider, the model= string, and whether the base is coerced
to end in /v1. These tests lock that mapping down.
"""

from unittest.mock import patch

from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import PORTKEY_API_MODE_CONFIG_KEY


def _make_portkey_llm(
    mode: str | None,
    api_base: str,
    model_name: str = "gpt-4o",
) -> LitellmLLM:
    custom_config = {PORTKEY_API_MODE_CONFIG_KEY: mode} if mode is not None else None
    return LitellmLLM(
        api_key="pk-test-key",
        timeout=30,
        model_provider=LlmProviderNames.PORTKEY,
        model_name=model_name,
        max_input_tokens=128_000,
        api_base=api_base,
        custom_config=custom_config,
    )


def _completion_kwargs(llm: LitellmLLM) -> dict:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))
        return dict(mock_completion.call_args.kwargs)


def test_chat_completions_mode_routes_via_openai_with_v1_base() -> None:
    llm = _make_portkey_llm("chat_completions", "https://api.portkey.ai/v1")
    assert llm._custom_llm_provider == "openai"
    assert llm._api_base == "https://api.portkey.ai/v1"

    kwargs = _completion_kwargs(llm)
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == "https://api.portkey.ai/v1"
    # OpenAI-compatible proxies send a bare model name.
    assert kwargs["model"] == "gpt-4o"


def test_chat_completions_mode_coerces_bare_base_to_v1() -> None:
    llm = _make_portkey_llm("chat_completions", "https://api.portkey.ai")
    assert llm._api_base == "https://api.portkey.ai/v1"


def test_default_mode_is_chat_completions() -> None:
    # No portkey_api_mode in custom_config -> defaults to chat completions.
    llm = _make_portkey_llm(None, "https://api.portkey.ai/v1")
    assert llm._portkey_api_mode == "chat_completions"
    assert llm._custom_llm_provider == "openai"


def test_responses_mode_prefixes_model_and_keeps_v1_base() -> None:
    llm = _make_portkey_llm("responses", "https://api.portkey.ai/v1")
    assert llm._custom_llm_provider == "openai"
    assert llm._api_base == "https://api.portkey.ai/v1"

    kwargs = _completion_kwargs(llm)
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == "https://api.portkey.ai/v1"
    # Responses mode drives litellm's completions->responses bridge via the prefix.
    assert kwargs["model"] == "responses/gpt-4o"


def test_messages_mode_routes_via_anthropic_with_bare_base() -> None:
    llm = _make_portkey_llm(
        "messages", "https://api.portkey.ai", model_name="claude-sonnet-5"
    )
    assert llm._custom_llm_provider == "anthropic"
    # Messages mode must NOT be coerced to /v1 — litellm appends /v1/messages.
    assert llm._api_base == "https://api.portkey.ai"

    kwargs = _completion_kwargs(llm)
    assert kwargs["custom_llm_provider"] == "anthropic"
    assert kwargs["base_url"] == "https://api.portkey.ai"
    # Anthropic path uses a bare model name (no responses/ or provider prefix).
    assert kwargs["model"] == "claude-sonnet-5"


def test_messages_mode_strips_trailing_slash_but_keeps_bare_host() -> None:
    llm = _make_portkey_llm(
        "messages", "https://api.portkey.ai/", model_name="claude-sonnet-5"
    )
    assert llm._api_base == "https://api.portkey.ai"


def test_api_mode_is_popped_from_custom_config() -> None:
    # The mode must not leak into os.environ via temporary_env_and_lock, so it is
    # stripped from _custom_config after being read.
    llm = _make_portkey_llm("messages", "https://api.portkey.ai")
    assert llm._custom_config is not None
    assert PORTKEY_API_MODE_CONFIG_KEY not in llm._custom_config
    assert llm._portkey_api_mode == "messages"
