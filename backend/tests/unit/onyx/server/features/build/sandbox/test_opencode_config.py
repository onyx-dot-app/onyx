from __future__ import annotations

import json

import pytest

from onyx.server.features.build.sandbox.models import (
    GatewayModelConfig,
    LLMProviderConfig,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_opencode_base_config,
    build_provider_opencode_config,
    build_session_opencode_config,
)


def _gateway(*, default: str = "7/gpt-5.5") -> LLMProviderConfig:
    return LLMProviderConfig(
        provider="onyx",
        model_name=default,
        api_key="proxy-placeholder",
        api_base="https://onyx.test/api/build/llm-gateway/v1",
        npm="@ai-sdk/openai-compatible",
        display_name="Onyx",
        models=[
            GatewayModelConfig(id="7/gpt-5.5", display_name="GPT-5.5"),
            GatewayModelConfig(
                id="9/claude-opus-4-8",
                display_name="Claude Opus 4.8",
                supports_reasoning=True,
                max_input_tokens=200_000,
            ),
        ],
    )


def test_gateway_is_the_only_enabled_provider() -> None:
    config = build_provider_opencode_config(_gateway())
    assert config["model"] == "onyx/7/gpt-5.5"
    assert config["enabled_providers"] == ["onyx"]
    provider = config["provider"]["onyx"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"] == {
        "apiKey": "proxy-placeholder",
        "baseURL": "https://onyx.test/api/build/llm-gateway/v1",
    }
    assert set(provider["models"]) == {"7/gpt-5.5", "9/claude-opus-4-8"}
    assert provider["models"]["9/claude-opus-4-8"]["limit"] == {
        "context": 200_000,
        "output": 32_000,
    }


def test_default_must_exist_in_gateway_catalog() -> None:
    with pytest.raises(ValueError, match="not in the provider catalog"):
        build_provider_opencode_config(_gateway(default="missing"))


def test_session_config_is_json_for_gateway() -> None:
    rendered = build_session_opencode_config(_gateway(), ["question"])
    assert json.loads(rendered)["permission"]["question"] == "deny"


def test_base_config_keeps_sandbox_permissions_and_plugins() -> None:
    config = build_opencode_base_config(
        disabled_tools=["question", "webfetch"],
        plugins=["/workspace/plugin.ts"],
    )
    assert config["plugin"] == ["/workspace/plugin.ts"]
    assert config["permission"]["question"] == "deny"
    assert config["permission"]["webfetch"] == "deny"
    assert config["permission"]["external_directory"] == {
        "*": "deny",
        "/tmp": "allow",
        "/tmp/**": "allow",
    }
    assert config["permission"]["skill"] == {
        "*": "allow",
        "customize-opencode": "deny",
    }


def test_dev_mode_allows_external_directories() -> None:
    assert (
        build_opencode_base_config(dev_mode=True)["permission"]["external_directory"]
        == "allow"
    )
