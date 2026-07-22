"""Live guard for the Azure Responses API surface routing (#11420).

`LitellmLLM` routes true OpenAI models on Azure through LiteLLM's responses
bridge. The bridge must target the modern `/openai/v1/responses` surface even
when the provider is configured with a dated api-version: dated versions make
LiteLLM build the legacy `/openai/responses?api-version=<dated>` URL, which
sovereign clouds (e.g. Azure Government) do not serve.

Commercial Azure serves BOTH surfaces successfully, so a plain success
assertion cannot catch a regression to the legacy surface — these tests
intercept the actual request URL. The URL construction happens inside
LiteLLM, so this is also the guard that a LiteLLM version bump doesn't
silently change the surface.
"""

from typing import Any
from urllib.parse import urlparse

import pytest
from litellm.llms.custom_httpx.http_handler import HTTPHandler

from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import LanguageModelInput, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.nightly

# Deployment that exists on the shared Azure test resource (the same resource
# AZURE_API_URL points at; see tests/daily/embedding for its embedding use).
_CHAT_DEPLOYMENT = "gpt-4o"

# A dated api-version, as admins configure for Azure chat completions. Before
# the v1-surface fix this routed responses-bridge calls to the legacy surface.
_DATED_API_VERSION = "2025-03-01-preview"


def _resource_base(azure_api_url: str) -> str:
    """AZURE_API_URL is a full deployment target URI; extract the resource base."""
    parsed = urlparse(azure_api_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_azure_llm(test_secrets: dict[TestSecret, str]) -> LitellmLLM:
    return LitellmLLM(
        api_key=test_secrets[TestSecret.AZURE_API_KEY],
        model_provider=LlmProviderNames.AZURE,
        model_name=_CHAT_DEPLOYMENT,
        deployment_name=_CHAT_DEPLOYMENT,
        api_base=_resource_base(test_secrets[TestSecret.AZURE_API_URL]),
        api_version=_DATED_API_VERSION,
        max_input_tokens=128_000,
        timeout=60,
    )


def _record_posted_urls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []
    original_post = HTTPHandler.post

    def recording_post(self: HTTPHandler, url: str, *args: Any, **kwargs: Any) -> Any:
        urls.append(str(url))
        return original_post(self, url, *args, **kwargs)

    monkeypatch.setattr(HTTPHandler, "post", recording_post)
    return urls


def _assert_v1_surface(urls: list[str], api_base: str) -> None:
    azure_urls = [url for url in urls if api_base in url]
    assert azure_urls, f"no request reached the Azure resource; saw: {urls}"
    for url in azure_urls:
        assert "/openai/v1/responses" in url, f"legacy responses surface used: {url}"
        assert "api-version=preview" in url, f"unexpected api-version: {url}"


@pytest.mark.secrets(TestSecret.AZURE_API_KEY, TestSecret.AZURE_API_URL)
def test_azure_responses_bridge_targets_v1_surface(
    test_secrets: dict[TestSecret, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = _record_posted_urls(monkeypatch)
    llm = _build_azure_llm(test_secrets)

    messages: LanguageModelInput = [UserMessage(content="Say hello in three words")]
    response = llm.invoke(messages, max_tokens=32)

    assert response.choice.message.content
    _assert_v1_surface(urls, _resource_base(test_secrets[TestSecret.AZURE_API_URL]))


@pytest.mark.secrets(TestSecret.AZURE_API_KEY, TestSecret.AZURE_API_URL)
def test_azure_responses_bridge_streams_on_v1_surface(
    test_secrets: dict[TestSecret, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = _record_posted_urls(monkeypatch)
    llm = _build_azure_llm(test_secrets)

    messages: LanguageModelInput = [UserMessage(content="Say hello in three words")]
    content = "".join(
        chunk.choice.delta.content or ""
        for chunk in llm.stream(messages, max_tokens=32)
    )

    assert content
    _assert_v1_surface(urls, _resource_base(test_secrets[TestSecret.AZURE_API_URL]))
