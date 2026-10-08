import json
from pathlib import Path
from typing import Any

from scripts.sync_price_table import (
    _preserve_unbounded_flags,
    merge_litellm,
    merge_openrouter,
)


def _providers() -> dict[str, Any]:
    return {
        key: {"models": {}, "aliases": {}}
        for key in ("anthropic", "openai", "bedrock", "bedrock_converse")
    }


def _chat_entry(provider: str, **extra: Any) -> dict[str, Any]:
    return {
        "litellm_provider": provider,
        "mode": "chat",
        "input_cost_per_token": 2e-06,
        "output_cost_per_token": 1e-05,
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 64_000,
        "supports_vision": True,
        "supports_reasoning": True,
        **extra,
    }


def test_merge_litellm_gap_fills_first_party_chat_models() -> None:
    providers = _providers()
    merge_litellm(providers, {"claude-new-flagship": _chat_entry("anthropic")})

    entry = providers["anthropic"]["models"]["claude-new-flagship"]
    assert entry["mode"] == "chat"
    assert entry["cost"] == {"input": 2.0, "output": 10.0}
    assert entry["limit"] == {"context": 1_000_000, "output": 64_000}
    assert entry["modalities"]["input"] == ["text", "image"]
    assert entry["reasoning"] is True


def test_merge_litellm_skips_non_gap_fill_chat_models() -> None:
    providers = _providers()
    merge_litellm(
        providers,
        {
            "bedrock/ai21.j2-mid-v1": _chat_entry("bedrock"),
            "ft:gpt-4.1-2025-04-14": _chat_entry("openai"),
            "eu/gpt-5": _chat_entry("openai"),
            "gpt-retired": _chat_entry("openai", deprecation_date="2020-01-01"),
            "gpt-unpriced": _chat_entry("openai", output_cost_per_token=None),
        },
    )

    assert all(not section["models"] for section in providers.values())


def test_merge_litellm_keeps_existing_rates() -> None:
    providers = _providers()
    providers["anthropic"]["models"]["claude-x"] = {
        "mode": "chat",
        "cost": {"input": 3.0, "output": 15.0},
    }
    merge_litellm(
        providers,
        {"claude-x": _chat_entry("anthropic", cache_read_input_token_cost=3e-07)},
    )

    assert providers["anthropic"]["models"]["claude-x"]["cost"] == {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
    }


def _or_model(
    model_id: str,
    *,
    tokenizer: str = "GPT",
    context_length: int | None = 1_000_000,
    price: str = "0.000001",
) -> dict[str, Any]:
    return {
        "id": model_id,
        "context_length": context_length,
        "architecture": {"tokenizer": tokenizer},
        "top_provider": {"context_length": context_length},
        "pricing": {"prompt": price, "completion": price},
        "supported_parameters": ["tools"],
    }


def _openrouter_section() -> dict[str, Any]:
    return {"openrouter": {"models": {}, "aliases": {}}}


def test_merge_openrouter_flags_endpointless_routers() -> None:
    providers: dict[str, Any] = _openrouter_section()
    models: dict[str, Any] = providers["openrouter"]["models"]
    models["vendor/free-router"] = {"mode": "chat"}  # already vendored
    models["vendor/real-model"] = {"mode": "chat", "unbounded": True}
    merge_openrouter(
        providers,
        [
            _or_model(
                "vendor/free-router",
                tokenizer="Router",
                context_length=None,
                price="0",
            ),
            _or_model("vendor/new-router", tokenizer="Router", context_length=None),
            # Same tokenizer but a declared endpoint: not unbounded, and a
            # stale flag on an existing entry is cleared.
            _or_model("vendor/real-model", tokenizer="Router"),
            _or_model("vendor/boring-model"),
        ],
    )

    assert models["vendor/free-router"]["unbounded"] is True
    assert models["vendor/new-router"]["unbounded"] is True
    assert "unbounded" not in models["vendor/real-model"]
    assert "unbounded" not in models["vendor/boring-model"]


def test_preserve_unbounded_flags_survives_feed_outage(tmp_path: Path) -> None:
    """A failed OpenRouter fetch must not drop router flags the merge can no
    longer re-derive — they carry over from the vendored file."""
    providers: dict[str, Any] = _openrouter_section()
    models: dict[str, Any] = providers["openrouter"]["models"]
    models["openrouter/auto"] = {"mode": "chat"}
    models["vendor/real-model"] = {"mode": "chat"}
    (tmp_path / "openrouter.json").write_text(
        json.dumps({"models": {"openrouter/auto": {"unbounded": True}}})
    )

    _preserve_unbounded_flags(providers, tmp_path)

    assert models["openrouter/auto"]["unbounded"] is True
    assert "unbounded" not in models["vendor/real-model"]
