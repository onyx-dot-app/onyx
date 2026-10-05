from typing import Any

from scripts.sync_price_table import merge_litellm


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
