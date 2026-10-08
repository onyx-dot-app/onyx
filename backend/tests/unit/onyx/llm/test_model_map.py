from typing import Any
from unittest.mock import patch

from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.llm import model_catalog
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_capabilities import (
    find_model_obj,
    get_model_map,
    model_is_reasoning_model,
)


def _fresh_model_map() -> dict:
    model_catalog.build_model_map.cache_clear()
    get_model_map.cache_clear()
    return get_model_map()


def _reset_caches() -> None:
    model_catalog.build_model_map.cache_clear()
    get_model_map.cache_clear()


def test_partial_match_in_model_map() -> None:
    """
    We should handle adding/not adding the provider prefix to the model name.
    """
    model_map = _fresh_model_map()
    try:
        _EXPECTED_FIELDS = {
            "max_input_tokens": 128000,
            "max_output_tokens": 16384,
            "max_tokens": 128000,
            "supports_function_calling": True,
            "supports_reasoning": False,
            "supports_response_schema": True,
            "supports_vision": True,
            "litellm_provider": "openai",
        }

        # ollama_chat carries no gpt-4o, so both names resolve through the
        # bare-key pass: "openai/gpt-4o" as a provider-scoped key, then
        # "gpt-4o" as a bare key owned by openai.
        result1 = find_model_obj(
            model_map, LlmProviderNames.OLLAMA_CHAT, "openai/gpt-4o"
        )
        assert result1 is not None
        for key, value in _EXPECTED_FIELDS.items():
            assert key in result1
            assert result1[key] == value, "Unexpected value for key: {}".format(key)

        result2 = find_model_obj(model_map, LlmProviderNames.OLLAMA_CHAT, "gpt-4o")
        assert result2 is not None
        for key, value in _EXPECTED_FIELDS.items():
            assert key in result2
            assert result2[key] == value, "Unexpected value for key: {}".format(key)
    finally:
        _reset_caches()


def test_bare_key_prefers_canonical_owner() -> None:
    """A bare model id shared by several provider sections resolves to the
    canonical owner's entry, while provider-scoped keys stay separate."""
    mock_catalog = {
        "openai": {
            "models": {
                "gpt-4o": {
                    "name": "GPT-4o",
                    "reasoning": False,
                    "limit": {"context": 128000},
                }
            },
            "aliases": {},
        },
        "azure": {
            "models": {
                "gpt-4o": {
                    "name": "GPT-4o",
                    "reasoning": True,
                    "limit": {"context": 999},
                }
            },
            "aliases": {},
        },
    }

    with patch.object(model_catalog, "_catalog", return_value=mock_catalog):
        model_map = _fresh_model_map()
        try:
            bare = find_model_obj(model_map, "custom_provider", "gpt-4o")
            assert bare is not None
            assert bare["litellm_provider"] == "openai"
            assert bare["max_tokens"] == 128000

            scoped = find_model_obj(model_map, LlmProviderNames.AZURE, "gpt-4o")
            assert scoped is not None
            assert scoped["litellm_provider"] == "azure"
            assert scoped["max_tokens"] == 999
        finally:
            _reset_caches()


def test_model_is_reasoning_model_handles_none_in_model_map() -> None:
    """Regression: a catalog entry may carry supports_reasoning=None.
    model_is_reasoning_model must always return a bool, never None."""
    mock_catalog = {
        "openai": {
            "models": {
                "gpt-4o": {"reasoning": None},
                "o3": {"reasoning": True},
                "gpt-4o-mini": {},
            },
            "aliases": {},
        },
    }

    with (
        patch.object(model_catalog, "_catalog", return_value=mock_catalog),
        patch(
            "onyx.llm.model_capabilities._probe_supports_reasoning",
            return_value=False,
        ),
    ):
        _fresh_model_map()
        try:
            # None in map — should fall through to the probe
            assert model_is_reasoning_model("gpt-4o", "openai") is False

            # True in map — should return True without probing
            assert model_is_reasoning_model("o3", "openai") is True

            # Missing key — should fall through to the probe
            assert model_is_reasoning_model("gpt-4o-mini", "openai") is False
        finally:
            _reset_caches()


def test_unbounded_entry_drops_max_output_tokens() -> None:
    """Router meta-models flagged `unbounded` (e.g. openrouter/auto) route to
    endpoints smaller than their advertised limits, so the model map must not
    emit an output limit callers would send as max_tokens."""
    mock_catalog: dict[str, Any] = {
        "openrouter": {
            "models": {
                "openrouter/auto": {
                    "limit": {"context": 2_000_000, "output": 2_000_000},
                    "unbounded": True,
                },
                "vendor/real-model": {
                    "limit": {"context": 2_000_000, "output": 128_000},
                },
            },
            "aliases": {},
        },
    }

    with patch.object(model_catalog, "_catalog", return_value=mock_catalog):
        model_map = _fresh_model_map()
        try:
            router = find_model_obj(
                model_map, LlmProviderNames.OPENROUTER, "openrouter/auto"
            )
            assert router is not None
            assert router["max_output_tokens"] is None
            assert router["unbounded"] is True

            bounded = find_model_obj(
                model_map, LlmProviderNames.OPENROUTER, "vendor/real-model"
            )
            assert bounded is not None
            assert bounded["max_output_tokens"] == 128_000
            assert bounded["unbounded"] is None
        finally:
            _reset_caches()


