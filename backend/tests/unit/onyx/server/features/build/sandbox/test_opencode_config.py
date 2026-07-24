"""Tests for :func:`build_multi_provider_opencode_config`.

The multi-provider helper is what enables cross-provider per-prompt model
overrides on the opencode-serve path without restarting the pod. Correctness
here is load-bearing: a silent provider overwrite or a missing api_key in the
rendered ``opencode.json`` means user-facing "agent is suddenly using
big-pickle" / 401 / 'unknown provider' bugs.
"""

from __future__ import annotations

import pytest

from onyx.server.features.build.configs import MCP_SESSION_TAG_HEADER
from onyx.server.features.build.sandbox.models import (
    CraftMCPServerConfig,
    LLMProviderConfig,
)
from onyx.server.features.build.sandbox.util.mcp_config import craft_mcp_fingerprint
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_multi_provider_opencode_config,
    build_session_mcp_config,
)


def _cfg(
    provider: str,
    model: str,
    api_key: str | None = "sk-test",
    api_base: str | None = None,
) -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=provider, model_name=model, api_key=api_key, api_base=api_base
    )


def test_single_provider_renders_all_required_fields() -> None:
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7")],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
    )
    assert config["model"] == "anthropic/claude-opus-4-7"
    assert config["enabled_providers"] == ["anthropic"]
    assert config["provider"]["anthropic"]["options"]["apiKey"] == "sk-test"
    # opus-4-7 is in _ADAPTIVE_THINKING_MODELS, so adaptive thinking.
    # Anthropic defaults adaptive thinking display to "omitted"; explicit
    # summarized display is required for Craft to receive readable thought text.
    assert config["provider"]["anthropic"]["models"]["claude-opus-4-7"]["options"][
        "thinking"
    ] == {"type": "adaptive", "display": "summarized"}


def test_adaptive_anthropic_models_request_readable_thinking_summaries() -> None:
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-8")],
        default_provider="anthropic",
        default_model="claude-opus-4-8",
    )

    assert config["provider"]["anthropic"]["models"]["claude-opus-4-8"]["options"][
        "thinking"
    ] == {"type": "adaptive", "display": "summarized"}


def test_multi_provider_each_gets_its_own_block() -> None:
    """
    All three providers should be pre-loaded with their own api_key so
    per-prompt model override can target any of them without a pod restart.
    """
    config = build_multi_provider_opencode_config(
        providers=[
            _cfg("anthropic", "claude-opus-4-7", api_key="sk-ant-1"),
            _cfg("openai", "gpt-5.5", api_key="sk-oai-2"),
            _cfg("openrouter", "minimax/m2", api_key="sk-or-3"),
        ],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
    )
    assert set(config["enabled_providers"]) == {
        "anthropic",
        "openai",
        "openrouter",
    }
    assert config["provider"]["anthropic"]["options"]["apiKey"] == "sk-ant-1"
    assert config["provider"]["openai"]["options"]["apiKey"] == "sk-oai-2"
    assert config["provider"]["openrouter"]["options"]["apiKey"] == "sk-or-3"
    # The 'model' (session default) is the explicit default; per-prompt
    # overrides take precedence at call time.
    assert config["model"] == "anthropic/claude-opus-4-7"


def test_duplicate_providers_raise_value_error() -> None:
    """
    Passing two entries with the same provider would silently overwrite each
    other under a naive dict comprehension. Detect and refuse.
    """
    with pytest.raises(ValueError, match="duplicate provider entries"):
        build_multi_provider_opencode_config(
            providers=[
                _cfg("anthropic", "claude-opus-4-7", api_key="sk-1"),
                _cfg("anthropic", "claude-sonnet-4-6", api_key="sk-2"),
            ],
            default_provider="anthropic",
            default_model="claude-opus-4-7",
        )


def test_empty_providers_list_raises() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        build_multi_provider_opencode_config(
            providers=[],
            default_provider="anthropic",
            default_model="claude-opus-4-7",
        )


def test_default_provider_must_be_in_providers() -> None:
    """
    Mis-spelling default_provider is the kind of bug that would otherwise
    produce an invalid ``model`` field opencode rejects only at first prompt —
    fail fast at config-build time.
    """
    with pytest.raises(ValueError, match="not in providers"):
        build_multi_provider_opencode_config(
            providers=[_cfg("anthropic", "claude-opus-4-7")],
            default_provider="openai",
            default_model="gpt-5.5",
        )


def test_no_api_key_renders_no_options_block() -> None:
    """
    If the caller omits the api_key (e.g. a provider that uses env-var auth
    elsewhere), the ``options`` block should be absent rather than present with
    apiKey: null.
    """
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7", api_key=None)],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
    )
    block = config["provider"]["anthropic"]
    assert "options" not in block


def test_api_base_propagates() -> None:
    config = build_multi_provider_opencode_config(
        providers=[
            _cfg(
                "openai",
                "gpt-5-mini",
                api_key="sk-x",
                api_base="https://my-azure-mirror.example.com/v1",
            )
        ],
        default_provider="openai",
        default_model="gpt-5-mini",
    )
    assert (
        config["provider"]["openai"]["api"] == "https://my-azure-mirror.example.com/v1"
    )


