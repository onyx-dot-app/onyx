"""opencode.json builders.

opencode-serve loads config once at startup and does not hot-reload
(sst/opencode#22213), so both the K8s and docker paths pre-load every
supported provider — real key (or proxy placeholder) when configured, dummy
key otherwise — letting per-prompt model overrides cross providers without a
restart.
"""

from typing import Any

from onyx.llm.constants import LlmProviderNames
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


def opencode_provider_id(provider: str) -> str:
    """Provider ID to write into opencode config/request bodies.

    Onyx stores OpenAI-compatible endpoints as ``openai_compatible`` so the
    rest of the platform can distinguish them from first-party OpenAI. OpenCode
    expects these endpoints under the ``openai`` provider with a custom API
    base, so Craft translates at the sandbox boundary.
    """
    if provider == LlmProviderNames.OPENAI_COMPATIBLE:
        return "openai"
    return provider


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
    model_block: dict[str, Any] = {}
    if options:
        model_block["options"] = options
    # Dynamic OpenAI-compatible endpoints need explicit model declarations;
    # otherwise OpenCode falls back to its built-in OpenAI catalog and rejects
    # platform models (or stale discovered names) before the request reaches the
    # custom API base.
    if options or provider_config.provider == LlmProviderNames.OPENAI_COMPATIBLE:
        block["models"] = {provider_config.model_name: model_block}
    return block


def _build_provider_blocks(
    providers: list[LLMProviderConfig],
) -> dict[str, dict[str, Any]]:
    """Merge configs that target the same OpenCode provider ID.

    Multiple Onyx configs can render as OpenCode ``openai``: first-party OpenAI
    plus OpenAI-compatible endpoints, or several model entries for the same
    OpenAI-compatible endpoint. Preserve first writer credentials/API base so
    the default config remains authoritative, but union model declarations so
    per-message overrides can use any visible platform model.
    """
    blocks: dict[str, dict[str, Any]] = {}
    for provider_config in providers:
        provider_id = opencode_provider_id(provider_config.provider)
        next_block = _build_provider_block(provider_config)
        current = blocks.setdefault(provider_id, {})
        if "options" not in current and "options" in next_block:
            current["options"] = next_block["options"]
        if "api" not in current and "api" in next_block:
            current["api"] = next_block["api"]
        if "models" in next_block:
            current.setdefault("models", {}).update(next_block["models"])
    return blocks


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

    provider_blocks = _build_provider_blocks(providers)
    provider_names = set(provider_blocks)
    default_provider_id = opencode_provider_id(default_provider)
    if default_provider_id not in provider_names:
        raise ValueError(
            f"default_provider={default_provider!r} not in providers"
            f" {sorted(provider_names)}"
        )

    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{default_provider_id}/{default_model}",
        "provider": provider_blocks,
        "enabled_providers": sorted(provider_names),
        "permission": _build_permissions(disabled_tools, dev_mode),
    }
    if plugins:
        config["plugin"] = list(plugins)
    return config
