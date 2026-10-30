"""Unit tests for Inworld Router routing in LitellmLLM.

Inworld Router speaks OpenAI chat completions, so it routes through the
OpenAI-compatible surface with a bare `provider/model` id. Its API keys are
Base64 `key:secret` credentials that the router reads from a Basic
Authorization header, which must replace the SDK's default Bearer header.
"""

from unittest.mock import patch

from onyx.llm.api_surfaces import LlmApiSurface, resolve_api_surface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.multi_llm import LitellmLLM


def _make_llm(
    api_key: str | None = "aW53b3JsZDpzZWNyZXQ=",
    api_base: str | None = "https://api.inworld.ai/v1",
    model_name: str = "openai/gpt-5.4",
    extra_headers: dict[str, str] | None = None,
) -> LitellmLLM:
    return LitellmLLM(
        api_key=api_key,
        model_provider=LlmProviderNames.INWORLD,
        model_name=model_name,
        max_input_tokens=128_000,
        api_base=api_base,
        extra_headers=extra_headers,
    )


def _completion_kwargs(llm: LitellmLLM) -> dict:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: list[ChatCompletionMessage] = [UserMessage(content="Hi")]
        list(llm.stream_raw(messages))
        return dict(mock_completion.call_args.kwargs)


def test_routes_through_openai_chat_completions_surface() -> None:
    assert (
        resolve_api_surface(LlmProviderNames.INWORLD, None)
        is LlmApiSurface.OPENAI_CHAT_COMPLETIONS
    )

    kwargs = _completion_kwargs(_make_llm())
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == "https://api.inworld.ai/v1"
    # The router parses `provider/model` itself; no LiteLLM prefix is added.
    assert kwargs["model"] == "openai/gpt-5.4"


def test_bare_base_is_coerced_to_v1() -> None:
    llm = _make_llm(api_base="https://api.inworld.ai/")
    assert llm._api_base == "https://api.inworld.ai/v1"


def test_auto_router_model_is_sent_as_is() -> None:
    kwargs = _completion_kwargs(_make_llm(model_name="auto"))
    assert kwargs["model"] == "auto"


def test_api_key_is_sent_as_basic_authorization() -> None:
    kwargs = _completion_kwargs(_make_llm())
    assert kwargs["extra_headers"]["Authorization"] == "Basic aW53b3JsZDpzZWNyZXQ="


def test_basic_prefix_in_stored_key_is_not_doubled() -> None:
    kwargs = _completion_kwargs(_make_llm(api_key="Basic aW53b3JsZDpzZWNyZXQ="))
    assert kwargs["extra_headers"]["Authorization"] == "Basic aW53b3JsZDpzZWNyZXQ="


def test_basic_authorization_keeps_other_extra_headers() -> None:
    kwargs = _completion_kwargs(_make_llm(extra_headers={"x-client-request-id": "r1"}))
    assert kwargs["extra_headers"]["x-client-request-id"] == "r1"
    assert kwargs["extra_headers"]["Authorization"] == "Basic aW53b3JsZDpzZWNyZXQ="


def test_no_authorization_header_without_api_key() -> None:
    kwargs = _completion_kwargs(_make_llm(api_key=None))
    assert "Authorization" not in (kwargs.get("extra_headers") or {})


def test_other_openai_compatible_providers_keep_bearer_auth() -> None:
    llm = LitellmLLM(
        api_key="sk-test",
        model_provider=LlmProviderNames.OPENAI_COMPATIBLE,
        model_name="gpt-4o",
        max_input_tokens=128_000,
        api_base="http://localhost:8000/v1",
    )
    kwargs = _completion_kwargs(llm)
    assert "Authorization" not in (kwargs.get("extra_headers") or {})