def test_permission_block_allows_tmp_external_directory_by_default() -> None:
    """
    K8s + Docker run in container, so external_directory stays deny-by-default.
    ``/tmp`` is the one sandbox-local exception agents need for scratch files.
    Only ``dev_mode=True`` opens all external paths up.
    """
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7")],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
    )
    assert config["permission"]["external_directory"] == {
        "*": "deny",
        "/tmp": "allow",
        "/tmp/**": "allow",
    }
    assert list(config["permission"]["external_directory"].items()) == [
        ("*", "deny"),
        ("/tmp", "allow"),
        ("/tmp/**", "allow"),
    ]

    dev_config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7")],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
        dev_mode=True,
    )
    assert dev_config["permission"]["external_directory"] == "allow"


def test_disabled_tools_become_deny_entries() -> None:
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7")],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
        disabled_tools=["question", "webfetch"],
    )
    assert config["permission"]["question"] == "deny"
    assert config["permission"]["webfetch"] == "deny"


def test_skill_permission_denies_builtin_customize_opencode() -> None:
    """
    The built-in customize-opencode skill must be denied by name, with "*"
    before the deny since opencode evaluates skill rules via findLast().
    """
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7")],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
    )
    skill_perm = config["permission"]["skill"]
    assert skill_perm["customize-opencode"] == "deny"
    assert skill_perm["*"] == "allow"
    keys = list(skill_perm.keys())
    assert keys.index("*") < keys.index("customize-opencode")


def test_plugins_omitted_by_default() -> None:
    """
    No `plugin` key unless plugins are explicitly requested, so the default
    config stays byte-identical to pre-plugin behavior.
    """
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7")],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
    )
    assert "plugin" not in config


def test_plugins_are_emitted_when_provided() -> None:
    """
    The session-tagging plugin path flows into the `plugin` array so
    opencode-serve loads it pod-wide via OPENCODE_CONFIG_CONTENT.
    """
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7")],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
        plugins=["/workspace/opencode-plugins/session-proxy-tag.ts"],
    )
    assert config["plugin"] == ["/workspace/opencode-plugins/session-proxy-tag.ts"]


def _mcp(
    key: str,
    url: str = "https://mcp.example.com/mcp",
    disabled_tools: tuple[str, ...] = (),
) -> CraftMCPServerConfig:
    return CraftMCPServerConfig(
        key=key, url=url, disabled_tools=disabled_tools, server_id=1
    )


def test_pod_global_config_never_carries_mcp() -> None:
    # Craft MCP servers live in per-session config so they can hot-reload; the
    # pod-global config must not carry them.
    config = build_multi_provider_opencode_config(
        providers=[_cfg("anthropic", "claude-opus-4-7")],
        default_provider="anthropic",
        default_model="claude-opus-4-7",
    )
    assert "mcp" not in config


def test_no_mcp_servers_emits_only_schema() -> None:
    config = build_session_mcp_config([], "sess-1")
    assert config == {"$schema": "https://opencode.ai/config.json"}


def test_mcp_servers_emit_remote_entries_with_session_tag_header() -> None:
    config = build_session_mcp_config(
        [_mcp("linear-7", url="https://mcp.linear.app/mcp")], "sess-abc"
    )
    assert config["mcp"] == {
        "linear-7": {
            "type": "remote",
            "url": "https://mcp.linear.app/mcp",
            "enabled": True,
            # The proxy owns credentials, so opencode must not run its own OAuth
            # discovery against these servers.
            "oauth": False,
            # The proxy reads this to attribute the tool call to a session for
            # approval (no per-user credentials — the proxy injects those).
            "headers": {MCP_SESSION_TAG_HEADER: "sess-abc"},
        }
    }


def test_mcp_tool_curation_maps_to_wildcard_allow_and_deny_permissions() -> None:
    config = build_session_mcp_config(
        [_mcp("linear-7", disabled_tools=("delete_issue",))], "sess-1"
    )
    permission = config["permission"]
    assert permission["linear-7_*"] == "allow"
    assert permission["linear-7_delete_issue"] == "deny"


def test_uncurated_mcp_server_still_gets_wildcard_allow() -> None:
    # Zero Tool rows: the wildcard must still allow so runtime-discovered tools
    # don't fall through to opencode's default "ask".
    config = build_session_mcp_config([_mcp("linear-7")], "sess-1")
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
    # server set — also how credential state reaches the digest, since an
    # unauthenticated server is never resolved into the set.
    assert craft_mcp_fingerprint(base + [_srv(2)]) != baseline
    assert craft_mcp_fingerprint([]) != baseline
    # url
    assert craft_mcp_fingerprint([_srv(1, url="u2", disabled_tools=("x",))]) != baseline
    # disabled-tool set
    assert (
        craft_mcp_fingerprint([_srv(1, url="u1", disabled_tools=("x", "y"))])
        != baseline
    )