def test_inflated_output_claim_drops_max_output_tokens() -> None:
    """Chat-mode entries whose vendored output limit is at or above the
    context window carry a pool-max fabrication, not a per-request cap —
    the model map must not emit it. Non-chat modes (image/TTS limits mean
    something else) are left alone."""
    mock_catalog: dict[str, Any] = {
        "wandb": {
            "models": {
                "vendor/fabricated": {
                    "mode": "chat",
                    "limit": {"context": 262_144, "output": 262_144},
                },
                "vendor/real": {
                    "mode": "chat",
                    "limit": {"context": 262_144, "output": 131_072},
                },
                "vendor/veo": {
                    "mode": "image",
                    "limit": {"context": 480, "output": 8192},
                },
            },
            "aliases": {},
        },
    }

    with patch.object(model_catalog, "_catalog", return_value=mock_catalog):
        model_map = _fresh_model_map()
        try:
            fabricated = find_model_obj(model_map, "wandb", "vendor/fabricated")
            assert fabricated is not None
            assert fabricated["max_output_tokens"] is None
            assert fabricated["unbounded"] is None

            real = find_model_obj(model_map, "wandb", "vendor/real")
            assert real is not None
            assert real["max_output_tokens"] == 131_072

            image = find_model_obj(model_map, "wandb", "vendor/veo")
            assert image is not None
            assert image["max_output_tokens"] == 8192
        finally:
            _reset_caches()


def test_chat_only_skips_non_chat_entries() -> None:
    """A bare-name scan can resolve a chat lookup to an image/embedding entry;
    chat_only makes it behave like a miss so callers get fallbacks."""
    mock_catalog: dict[str, Any] = {
        "openai": {
            "models": {
                "gpt-image-1": {
                    "mode": "image",
                    "limit": {"context": 0, "output": 0},
                },
            },
            "aliases": {},
        },
    }

    with patch.object(model_catalog, "_catalog", return_value=mock_catalog):
        model_map = _fresh_model_map()
        try:
            # Unfiltered lookup still resolves (cost/existence checks need it).
            assert find_model_obj(model_map, "custom", "gpt-image-1") is not None
            assert (
                find_model_obj(model_map, "custom", "gpt-image-1", chat_only=True)
                is None
            )
        finally:
            _reset_caches()


def test_chat_only_accepts_responses_mode_entries() -> None:
    """Responses-API models (mode "responses") are chat-shaped: budget lookups
    must keep their real limits, not the 32k fallback."""
    mock_catalog: dict[str, Any] = {
        "openai": {
            "models": {
                "gpt-5-pro": {
                    "mode": "responses",
                    "limit": {"context": 400_000, "output": 272_000},
                },
            },
            "aliases": {},
        },
    }

    with patch.object(model_catalog, "_catalog", return_value=mock_catalog):
        model_map = _fresh_model_map()
        try:
            obj = find_model_obj(model_map, "openai", "gpt-5-pro", chat_only=True)
            assert obj is not None
            assert obj["max_tokens"] == 400_000
            assert obj["max_output_tokens"] == 272_000
        finally:
            _reset_caches()


def _remote_response(section: dict[str, Any]) -> Any:
    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return section

    return _Resp()


def test_remote_catalog_resolves_missing_models() -> None:
    """Models absent from the vendored table resolve from the provider's
    remote price_table: compat conversion applies, hits stamp into the map,
    and the provider file is fetched at most once."""
    remote_section: dict[str, Any] = {
        "models": {
            "vendor/new-model": {
                "mode": "chat",
                "limit": {"context": 1_000_000, "output": 64_000},
                "cost": {"input": 1.0, "output": 2.0},
            },
        },
        "aliases": {"vendor/new-alias": "vendor/new-model"},
    }
    calls: list[str] = []

    def fake_get(provider: str) -> Any:
        calls.append(provider)
        return _remote_response(remote_section)

    with (
        patch.object(model_catalog, "_catalog", return_value={}),
        patch.object(model_catalog, "_fetch_provider_file", side_effect=fake_get),
    ):
        model_catalog.reset_remote_cache()
        model_map = _fresh_model_map()
        try:
            obj = find_model_obj(model_map, "wandb", "vendor/new-model")
            assert obj is not None
            assert obj["max_output_tokens"] == 64_000
            assert obj["litellm_provider"] == "wandb"

            # Second hit serves from the stamped map — no refetch.
            assert find_model_obj(model_map, "wandb", "vendor/new-model") is not None
            # Alias resolves against the same remote section.
            assert find_model_obj(model_map, "wandb", "vendor/new-alias") is not None
            assert len(calls) == 1

            # Cost lookups go through find_model_entry -> same remote file.
            assert model_catalog.find_model_cost("wandb", "vendor/new-model") == {
                "input": 1.0,
                "output": 2.0,
            }
            assert len(calls) == 1
        finally:
            _reset_caches()
            model_catalog.reset_remote_cache()


