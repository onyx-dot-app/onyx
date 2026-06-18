"""The opencode config the K8s manager ships must never carry a real LLM key.

On Kubernetes the egress proxy injects the live per-tenant key on the wire, so
`_placeholder_llm_configs` strips every real key before the config reaches the
pod. These pin that swap and that the rendered opencode.json leaks no real key.
"""

from __future__ import annotations

import json

import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
from onyx.server.features.build.configs import SANDBOX_PROXY_INJECTED_PLACEHOLDER
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_multi_provider_opencode_config,
)

_REAL_KEY = "sk-real-secret-do-not-ship"


def _config(
    provider: str, api_key: str | None, api_base: str | None = None
) -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=provider, model_name="m", api_key=api_key, api_base=api_base
    )


def test_placeholder_swap_replaces_real_keys_keeps_routing() -> None:
    swapped = ksm._placeholder_llm_configs(
        [
            _config("openai", _REAL_KEY),
            _config("anthropic", _REAL_KEY, api_base="https://gw.example/v1"),
        ]
    )
    assert [c.api_key for c in swapped] == [SANDBOX_PROXY_INJECTED_PLACEHOLDER] * 2
    # provider / model / api_base (non-secret routing inputs) are untouched.
    assert [c.provider for c in swapped] == ["openai", "anthropic"]
    assert swapped[1].api_base == "https://gw.example/v1"


def test_keyless_provider_stays_keyless() -> None:
    # No real key to strip, so no placeholder is injected either.
    assert ksm._placeholder_llm_configs([_config("openai", None)])[0].api_key is None


def test_rendered_opencode_config_leaks_no_real_key() -> None:
    swapped = ksm._placeholder_llm_configs(
        [_config("openai", _REAL_KEY), _config("anthropic", _REAL_KEY)]
    )
    config = build_multi_provider_opencode_config(
        providers=swapped,
        default_provider="openai",
        default_model="m",
    )
    assert _REAL_KEY not in json.dumps(config)
    for provider in ("openai", "anthropic"):
        assert (
            config["provider"][provider]["options"]["apiKey"]
            == SANDBOX_PROXY_INJECTED_PLACEHOLDER
        )
