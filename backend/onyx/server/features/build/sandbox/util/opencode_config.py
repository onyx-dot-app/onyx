import json
from typing import Any

from onyx.server.features.build.sandbox.models import LLMProviderConfig

# 4.6+ supports adaptive thinking; older needs enabled+budgetTokens.
_ADAPTIVE_THINKING_MODELS = frozenset(
    {"claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-4-6"}
)

# Model configurations don't track max output tokens, so gateway model entries
# advertise this fixed budget to opencode. 128k matches the recommended Craft
# models (Claude Fable/Opus 4.8, GPT-5.6) per models.dev; providers enforce
# their own real caps on models with smaller limits.
_GATEWAY_DEFAULT_MAX_OUTPUT_TOKENS = 128_000


def _model_options(provider: str, model_name: str) -> dict[str, Any]:
    if provider == "openai":
        return {"reasoningEffort": "high"}
    if provider in ("anthropic", "bedrock"):
        if model_name in _ADAPTIVE_THINKING_MODELS or model_name.startswith(
            tuple(f"{m}-" for m in _ADAPTIVE_THINKING_MODELS)
        ):
            return {"thinking": {"type": "adaptive", "display": "summarized"}}
        return {"thinking": {"type": "enabled", "budgetTokens": 16000}}
    if provider == "google":
        return {"thinking_budget": 16000, "thinking_level": "high"}
    if provider == "azure":
        return {"reasoningEffort": "high"}
    return {}


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
    disabled_tools: list[str] | None, dev_mode: bool
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
    return permissions


def _build_provider_block(
    provider_config: LLMProviderConfig,
) -> dict[str, Any]:
    if provider_config.npm_package is not None:
        return _build_custom_provider_block(provider_config)
    block: dict[str, Any] = {}
    if provider_config.api_key:
        block["options"] = {"apiKey": provider_config.api_key}
    if provider_config.api_base:
        block["api"] = provider_config.api_base
    options = _model_options(provider_config.provider, provider_config.model_name)
    if options:
        block["models"] = {provider_config.model_name: {"options": options}}
    return block


def _build_custom_provider_block(
    provider_config: LLMProviderConfig,
) -> dict[str, Any]:
    """Unlike native providers, a custom provider's baseURL goes in
    ``options`` and its model list must be explicit (no models.dev entry)."""
    options: dict[str, Any] = {}
    if provider_config.api_key:
        options["apiKey"] = provider_config.api_key
    if provider_config.api_base:
        options["baseURL"] = provider_config.api_base
    # "npm" is opencode's config key for the AI-SDK package implementing
    # a custom provider's wire protocol.
    block: dict[str, Any] = {"npm": provider_config.npm_package, "options": options}
    if provider_config.display_name:
        block["name"] = provider_config.display_name
    models: dict[str, Any] = {}
    for model in provider_config.models or []:
        entry: dict[str, Any] = {"name": model.display_name}
        if model.supports_reasoning:
            entry["options"] = {"reasoningEffort": "high"}
        if model.max_input_tokens:
            # opencode's schema requires both keys when "limit" is present.
            entry["limit"] = {
                "context": model.max_input_tokens,
                "output": _GATEWAY_DEFAULT_MAX_OUTPUT_TOKENS,
            }
        models[model.id] = entry
    block["models"] = models
    return block


def build_opencode_base_config(
    disabled_tools: list[str] | None = None,
    dev_mode: bool = False,
    plugins: list[str] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "permission": _build_permissions(disabled_tools, dev_mode),
    }
    if plugins:
        config["plugin"] = list(plugins)
    return config


def build_provider_opencode_config(
    provider_config: LLMProviderConfig,
    disabled_tools: list[str] | None = None,
    dev_mode: bool = False,
    plugins: list[str] | None = None,
) -> dict[str, Any]:
    if provider_config.models is not None and provider_config.model_name not in {
        model.id for model in provider_config.models
    }:
        raise ValueError(
            f"default model {provider_config.model_name!r} is not in the provider catalog"
        )

    config = build_opencode_base_config(disabled_tools, dev_mode, plugins)
    config.update(
        {
            "model": f"{provider_config.provider}/{provider_config.model_name}",
            "provider": {
                provider_config.provider: _build_provider_block(provider_config)
            },
            "enabled_providers": [provider_config.provider],
        }
    )
    return config


def build_session_opencode_config(
    provider_config: LLMProviderConfig,
    disabled_tools: list[str],
) -> str:
    return json.dumps(
        build_provider_opencode_config(
            provider_config,
            disabled_tools=disabled_tools,
        )
    )
