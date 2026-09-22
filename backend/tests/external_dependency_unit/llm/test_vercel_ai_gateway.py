"""Live behavior tests for Vercel AI Gateway through LiteLLM.

Two tiers:

- The catalog contract test needs no credentials, because the gateway's
  `/v1/models` listing is public. Onyx drives every model field from that
  listing rather than LiteLLM's static map, so a schema change upstream would
  silently degrade model fetching. It runs on every PR to catch that.
- The inference test spends money and is marked nightly, matching the other
  live LLM provider tests.
"""

import time

import httpx
import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import ChatCompletionMessage, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import VERCEL_AI_GATEWAY_DEFAULT_API_BASE
from tests.utils.secret_names import TestSecret

# Cheap, stable, and present in both the live catalog and LiteLLM's cost map.
_TEST_MODEL = "meta/llama-3.1-8b"


def _fetch_catalog() -> list[dict]:
    """The contract tests gate every PR, so a single transient network blip
    must not fail unrelated merges. Retry briefly, then let the error surface."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = httpx.get(
                f"{VERCEL_AI_GATEWAY_DEFAULT_API_BASE}/models", timeout=30.0
            )
            response.raise_for_status()
            return response.json()["data"]
        except (httpx.HTTPError, KeyError, ValueError) as err:
            last_error = err
            if attempt < 2:
                time.sleep(2**attempt)
    raise AssertionError(
        f"Vercel AI Gateway catalog unreachable after 3 attempts: {last_error}"
    )


def test_public_catalog_still_carries_the_fields_onyx_maps() -> None:
    """`get_vercel_ai_gateway_available_models` reads these fields by name."""
    models = _fetch_catalog()

    language_models = [m for m in models if m.get("type") == "language"]
    assert language_models, "catalog returned no language models"

    # `type` must still discriminate, or embedding models leak into the picker.
    assert {m.get("type") for m in models} - {"language"}, (
        "catalog no longer distinguishes non-language models"
    )

    by_id = {m["id"]: m for m in language_models}
    assert _TEST_MODEL in by_id, (
        f"{_TEST_MODEL} is gone from the catalog; the nightly inference test "
        f"pins that id and needs repointing"
    )

    sample = by_id[_TEST_MODEL]
    missing = [
        field
        for field, ok in (
            ("context_window", isinstance(sample.get("context_window"), int)),
            (
                "modalities.input",
                isinstance((sample.get("modalities") or {}).get("input"), list),
            ),
            (
                "supported_parameters",
                isinstance(sample.get("supported_parameters"), list),
            ),
        )
        if not ok
    ]
    assert not missing, f"{_TEST_MODEL} no longer carries: {', '.join(missing)}"


def test_namespaced_model_ids_are_still_vendor_prefixed() -> None:
    """Onyx hands LiteLLM `vercel_ai_gateway/<vendor>/<model>`. If the catalog
    stopped namespacing ids, that spelling would break."""
    unprefixed = [
        m["id"]
        for m in _fetch_catalog()
        if m.get("type") == "language" and "/" not in m["id"]
    ]
    assert not unprefixed, (
        f"catalog ids are no longer vendor-prefixed: {unprefixed[:5]}"
    )


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
