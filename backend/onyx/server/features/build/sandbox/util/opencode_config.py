"""opencode.json builders.

opencode-serve loads config once at startup and does not hot-reload
(sst/opencode#22213), so both the K8s and docker paths pre-load every
supported provider — real key (or proxy placeholder) when configured, dummy
key otherwise — letting per-prompt model overrides cross providers without a
restart.
"""

from typing import Any

from onyx.server.features.build.sandbox.models import LLMProviderConfig

# 4.6+ supports adaptive thinking; older needs enabled+budgetTokens.
_ADAPTIVE_THINKING_MODELS = frozenset(
    {"claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-4-6"}
)


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
}


def _build_permissions(
    disabled_tools: list[str] | None, dev_mode: bool
) -> dict[str, Any]:
    permissions: dict[str, Any] = {
        k: (v.copy() if isinstance(v, dict) else v)
        for k, v in _PERMISSIONS_TEMPLATE.items()
    }
    permissions["external_directory"] = "allow" if dev_mode else {"*": "deny"}
    if disabled_tools:
        for tool in disabled_tools:
            permissions[tool] = "deny"
    return permissions


def _build_provider_block(
    provider_config: LLMProviderConfig,
) -> dict[str, Any]:
    block: dict[str, Any] = {}
    if provider_config.api_key:
        block["options"] = {"apiKey": provider_config.api_key}
    if provider_config.api_base:
        block["api"] = provider_config.api_base
    options = _model_options(provider_config.provider, provider_config.model_name)
    if options:
        block["models"] = {provider_config.model_name: {"options": options}}
    return block


def build_opencode_config(
    provider: str,
    model_name: str,
    api_key: str | None = None,
    api_base: str | None = None,
    disabled_tools: list[str] | None = None,
    dev_mode: bool = False,
    plugins: list[str] | None = None,
) -> dict[str, Any]:
    """Single-provider wrapper around :func:`build_multi_provider_opencode_config`."""
    return build_multi_provider_opencode_config(
        providers=[
            LLMProviderConfig(
                provider=provider,
                model_name=model_name,
                api_key=api_key,
                api_base=api_base,
            )
        ],
        default_provider=provider,
        default_model=model_name,
        disabled_tools=disabled_tools,
        dev_mode=dev_mode,
        plugins=plugins,
    )


def build_multi_provider_opencode_config(
    providers: list[LLMProviderConfig],
    default_provider: str,
    default_model: str,
    disabled_tools: list[str] | None = None,
    dev_mode: bool = False,
    plugins: list[str] | None = None,
) -> dict[str, Any]:
    """opencode.json with every provider pre-registered so per-prompt
    ``body["model"]`` overrides can target any of them.

    ``plugins`` is an optional list of opencode plugin specs (npm names or
    absolute file paths) loaded once per session Instance.

    Raises:
        ValueError: If ``providers`` is empty or ``default_provider`` is
            not in ``providers``.
    """
    if not providers:
        raise ValueError("providers must contain at least one entry")

    seen: set[str] = set()
    duplicates = [
        p.provider for p in providers if p.provider in seen or seen.add(p.provider)
    ]  # type: ignore[func-returns-value]
    if duplicates:
        raise ValueError(
            f"duplicate provider entries: {duplicates!r} — opencode.json "
            "uses one block per providerID; merge them at the call site"
        )

    provider_names = {p.provider for p in providers}
    if default_provider not in provider_names:
        raise ValueError(
            f"default_provider={default_provider!r} not in providers"
            f" {sorted(provider_names)}"
        )

    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{default_provider}/{default_model}",
        "provider": {p.provider: _build_provider_block(p) for p in providers},
        "enabled_providers": sorted(provider_names),
        "permission": _build_permissions(disabled_tools, dev_mode),
    }
    if plugins:
        config["plugin"] = list(plugins)
    return config
