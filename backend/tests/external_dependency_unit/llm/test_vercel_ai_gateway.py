"""Live behavior tests for Vercel AI Gateway through LiteLLM.

Two tiers:

- The catalog contract test needs no credentials, because the gateway's
  `/v1/models` listing is public. Onyx drives every model field from that
  listing rather than LiteLLM's static map, so a schema change upstream would
  silently degrade model fetching. It runs on every PR to catch that.
- The inference test spends money and is marked nightly, matching the other
  live LLM provider tests.
"""

import httpx
import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import ChatCompletionMessage, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import VERCEL_AI_GATEWAY_DEFAULT_API_BASE
from tests.utils.secret_names import TestSecret

# Cheap, stable, and present in both the live catalog and LiteLLM's cost map.
_TEST_MODEL = "meta/llama-3.1-8b"


def test_public_catalog_still_carries_the_fields_onyx_maps() -> None:
    """`get_vercel_ai_gateway_available_models` reads these fields by name."""
    response = httpx.get(f"{VERCEL_AI_GATEWAY_DEFAULT_API_BASE}/models", timeout=30.0)
    response.raise_for_status()
    models = response.json()["data"]

    language_models = [m for m in models if m.get("type") == "language"]
    assert language_models, "catalog returned no language models"

    # `type` must still discriminate, or embedding models leak into the picker.
    assert {m.get("type") for m in models} - {"language"}, (
        "catalog no longer distinguishes non-language models"
    )

    sample = next(m for m in language_models if m["id"] == _TEST_MODEL)
    assert isinstance(sample["context_window"], int)
    assert isinstance(sample["modalities"]["input"], list)
    assert isinstance(sample["supported_parameters"], list)


def test_namespaced_model_ids_are_still_vendor_prefixed() -> None:
    """Onyx hands LiteLLM `vercel_ai_gateway/<vendor>/<model>`. If the catalog
    stopped namespacing ids, that spelling would break."""
    response = httpx.get(f"{VERCEL_AI_GATEWAY_DEFAULT_API_BASE}/models", timeout=30.0)
    response.raise_for_status()
    language_models = [
        m for m in response.json()["data"] if m.get("type") == "language"
    ]
    assert all("/" in m["id"] for m in language_models)


@pytest.mark.nightly
@pytest.mark.secrets(TestSecret.VERCEL_AI_GATEWAY_API_KEY)
def test_streaming_completion_through_the_gateway(
    test_secrets: dict[TestSecret, str],
) -> None:
    """The doubly-namespaced model string must survive to a real response.

    LiteLLM's own convention is `provider/model` and the gateway's is
    `vendor/model`, so this sends `vercel_ai_gateway/meta/llama-3.1-8b`.
    """
    llm = LitellmLLM(
        api_key=test_secrets[TestSecret.VERCEL_AI_GATEWAY_API_KEY],
        model_provider=LlmProviderNames.VERCEL_AI_GATEWAY,
        model_name=_TEST_MODEL,
        max_input_tokens=128_000,
        timeout=60,
    )

    prompt: list[ChatCompletionMessage] = [
        UserMessage(role="user", content="Reply with exactly the word: pong")
    ]

    content = "".join(
        chunk.choice.delta.content or "" for chunk in llm.stream(prompt=prompt)
    )
    assert "pong" in content.lower()