def test_remote_catalog_overrides_vendored() -> None:
    """Remote wins for entries it defines; vendored-only entries still
    resolve (the vendored file is the floor, not the primary)."""
    vendored: dict[str, Any] = {
        "wandb": {
            "models": {
                "vendor/m": {
                    "mode": "chat",
                    "limit": {"context": 100, "output": 50},
                    "cost": {"input": 1.0, "output": 1.0},
                },
                "vendor/old": {
                    "mode": "chat",
                    "limit": {"context": 10, "output": 5},
                    "cost": {"input": 0.5, "output": 0.5},
                },
            },
            "aliases": {},
        }
    }
    remote_section: dict[str, Any] = {
        "models": {
            "vendor/m": {
                "mode": "chat",
                "limit": {"context": 200, "output": 80},
                "cost": {"input": 5.0, "output": 5.0},
            },
        },
        "aliases": {},
    }

    def fake_get(_provider: str) -> Any:
        return _remote_response(remote_section)

    with (
        patch.object(model_catalog, "_catalog", return_value=vendored),
        patch.object(model_catalog, "_fetch_provider_file", side_effect=fake_get),
    ):
        model_catalog.reset_remote_cache()
        model_map = _fresh_model_map()
        try:
            obj = find_model_obj(model_map, "wandb", "vendor/m")
            assert obj is not None
            assert obj["max_tokens"] == 200
            assert model_catalog.find_model_cost("wandb", "vendor/m") == {
                "input": 5.0,
                "output": 5.0,
            }

            # Absent from remote but vendored — still resolves.
            assert find_model_obj(model_map, "wandb", "vendor/old") is not None
        finally:
            _reset_caches()
            model_catalog.reset_remote_cache()


def test_remote_catalog_fails_closed() -> None:
    """Fetch failures degrade to the normal miss and are negative-cached."""
    calls: list[str] = []

    def failing_get(provider: str) -> Any:
        calls.append(provider)
        raise model_catalog.httpx.ConnectError("offline")

    with (
        patch.object(model_catalog, "_catalog", return_value={}),
        patch.object(model_catalog, "_fetch_provider_file", side_effect=failing_get),
    ):
        model_catalog.reset_remote_cache()
        model_map = _fresh_model_map()
        try:
            assert find_model_obj(model_map, "wandb", "vendor/x") is None
            assert find_model_obj(model_map, "wandb", "vendor/y") is None
            assert len(calls) == 1
        finally:
            _reset_caches()
            model_catalog.reset_remote_cache()


def test_remote_catalog_respects_airgap() -> None:
    """ONYX_AIRGAPPED deployments never consult the remote catalog."""
    with (
        patch.object(model_catalog, "_catalog", return_value={}),
        patch.object(model_catalog, "ONYX_AIRGAPPED", True),
        patch.object(
            model_catalog,
            "_fetch_provider_file",
            side_effect=AssertionError("must not fetch when air-gapped"),
        ),
    ):
        model_catalog.reset_remote_cache()
        model_map = _fresh_model_map()
        try:
            assert find_model_obj(model_map, "wandb", "vendor/x") is None
        finally:
            _reset_caches()
            model_catalog.reset_remote_cache()


def test_remote_catalog_respects_chat_only() -> None:
    """A remote non-chat entry resolves unfiltered but not under chat_only."""
    remote_section: dict[str, Any] = {
        "models": {
            "vendor/new-image": {
                "mode": "image",
                "limit": {"context": 0, "output": 0},
            },
        },
        "aliases": {},
    }
    calls: list[str] = []

    def fake_get(provider: str) -> Any:
        calls.append(provider)
        return _remote_response(remote_section)

    with (
        patch.object(model_catalog, "_catalog", return_value={}),
        patch.object(model_catalog, "_fetch_provider_file", side_effect=fake_get),
    ):
        model_catalog.reset_remote_cache()
        model_map = _fresh_model_map()
        try:
            assert find_model_obj(model_map, "wandb", "vendor/new-image") is not None
            assert (
                find_model_obj(model_map, "wandb", "vendor/new-image", chat_only=True)
                is None
            )
        finally:
            _reset_caches()
            model_catalog.reset_remote_cache()


