"""Sentinel assertions over the vendored model catalog.

These pin the fields and coverage the runtime depends on. They run on every
PR — including the weekly sync PR — so an upstream schema change or a source
dropping data turns the sync red before it merges rather than degrading
pricing/capability answers silently.
"""

from pathlib import Path

import pytest

from onyx.llm import model_catalog
from onyx.llm.constants import LlmProviderNames
from onyx.llm.well_known_providers.llm_provider_options import (
    get_anthropic_model_names,
    get_openai_model_names,
    get_vertexai_model_names,
)

_PRICE_TABLE_DIR = Path(model_catalog.__file__).parent / "price_table"

# Providers whose absence would break core product surfaces.
_REQUIRED_PROVIDERS = {
    LlmProviderNames.OPENAI,
    LlmProviderNames.ANTHROPIC,
    LlmProviderNames.VERTEX_AI,
    LlmProviderNames.BEDROCK,
    LlmProviderNames.OPENROUTER,
    LlmProviderNames.AZURE,
}


def test_required_providers_present() -> None:
    missing = _REQUIRED_PROVIDERS - set(model_catalog.provider_names())
    assert not missing, f"catalog is missing provider sections: {missing}"


def test_every_catalog_file_is_a_known_provider() -> None:
    """A file the provider map doesn't know about would load but never be
    reachable — catch orphan sections from a stale PROVIDER_MAP."""
    files = {
        p.stem for p in _PRICE_TABLE_DIR.glob("*.json") if not p.stem.startswith("_")
    }
    assert files <= set(model_catalog.provider_names()), (
        f"catalog files with no provider entry: {files - set(model_catalog.provider_names())}"
    )


def test_chat_pricing_sentinel() -> None:
    """The flagship Anthropic model must carry full token pricing — input,
    output, and both cache buckets. If upstream drops a field this fails."""
    cost = model_catalog.find_model_cost(
        LlmProviderNames.ANTHROPIC, "claude-sonnet-4-5"
    )
    assert cost is not None
    assert cost["input"] == pytest.approx(3.0)
    assert cost["output"] == pytest.approx(15.0)
    assert cost.get("cache_read") is not None
    assert cost.get("cache_write") is not None


def test_litellm_merge_sentinels() -> None:
    """Fields only the litellm merge supplies — if the merge's schema guard
    regresses or litellm drops them, these catch it."""
    sonnet = model_catalog.find_model_entry(
        LlmProviderNames.ANTHROPIC, "claude-sonnet-4-5"
    )
    assert sonnet is not None
    assert sonnet.get("mode") == "chat"
    # Anthropic's 1h cache-write premium — litellm is the only public source.
    assert sonnet["cost"].get("cache_write_above_1hr") is not None

    # Per-image pricing only exists via litellm's per-unit cost fields.
    dalle = model_catalog.find_model_cost(LlmProviderNames.OPENAI, "dall-e-3")
    assert dalle is not None
    assert dalle.get("image") or dalle.get("image_input")


def test_alias_resolution_sentinels() -> None:
    """Provider-specific id formats must keep resolving."""
    bedrock = model_catalog.find_model_entry(
        LlmProviderNames.BEDROCK, "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    assert bedrock is not None, "bedrock region-prefix alias stopped resolving"
    assert bedrock.get("cost")

    vertex = model_catalog.find_model_entry(
        LlmProviderNames.VERTEX_AI, "claude-sonnet-4-5@20250929"
    )
    assert vertex is not None, "vertex @-revision alias stopped resolving"


def test_mode_filter_keeps_picklists_chat_only() -> None:
    """Non-chat models (image, realtime, transcription) must not leak into
    chat picklists — regression guard for the iter_models(mode=...) filter."""
    all_models = model_catalog.iter_models(LlmProviderNames.OPENAI)
    chat_models = model_catalog.iter_models(LlmProviderNames.OPENAI, mode="chat")
    assert len(all_models) > len(chat_models), (
        "expected non-chat entries in the openai section"
    )
    assert "dall-e-3" in all_models
    assert "dall-e-3" not in chat_models


def test_picklist_models_are_priced() -> None:
    """Every model shown in a curated picklist must resolve to priced catalog
    data — an unpriced picklist entry means a user-visible model bills $0."""
    picklists = {
        LlmProviderNames.OPENAI: get_openai_model_names(),
        LlmProviderNames.ANTHROPIC: get_anthropic_model_names(),
        LlmProviderNames.VERTEX_AI: get_vertexai_model_names(),
    }
    for provider, names in picklists.items():
        assert names, f"{provider} picklist is empty"
        for name in names:
            cost = model_catalog.find_model_cost(provider, name)
            assert cost is not None and cost.get("input") is not None, (
                f"{provider} picklist model {name!r} has no catalog pricing"
            )


def test_local_providers_bill_zero() -> None:
    """Self-hosted runtimes have no API bill — a cross-provider pricing leak
    would charge local inference at hosted rates."""
    assert model_catalog.find_model_cost("ollama_chat", "llama3.1") is None
    assert model_catalog.find_model_cost("lm_studio", "qwen") is None


def test_embedding_detection_uses_mode() -> None:
    """Embedding detection must use the catalog's mode field, not just the
    name heuristic — a missing mode silently misclassifies."""
    assert model_catalog.is_embedding_model_name("text-embedding-3-large") is True
    assert model_catalog.is_embedding_model_name("gpt-5") is False
