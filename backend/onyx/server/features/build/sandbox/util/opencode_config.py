"""Shared opencode configuration generation.

This module provides a centralized way to generate opencode.json configuration
that is consistent across local and Kubernetes sandbox environments.
"""

from typing import Any


def build_opencode_config(
    provider: str,
    model_name: str,
    api_key: str | None = None,
    api_base: str | None = None,
    disabled_tools: list[str] | None = None,
    dev_mode: bool = False,
) -> dict[str, Any]:
    """Build opencode.json configuration dict.

    Creates the configuration structure for the opencode CLI agent with
    provider-specific settings for thinking/reasoning and tool permissions.

    Args:
        provider: LLM provider type (e.g., "openai", "anthropic")
        model_name: Model name (e.g., "claude-sonnet-4-5", "gpt-4o")
        api_key: Optional API key for the provider
        api_base: Optional custom API base URL
        disabled_tools: Optional list of tools to disable (e.g., ["question", "webfetch"])
        dev_mode: If True, allow all external directories. If False (Docker/Kubernetes),
                  only whitelist /workspace/files and /workspace/demo-data.

    Returns:
        Configuration dict ready to be serialized to JSON
    """
    # Build opencode model string: provider/model-name
    opencode_model = f"{provider}/{model_name}"

    # Build configuration with schema
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": opencode_model,
        "provider": {},
    }

    # Build provider configuration
    provider_config: dict[str, Any] = {}

    # Add API key if provided
    if api_key:
        provider_config["options"] = {"apiKey": api_key}

    # Add API base if provided
    if api_base:
        provider_config["api"] = api_base

    # Build model configuration with thinking/reasoning options
    options: dict[str, Any] = {}

    if provider == "openai":
        options["reasoningEffort"] = "high"
    elif provider == "anthropic":
        options["thinking"] = {
            "type": "enabled",
            "budgetTokens": 16000,
        }
    elif provider == "google":
        options["thinking_budget"] = 16000
        options["thinking_level"] = "high"
    elif provider == "bedrock":
        options["thinking"] = {
            "type": "enabled",
            "budgetTokens": 16000,
        }
    elif provider == "azure":
        options["reasoningEffort"] = "high"

    # Add model configuration to provider
    if options:
        provider_config["models"] = {
            model_name: {
                "options": options,
            }
        }

    # Add provider to config
    config["provider"][provider] = provider_config

    # Set default tool permissions
    # Order matters: last matching rule wins
    # Allow all files first, then deny specific files
    config["permission"] = {
        "bash": {
            # Dangerous commands
            "rm": "deny",
            "ssh": "deny",
            "scp": "deny",
            "sftp": "deny",
            "ftp": "deny",
            "telnet": "deny",
            "nc": "deny",
            "netcat": "deny",
            # Block file reading commands to force use of read tool with permissions
            "tac": "deny",
            "nl": "deny",
            "od": "deny",
            "xxd": "deny",
            "hexdump": "deny",
            "strings": "deny",
            "base64": "deny",
            "*": "allow",  # Allow other bash commands
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
        "skill": "allow",
        "question": "allow",
        "webfetch": "allow",
        # External directory permissions:
        # - dev_mode: Allow all external directories for local development
        # - Docker/Kubernetes: Whitelist only specific directories
        "external_directory": (
            "allow"
            if dev_mode
            else {
                "*": "deny",  # Deny all external directories by default
                "/workspace/files": "allow",  # Allow files directory
                "/workspace/files/**": "allow",  # Allow files directory contents
                "/workspace/demo-data": "allow",  # Allow demo data directory
                "/workspace/demo-data/**": "allow",  # Allow demo data directory contents
            }
        ),
    }

    # Disable specified tools via permissions
    if disabled_tools:
        for tool in disabled_tools:
            config["permission"][tool] = "deny"

    return config
