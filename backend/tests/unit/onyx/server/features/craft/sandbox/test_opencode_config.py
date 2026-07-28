from __future__ import annotations

import json

import pytest

from onyx.server.features.build.configs import MCP_SESSION_TAG_HEADER
from onyx.server.features.build.sandbox.models import (
    CraftLLMProviderConfig,
    CraftMCPServerConfig,
)
from onyx.server.features.build.sandbox.util.mcp_config import craft_mcp_fingerprint
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_opencode_base_config,
    build_provider_opencode_config,
)
from onyx.server.gateway.models import (
    GatewayModelCapabilities,
    GatewayModelDescriptor,
)


def _gateway(*, default: str = "7/gpt-5.5") -> CraftLLMProviderConfig:
    return CraftLLMProviderConfig(
        provider="onyx",
        model_name=default,
        api_key="proxy-placeholder",
        api_base="https://onyx.test/api/gateway/v1",
        display_name="Onyx",
        models=[
            GatewayModelDescriptor(
                id="7/gpt-5.5",
                display_name="GPT-5.5",
                provider="openai",
            ),
            GatewayModelDescriptor(
                id="9/claude-opus-4-8",
                display_name="Claude Opus 4.8",
                provider="anthropic",
                capabilities=GatewayModelCapabilities(
                    input_modalities=("text", "image"),
                    supports_reasoning=True,
                ),
                max_input_tokens=200_000,
                max_output_tokens=128_000,
            ),
        ],
    )


def _mcp(
    key: str,
    url: str = "https://mcp.example.com/mcp",
    disabled_tools: tuple[str, ...] = (),
) -> CraftMCPServerConfig:
    return CraftMCPServerConfig(
        key=key, url=url, disabled_tools=disabled_tools, server_id=1
    )


def test_gateway_is_the_only_enabled_provider() -> None:
    config = build_provider_opencode_config(_gateway())
    assert config["model"] == "onyx/7/gpt-5.5"
    assert config["enabled_providers"] == ["onyx"]
    provider = config["provider"]["onyx"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"] == {
        "apiKey": "proxy-placeholder",
        "baseURL": "https://onyx.test/api/gateway/v1",
    }
    assert set(provider["models"]) == {"7/gpt-5.5", "9/claude-opus-4-8"}
    assert provider["models"]["9/claude-opus-4-8"]["limit"] == {
        "context": 200_000,
        "input": 200_000,
        "output": 128_000,
    }
    assert provider["models"]["7/gpt-5.5"] == {
        "name": "GPT-5.5",
        "attachment": False,
        "reasoning": False,
        "temperature": False,
        "tool_call": True,
        "modalities": {
            "input": ["text"],
            "output": ["text"],
        },
    }
    assert provider["models"]["9/claude-opus-4-8"] == {
        "name": "Claude Opus 4.8",
        "attachment": True,
        "reasoning": True,
        "temperature": False,
        "tool_call": True,
        "modalities": {
            "input": ["text", "image"],
            "output": ["text"],
        },
        "options": {"reasoningEffort": "high"},
        "limit": {
            "context": 200_000,
            "input": 200_000,
            "output": 128_000,
        },
    }


def test_gateway_capabilities_are_adapted_instead_of_hardcoded() -> None:
    gateway = CraftLLMProviderConfig(
        provider="onyx",
        model_name="4/custom-model",
        api_key=None,
        api_base="https://onyx.test/api/gateway/v1",
        models=[
            GatewayModelDescriptor(
                id="4/custom-model",
                display_name="Custom Model",
                provider="custom",
                capabilities=GatewayModelCapabilities(
                    input_modalities=("text", "image", "pdf"),
                    output_modalities=("text", "audio"),
                    supports_tool_calls=False,
                    supports_temperature=True,
                    supports_interleaved_reasoning=True,
                ),
            )
        ],
    )

    model = build_provider_opencode_config(gateway)["provider"]["onyx"]["models"][
        "4/custom-model"
    ]

    assert model == {
        "name": "Custom Model",
        "attachment": True,
        "reasoning": False,
        "temperature": True,
        "tool_call": False,
        "interleaved": True,
        "modalities": {
            "input": ["text", "image", "pdf"],
            "output": ["text", "audio"],
        },
    }