def test_twelvelabs_pegasus_override_present() -> None:
    model_map = _fresh_model_map()
    try:
        model_obj = find_model_obj(
            model_map,
            "twelvelabs",
            "us.twelvelabs.pegasus-1-2-v1:0",
        )
        assert model_obj is not None
        assert model_obj["max_input_tokens"] == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        assert model_obj["max_tokens"] == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        assert model_obj["supports_reasoning"] is False
    finally:
        _reset_caches()


def test_modeless_non_chat_ids_infer_mode_from_name() -> None:
    """Providers vendored from sources without a mode concept (e.g.
    vercel_ai_gateway) ship no mode field; embed/rerank ids must infer a
    non-chat mode or gateway model lists would offer them as chat models."""
    mock_catalog: dict[str, Any] = {
        "vercel_ai_gateway": {
            "models": {
                "cohere/embed-v5.0-fast": {
                    "limit": {"context": 512, "output": 512},
                },
                "cohere/rerank-v4-pro": {
                    "limit": {"context": 128_000, "output": 0},
                },
                "cohere/command-a": {
                    "limit": {"context": 256_000, "output": 8_000},
                },
            },
            "aliases": {},
        },
    }

    with (
        patch.object(model_catalog, "_catalog", return_value=mock_catalog),
        patch.object(
            model_catalog,
            "_fetch_provider_file",
            side_effect=model_catalog.httpx.ConnectError("offline"),
        ),
    ):
        model_catalog.reset_remote_cache()
        model_map = _fresh_model_map()
        try:
            for embed_name in ("cohere/embed-v5.0-fast", "cohere/rerank-v4-pro"):
                obj = find_model_obj(model_map, "vercel_ai_gateway", embed_name)
                assert obj is not None
                assert obj["mode"] == "embedding"
                assert (
                    find_model_obj(
                        model_map, "vercel_ai_gateway", embed_name, chat_only=True
                    )
                    is None
                )
                assert model_catalog.is_embedding_model_name(embed_name) is True
                assert embed_name not in model_catalog.iter_models(
                    "vercel_ai_gateway", mode="chat"
                )
                assert embed_name in model_catalog.iter_models(
                    "vercel_ai_gateway", mode="embedding"
                )

            chat = find_model_obj(model_map, "vercel_ai_gateway", "cohere/command-a")
            assert chat is not None
            assert chat["mode"] == "chat"
            assert model_catalog.is_embedding_model_name("cohere/command-a") is False
        finally:
            _reset_caches()
            model_catalog.reset_remote_cache()


def test_explicit_mode_wins_over_name_heuristic() -> None:
    """A vendored mode beats the name fallback — an upstream 'chat' entry
    named *-embed stays chat."""
    mock_catalog: dict[str, Any] = {
        "wandb": {
            "models": {
                "vendor/embed-named-chat": {
                    "mode": "chat",
                    "limit": {"context": 8_000},
                },
            },
            "aliases": {},
        },
    }

    with (
        patch.object(model_catalog, "_catalog", return_value=mock_catalog),
        patch.object(
            model_catalog,
            "_fetch_provider_file",
            side_effect=model_catalog.httpx.ConnectError("offline"),
        ),
    ):
        model_catalog.reset_remote_cache()
        model_map = _fresh_model_map()
        try:
            obj = find_model_obj(model_map, "wandb", "vendor/embed-named-chat")
            assert obj is not None
            assert obj["mode"] == "chat"
        finally:
            _reset_caches()
            model_catalog.reset_remote_cache()


def test_remote_catalog_malformed_entry_falls_back_to_vendored() -> None:
    """A remote entry _compat_entry can't render is a remote miss, not an
    error — the vendored floor still resolves the lookup."""
    vendored: dict[str, Any] = {
        "wandb": {
            "models": {
                "vendor/model": {
                    "mode": "chat",
                    "limit": {"context": 8_000},
                },
            },
            "aliases": {},
        }
    }
    remote_section: dict[str, Any] = {
        "models": {"vendor/model": "not-an-entry"},
        "aliases": {},
    }

    with (
        patch.object(model_catalog, "_catalog", return_value=vendored),
        patch.object(
            model_catalog,
            "_fetch_provider_file",
            return_value=_remote_response(remote_section),
        ),
    ):
        model_catalog.reset_remote_cache()
        model_map = _fresh_model_map()
        try:
            obj = find_model_obj(model_map, "wandb", "vendor/model")
            assert obj is not None
            assert obj["litellm_provider"] == "wandb"
            assert obj["max_tokens"] == 8_000
        finally:
            _reset_caches()
            model_catalog.reset_remote_cache()
