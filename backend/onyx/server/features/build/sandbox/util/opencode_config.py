"""opencode.json builders.

opencode-serve loads config once at startup and does not hot-reload
(sst/opencode#22213). The pod-wide base config carries permissions and
plugins; the per-session ``opencode.json`` layers on the gateway provider
catalog + default model AND the craft MCP servers, both of which opencode
deep-merges over the pod-global config and re-reads when the session's
instance is disposed — so a model change or an MCP-set change hot-reloads
without a pod re-provision.
"""

from collections.abc import Sequence
from typing import Any

from onyx.server.features.build.configs import MCP_SESSION_TAG_HEADER
from onyx.server.features.build.sandbox.models import (
    CraftLLMProviderConfig,
    CraftMCPServerConfig,
)

# Fallback output budget for gateway models the litellm map has no entry for
# (build_onyx_gateway_config derives the real per-model value). 128k matches the
# recommended Craft models (Claude Fable/Opus 4.8, GPT-5.6) per models.dev;
# providers enforce their own real caps regardless.
_GATEWAY_DEFAULT_MAX_OUTPUT_TOKENS = 128_000

# The gateway is an OpenAI-compatible endpoint, wired via opencode's
# openai-compatible SDK package.
_OPENAI_COMPATIBLE_NPM = "@ai-sdk/openai-compatible"


_PERMISSIONS_TEMPLATE: dict[str, Any] = {
    "bash": {
        "rm": "deny",
        "ssh": "deny",
        "scp": "deny",
        "sftp": "deny",
        "ftp": "deny",
        "telnet": "deny",
        "nc": "deny",
        "netcat": "deny",
        "tac": "deny",
        "nl": "deny",
        "od": "deny",
        "xxd": "deny",
        "hexdump": "deny",
        "strings": "deny",
        "base64": "deny",
        "*": "allow",
    },
    "edit": {
        "opencode.json": "deny",
        "**/opencode.json": "deny",
        "*": "allow",
    },
    "write": {
        "opencode.json": "deny",
        "**/opencode.json": "deny",
        "*": "allow",
    },
    "read": {
        "*": "allow",
        "opencode.json": "deny",
        "**/opencode.json": "deny",
    },
    "grep": {
        "*": "allow",
        "opencode.json": "deny",
        "**/opencode.json": "deny",
    },
    "glob": {
        "*": "allow",
        "opencode.json": "deny",
        "**/opencode.json": "deny",
    },
    "list": "allow",
    "lsp": "allow",
    "patch": "allow",
    # Deny opencode's built-in customize-opencode skill (edits opencode.json
    # via the skill tool, bypassing our edit/write denies). "*" must precede
    # the named deny — opencode evaluates skill rules with findLast().
    "skill": {"*": "allow", "customize-opencode": "deny"},
    "question": "allow",
    "webfetch": "allow",
    # Connect-app tool: a no-op tool the agent calls to request connecting an
    # external app it isn't set up for.
    "connect_app": "ask",
}

_TMP_EXTERNAL_DIRECTORY_RULES: dict[str, str] = {
    # OpenCode applies granular permission objects by pattern match with the
    # last matching rule winning. Keep the catch-all first so the /tmp allow
    # rules override it without opening any other external paths.
    "*": "deny",
    "/tmp": "allow",  # noqa: S108 - sandbox-local scratch path.
    "/tmp/**": "allow",  # noqa: S108 - sandbox-local scratch path.
}


def _build_permissions(
    disabled_tools: list[str] | None,
    dev_mode: bool,
    mcp_servers: Sequence[CraftMCPServerConfig] = (),
) -> dict[str, Any]:
    permissions: dict[str, Any] = {
        k: (v.copy() if isinstance(v, dict) else v)
        for k, v in _PERMISSIONS_TEMPLATE.items()
    }
    permissions["external_directory"] = (
        "allow" if dev_mode else _TMP_EXTERNAL_DIRECTORY_RULES.copy()
    )
    if disabled_tools:
        for tool in disabled_tools:
            permissions[tool] = "deny"
    # MCP tool ids are ``<serverKey>_<toolName>``. The wildcard allow defers
    # gating to the sandbox proxy and covers tools discovered at runtime.
    for server in mcp_servers:
        permissions[f"{server.key}_*"] = "allow"
        for tool_name in server.disabled_tools:
            permissions[f"{server.key}_{tool_name}"] = "deny"
    return permissions