def test_gateway_omits_partial_token_limits() -> None:
    gateway = CraftLLMProviderConfig(
        provider="onyx",
        model_name="7/broken-model",
        api_key=None,
        api_base="https://onyx.test/api/gateway/v1",
        models=[
            GatewayModelDescriptor(
                id="7/broken-model",
                display_name="Broken",
                provider="custom",
                max_input_tokens=32_000,
            )
        ],
    )

    model = build_provider_opencode_config(gateway)["provider"]["onyx"]["models"][
        "7/broken-model"
    ]
    assert "limit" not in model


def test_default_must_exist_in_gateway_catalog() -> None:
    with pytest.raises(ValueError, match="not in the provider catalog"):
        build_provider_opencode_config(_gateway(default="missing"))


def test_session_config_is_json_for_gateway() -> None:
    rendered = json.dumps(
        build_provider_opencode_config(_gateway(), disabled_tools=["question"])
    )
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


def test_pod_global_base_config_never_carries_mcp() -> None:
    # Craft MCP servers live in the per-session config so they can hot-reload;
    # the pod-global base config must not carry them.
    assert "mcp" not in build_opencode_base_config()


def test_session_config_without_mcp_omits_mcp_key() -> None:
    assert "mcp" not in build_provider_opencode_config(_gateway())


def test_session_config_carries_mcp_with_session_tag_header() -> None:
    config = build_provider_opencode_config(
        _gateway(),
        mcp_servers=[_mcp("linear-7", url="https://mcp.linear.app/mcp")],
        session_id="sess-abc",
    )
    assert config["mcp"] == {
        "linear-7": {
            "type": "remote",
            "url": "https://mcp.linear.app/mcp",
            "enabled": True,
            # The proxy owns credentials; opencode must not run its own OAuth
            # discovery.
            "oauth": False,
            # The proxy reads this to attribute the tool call to a session for
            # approval (no per-user credentials — the proxy injects those).
            "headers": {MCP_SESSION_TAG_HEADER: "sess-abc"},
        }
    }


def test_session_config_requires_session_id_when_mcp_present() -> None:
    with pytest.raises(ValueError, match="session_id is required"):
        build_provider_opencode_config(_gateway(), mcp_servers=[_mcp("linear-7")])


def test_mcp_tool_curation_maps_to_wildcard_allow_and_deny_permissions() -> None:
    config = build_provider_opencode_config(
        _gateway(),
        mcp_servers=[_mcp("linear-7", disabled_tools=("delete_issue",))],
        session_id="sess-1",
    )
    permission = config["permission"]
    assert permission["linear-7_*"] == "allow"
    assert permission["linear-7_delete_issue"] == "deny"


def test_uncurated_mcp_server_still_gets_wildcard_allow() -> None:
    # Zero Tool rows: the wildcard must still allow so runtime-discovered tools
    # don't fall through to opencode's default "ask".
    config = build_provider_opencode_config(
        _gateway(), mcp_servers=[_mcp("linear-7")], session_id="sess-1"
    )
    assert config["permission"]["linear-7_*"] == "allow"


def _srv(
    server_id: int,
    url: str = "https://mcp.example.com/mcp",
    disabled_tools: tuple[str, ...] = (),
) -> CraftMCPServerConfig:
    return CraftMCPServerConfig(
        key=f"s-{server_id}",
        url=url,
        disabled_tools=disabled_tools,
        server_id=server_id,
    )


def test_craft_mcp_fingerprint_is_order_independent() -> None:
    a, b = _srv(1, url="u1"), _srv(2, url="u2")
    assert craft_mcp_fingerprint([a, b]) == craft_mcp_fingerprint([b, a])


def test_craft_mcp_fingerprint_reacts_to_each_input() -> None:
    base = [_srv(1, url="u1", disabled_tools=("x",))]
    baseline = craft_mcp_fingerprint(base)
    # server set — also how credential state reaches the digest
    assert craft_mcp_fingerprint(base + [_srv(2)]) != baseline
    assert craft_mcp_fingerprint([]) != baseline
    # url
    assert craft_mcp_fingerprint([_srv(1, url="u2", disabled_tools=("x",))]) != baseline
    # disabled-tool set
    assert (
        craft_mcp_fingerprint([_srv(1, url="u1", disabled_tools=("x", "y"))])
        != baseline
    )
