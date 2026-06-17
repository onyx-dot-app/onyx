"""The Docker manager bakes a multi-provider opencode.json at container start.

Every supported provider must be registered so a per-prompt cross-provider
override never hits "model not found". When the egress proxy is enabled, real
keys are swapped for the placeholder (the proxy injects the live key on the
wire); without the proxy, keys (including the not-configured dummy) are baked
verbatim so an unconfigured provider fails closed upstream (401).
"""

from __future__ import annotations

import json

import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as dsm
from onyx.server.features.build.configs import BUILD_MODE_NOT_CONFIGURED_API_KEY
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


_OPENAI = _config("openai", _REAL_KEY)
_ANTHROPIC_CONFIGURED = _config("anthropic", _REAL_KEY)
_OPENROUTER_DUMMY = _config("openrouter", BUILD_MODE_NOT_CONFIGURED_API_KEY)


def test_all_configs_registered_no_proxy_keeps_keys_verbatim() -> None:
    configs = dsm._container_llm_configs(
        [_OPENAI, _ANTHROPIC_CONFIGURED, _OPENROUTER_DUMMY],
        _OPENAI,
        proxy_enabled=False,
    )
    by = {c.provider: c for c in configs}
    assert set(by) == {"openai", "anthropic", "openrouter"}
    # Real keys stay real (the proxy isn't there to inject them)...
    assert by["openai"].api_key == _REAL_KEY
    assert by["anthropic"].api_key == _REAL_KEY
    # ...and the unconfigured provider keeps its dummy key -> fails closed (401).
    assert by["openrouter"].api_key == BUILD_MODE_NOT_CONFIGURED_API_KEY


def test_proxy_swaps_real_keys_for_placeholder() -> None:
    configs = dsm._container_llm_configs(
        [_OPENAI, _ANTHROPIC_CONFIGURED, _OPENROUTER_DUMMY],
        _OPENAI,
        proxy_enabled=True,
    )
    # Every truthy key (real AND the dummy) becomes the placeholder; on K8s/proxy
    # the proxy decides per-provider whether a real key exists.
    assert all(c.api_key == SANDBOX_PROXY_INJECTED_PLACEHOLDER for c in configs)
    # Non-secret routing inputs survive.
    assert {c.provider for c in configs} == {"openai", "anthropic", "openrouter"}


def test_keyless_provider_stays_keyless_under_proxy() -> None:
    # api_key=None (e.g. Ollama) must not get the placeholder, or it would reach
    # the LLM verbatim.
    configs = dsm._container_llm_configs(
        [_config("ollama", None)], _config("ollama", None), proxy_enabled=True
    )
    assert configs[0].api_key is None


def test_falls_back_to_single_config_when_all_is_none() -> None:
    configs = dsm._container_llm_configs(None, _OPENAI, proxy_enabled=False)
    assert configs == [_OPENAI]


def test_rendered_config_registers_every_provider_and_leaks_no_real_key() -> None:
    configs = dsm._container_llm_configs(
        [_OPENAI, _ANTHROPIC_CONFIGURED, _OPENROUTER_DUMMY],
        _OPENAI,
        proxy_enabled=True,
    )
    config = build_multi_provider_opencode_config(
        providers=configs,
        default_provider="openai",
        default_model="m",
    )
    # All three providers enabled so per-prompt overrides can target any of them.
    assert set(config["enabled_providers"]) == {"openai", "anthropic", "openrouter"}
    # Single prefix, no double-prefix.
    assert config["model"] == "openai/m"
    # No real key shipped to the container under the proxy posture.
    assert _REAL_KEY not in json.dumps(config)