def _build_session_mcp_block(
    mcp_servers: Sequence[CraftMCPServerConfig],
    session_id: str,
) -> dict[str, dict[str, Any]]:
    """opencode remote ``mcp`` entries for a session.

    Each server carries the ``MCP_SESSION_TAG_HEADER`` header stamped with
    ``session_id``: opencode's in-process MCP client uses the untagged base
    proxy env, so this header is how the egress proxy attributes a tool call to
    its session for approval (the proxy strips it before the origin sees it).
    The tag is a same-user attribution hint, not a security boundary — a sandbox
    is one trust domain per user, so the value is not tamper-proof against a
    compromised process in it (see the note in the gate). Credentials are
    injected by the proxy; the only header we set is the session tag.
    """
    # ``oauth: false`` keeps opencode from running its own discovery against
    # paths the proxy blocks, which reports `needs_auth` for servers that work.
    return {
        server.key: {
            "type": "remote",
            "url": server.url,
            "enabled": True,
            "oauth": False,
            "headers": {MCP_SESSION_TAG_HEADER: session_id},
        }
        for server in mcp_servers
    }


def _build_provider_block(
    llm_provider_config: CraftLLMProviderConfig,
) -> dict[str, Any]:
    """The gateway is an openai-compatible provider with no models.dev entry, so
    its baseURL goes in ``options`` and its model list must be explicit."""
    options: dict[str, Any] = {}
    if llm_provider_config.api_key:
        options["apiKey"] = llm_provider_config.api_key
    if llm_provider_config.api_base:
        options["baseURL"] = llm_provider_config.api_base
    block: dict[str, Any] = {"npm": _OPENAI_COMPATIBLE_NPM, "options": options}
    if llm_provider_config.display_name:
        block["name"] = llm_provider_config.display_name
    models: dict[str, Any] = {}
    for model in llm_provider_config.models or []:
        entry: dict[str, Any] = {"name": model.display_name}
        if model.supports_reasoning:
            entry["options"] = {"reasoningEffort": "high"}
        if model.max_input_tokens:
            # opencode's schema requires both keys when "limit" is present.
            entry["limit"] = {
                "context": model.max_input_tokens,
                "output": model.max_output_tokens or _GATEWAY_DEFAULT_MAX_OUTPUT_TOKENS,
            }
        models[model.id] = entry
    block["models"] = models
    return block


def build_opencode_base_config(
    disabled_tools: list[str] | None = None,
    dev_mode: bool = False,
    plugins: list[str] | None = None,
) -> dict[str, Any]:
    """Pod-wide base config: permissions and plugins only.

    Providers and craft MCP servers are NOT emitted here — they live in the
    per-session ``opencode.json`` (see ``build_provider_opencode_config``) so
    a model change or MCP-set change hot-reloads without a pod re-provision.
    """
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "permission": _build_permissions(disabled_tools, dev_mode),
    }
    if plugins:
        config["plugin"] = list(plugins)
    return config


def build_provider_opencode_config(
    llm_provider_config: CraftLLMProviderConfig,
    disabled_tools: list[str] | None = None,
    dev_mode: bool = False,
    plugins: list[str] | None = None,
    mcp_servers: Sequence[CraftMCPServerConfig] = (),
    session_id: str | None = None,
) -> dict[str, Any]:
    """Per-session ``opencode.json``: the gateway provider catalog + default
    model, plus the craft MCP servers (session-tagged) and their per-tool
    permission gates. opencode deep-merges this over the pod-global base.
    """
    if (
        llm_provider_config.models is not None
        and llm_provider_config.model_name
        not in {model.id for model in llm_provider_config.models}
    ):
        raise ValueError(
            f"default model {llm_provider_config.model_name!r} is not in the provider catalog"
        )

    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{llm_provider_config.provider}/{llm_provider_config.model_name}",
        "provider": {
            llm_provider_config.provider: _build_provider_block(llm_provider_config)
        },
        "enabled_providers": [llm_provider_config.provider],
        "permission": _build_permissions(disabled_tools, dev_mode, mcp_servers),
    }
    if plugins:
        config["plugin"] = list(plugins)
    if mcp_servers:
        if session_id is None:
            raise ValueError("session_id is required when mcp_servers are provided")
        config["mcp"] = _build_session_mcp_block(mcp_servers, session_id)
    return config
